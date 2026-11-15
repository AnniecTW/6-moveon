"""Compare Gemini-only listing search with Gemini + Groq reranking on the A9 cases.

Usage (calls Gemini once and Groq once per case with GEMINI_API_KEY/GROQ_API_KEY):

    python manage.py compare_ranking_backends

The command replays browse_context's AI path without a database: price filters,
Gemini retrieval (search cutoff, top 8), then either the semantic-only display
rule (what PythonAnywhere runs today) or an LLM rerank through the app's prompt,
parser and relevance gate, including its fallback. A9's local Llama-3.2-3B
results for the same cases are read from docs/A9-part3/results_after.json.
Writes docs/search-calibration/ranking_comparison.json.
"""

import json
import statistics
from collections import deque
from pathlib import Path
from time import monotonic, perf_counter, sleep

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings

from marketplace.embeddings import GeminiEncoder, encode_query, similarity_threshold
from marketplace.local_llm import (
    LocalLLMError, RankingServiceError, _build_messages, _listing_payload, gate_listing_ids,
    groq_chat, parse_listing_ids,
)
from marketplace.management.commands.evaluate_ai import (
    A6_GOLD, A6_ITEM_TYPES, A6_LISTINGS, EXTRA_SEARCH_CASES, ndcg5, recall5,
)
from marketplace.search_semantic import MAX_RERANK_CANDIDATES, listing_document

ROOT = Path(settings.BASE_DIR)
OUTPUT_PATH = ROOT / "docs" / "search-calibration" / "ranking_comparison.json"
A9_RESULTS = ROOT / "docs" / "A9-part3" / "results_after.json"
# USD per 1M input/output tokens (console.groq.com/docs/models, checked 2026-11-15).
GROQ_PRICES = {"openai/gpt-oss-20b": (0.075, 0.30), "openai/gpt-oss-120b": (0.15, 0.60)}
# The free tier allows 8K tokens per minute; stay under it with headroom.
TOKENS_PER_MINUTE_BUDGET = 7000
GOLD_CASES = {f"S{n}" for n in range(1, 9)}


class TokenPacer:
    """Sleep before a request when the last minute's tokens would exceed the budget."""

    def __init__(self, budget):
        self.budget = budget
        self.window = deque()

    def wait(self, expected_tokens):
        while True:
            now = monotonic()
            while self.window and now - self.window[0][0] >= 60:
                self.window.popleft()
            if sum(tokens for _, tokens in self.window) + expected_tokens <= self.budget:
                return
            sleep(60 - (now - self.window[0][0]) + 0.5)

    def record(self, tokens):
        self.window.append((monotonic(), tokens))


def groq_with_retry(messages, *, api_key, model, retries=2):
    """The app never retries; this offline run waits out 429s to finish every case."""
    for attempt in range(retries + 1):
        try:
            return groq_chat(messages, api_key=api_key, model=model)
        except RankingServiceError as error:
            if error.reason != "rate_limited" or attempt == retries:
                raise
            sleep(float(error.retry_after or 10) + 0.5)


def _labels(case):
    return set(case["relevant"]) | set(case["acceptable"])


def _metrics(shown, case):
    value = ndcg5(shown, case["relevant"], case["acceptable"])
    recall = recall5(shown, case["relevant"])
    return {
        "shown_ids": shown,
        "ndcg5": None if value is None else round(value, 4),
        "recall5": None if recall is None else round(recall, 4),
        "false_positives": sum(listing_id not in _labels(case) for listing_id in shown),
    }


def _mean(values):
    values = [value for value in values if value is not None]
    return round(statistics.mean(values), 4) if values else None


class Command(BaseCommand):
    help = "Compare Gemini-only search with Gemini + Groq reranking on the A9 cases."

    def add_arguments(self, parser):
        parser.add_argument("--model", default="openai/gpt-oss-20b")

    def handle(self, *args, **options):
        api_key = settings.GROQ_API_KEY
        if not api_key or not settings.GEMINI_API_KEY:
            raise CommandError("GROQ_API_KEY and GEMINI_API_KEY are both required.")
        with override_settings(EMBEDDING_BACKEND="gemini"):
            report = self._compare(api_key, options["model"])
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self._print(report)
        self.stdout.write(self.style.SUCCESS(f"Wrote {OUTPUT_PATH.relative_to(ROOT)}"))

    def _compare(self, api_key, model):
        listings = json.loads(A6_LISTINGS.read_text(encoding="utf-8"))["results"]
        # Same candidate shape as browse._local_llm_candidates after seeding.
        candidates = [{
            "pk": row["id"], "title": row["title"], "description": row["description"],
            "listing_price": row["price"], "condition": row["condition"],
            "category": f"{row['category']['name']} / {A6_ITEM_TYPES[row['id']]}",
        } for row in listings]
        cases = [
            {"case": f"S{gold['query_id']}", "query": gold["query"], "filters": {},
             "relevant": gold["relevant"], "acceptable": gold["acceptable"]}
            for gold in json.loads(A6_GOLD.read_text(encoding="utf-8"))
        ] + EXTRA_SEARCH_CASES
        a9 = {case["case"]: case for case in json.loads(A9_RESULTS.read_text(encoding="utf-8"))["search"]["cases"]}

        encoder = GeminiEncoder(settings.GEMINI_API_KEY, model_name=settings.GEMINI_EMBEDDING_MODEL)
        doc_vectors = encoder.encode([listing_document(item) for item in candidates])
        query_vectors = encode_query(encoder, [case["query"][:200] for case in cases])
        cutoffs = {name: similarity_threshold(name)
                   for name in ("search", "semantic_only", "fallback")}
        pacer = TokenPacer(TOKENS_PER_MINUTE_BUDGET)
        expected_tokens = 1500
        rows = []
        for case, query_vector in zip(cases, query_vectors):
            max_price = float(case["filters"].get("max_price", "inf"))
            scored = [
                (item, sum(a * b for a, b in zip(query_vector, vector)))
                for item, vector in zip(candidates, doc_vectors)
                if float(item["listing_price"]) <= max_price
            ]
            retrieved = sorted(
                [(item, score) for item, score in scored if score >= cutoffs["search"]],
                key=lambda row: (-row[1], row[0]["pk"]),
            )[:MAX_RERANK_CANDIDATES]
            # Semantic-only display rule (LOCAL_LLM_ENABLED=False).
            gemini_only = [item["pk"] for item, score in retrieved
                           if score >= cutoffs["semantic_only"]][:5]
            row = {"case": case["case"], "query": case["query"],
                   "candidate_ids": [item["pk"] for item, _ in retrieved],
                   "gemini_only": _metrics(gemini_only, case)}
            row["groq"] = self._rank_with_groq(case, retrieved, cutoffs, api_key, model, pacer,
                                               expected_tokens)
            if row["groq"].get("total_tokens"):
                expected_tokens = row["groq"]["total_tokens"] + 200
            previous = a9.get(case["case"])
            if previous:
                row["a9_llama"] = {**_metrics(previous["shown_ids"], case),
                                   "seconds": round(previous["generation_s"], 2)}
            rows.append(row)
            self.stdout.write(
                f"{case['case']:>4} gemini={row['gemini_only']['ndcg5']} "
                f"groq={row['groq']['ndcg5']} ({row['groq']['state']}) "
                f"a9={row.get('a9_llama', {}).get('ndcg5')}"
            )
        return {"groq_model": model, "embedding_model": settings.GEMINI_EMBEDDING_MODEL,
                "cutoffs": cutoffs, "summary": self._summary(rows, model), "cases": rows}

    def _rank_with_groq(self, case, retrieved, cutoffs, api_key, model, pacer, expected_tokens):
        if not retrieved:
            return {**_metrics([], case), "state": "no_results", "called": False}
        relevant_candidates = [item for item, _ in retrieved]
        gate_catalog = [{**item, "id": item["pk"]} for item in relevant_candidates]
        # The fallback stays word-gated, exactly as in browse_context.
        fallback_ids = gate_listing_ids(
            case["query"], [item["pk"] for item, score in retrieved if score >= cutoffs["fallback"]],
            gate_catalog,
        )[:5]
        catalog = _listing_payload(relevant_candidates)
        result = {"called": True}
        pacer.wait(expected_tokens)
        try:
            content, usage, seconds = groq_with_retry(_build_messages(case["query"], catalog),
                                                      api_key=api_key, model=model)
            pacer.record(usage.get("total_tokens", expected_tokens))
            result.update({
                "raw": content, "seconds": round(seconds, 3),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                "total_tokens": usage.get("total_tokens"),
            })
            ids = parse_listing_ids(content, [item["id"] for item in catalog])
            ranked = gate_listing_ids(case["query"], ids, catalog,
                                      {item["pk"]: score for item, score in retrieved})
            if ranked:
                state, shown = "ai", ranked
            else:
                shown = fallback_ids
                state = "semantic_fallback_empty" if shown else "no_results"
        except LocalLLMError as error:
            pacer.record(expected_tokens)
            result["error"] = str(error)
            shown = fallback_ids
            state = "semantic_fallback_error" if shown else "unavailable"
        return {**result, **_metrics(shown, case), "state": state}

    def _summary(self, rows, model):
        input_price, output_price = GROQ_PRICES.get(model, (None, None))
        called = [row["groq"] for row in rows if row["groq"].get("seconds") is not None]
        no_match = [row for row in rows if row["case"] in {"S10", "S17"}]
        summary = {}
        for method in ("gemini_only", "groq", "a9_llama"):
            present = [row for row in rows if method in row]
            summary[method] = {
                "mean_ndcg5_gold8": _mean(row[method]["ndcg5"] for row in present
                                          if row["case"] in GOLD_CASES),
                "mean_ndcg5_all_labeled": _mean(row[method]["ndcg5"] for row in present),
                "mean_recall5_all_labeled": _mean(row[method]["recall5"] for row in present),
                "false_positives_total": sum(row[method]["false_positives"] for row in present),
                "no_match_cases_empty": sum(not row[method]["shown_ids"] for row in no_match
                                            if method in row),
                "cases": len(present),
            }
        summary["groq"].update({
            "states": {state: sum(row["groq"]["state"] == state for row in rows)
                       for state in sorted({row["groq"]["state"] for row in rows})},
            "median_seconds": round(statistics.median(c["seconds"] for c in called), 3) if called else None,
            "mean_prompt_tokens": _mean(c["prompt_tokens"] for c in called),
            "mean_completion_tokens": _mean(c["completion_tokens"] for c in called),
            "mean_reasoning_tokens": _mean(c["reasoning_tokens"] for c in called),
        })
        if input_price is not None and called:
            per_request = statistics.mean(
                (c["prompt_tokens"] * input_price + c["completion_tokens"] * output_price) / 1_000_000
                for c in called
            )
            summary["groq"]["paid_tier_usd_per_request"] = round(per_request, 8)
        summary["a9_llama"]["median_seconds"] = statistics.median(
            row["a9_llama"]["seconds"] for row in rows if "a9_llama" in row
        )
        return summary

    def _print(self, report):
        self.stdout.write(json.dumps(report["summary"], indent=2))
