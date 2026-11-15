"""Translate MiniLM similarity thresholds onto Gemini's score scale.

Usage (calls the Gemini API with GEMINI_API_KEY; needs local torch for MiniLM):

    python manage.py calibrate_embeddings

Gemini cosine scores sit higher than MiniLM's, so the A9 cutoffs cannot be
reused as numbers. Each cutoff is instead measured on labeled pairs under
MiniLM and the Gemini cutoff with the same behavior is chosen:

* ``search`` builds Llama's shortlist and favors recall, so Gemini keeps
  MiniLM's recall of relevant/acceptable listings.
* ``fallback``, ``semantic_only``, ``gate`` and ``pricing`` decide what is shown
  without another check, so Gemini keeps MiniLM's false-positive rate.

Search pairs come from the A6/A9 cases (17 queries x eligible listings). Pricing
pairs use held-out MerRec titles: titles already embedded as a type's examples
are excluded so a title is never matched against text that contains it.
"""

import csv
import json
from pathlib import Path
from time import sleep
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from marketplace.embeddings import SIMILARITY_THRESHOLDS, GeminiEncoder, encode_query, load_encoder
from marketplace.management.commands.evaluate_ai import (
    A6_GOLD, A6_LISTINGS, EXTRA_SEARCH_CASES, ndcg5,
)
from marketplace.pricing.initial import SOURCE_PATH, load_source, normalize
from marketplace.pricing.semantic import MODEL_NAME, type_documents
from marketplace.search_semantic import listing_document

OUTPUT_PATH = Path(settings.BASE_DIR) / "docs" / "search-calibration" / "gemini_calibration.json"
# Candidate cutoffs; -0.2 covers MiniLM's negative cosines for unrelated text.
GRID = [round(step * 0.005, 3) for step in range(-40, 201)]
MATCH_RULES = {
    "search": "recall",
    "fallback": "fpr",
    "semantic_only": "fpr",
    "gate": "fpr",
    "pricing": "fpr",
}
PRICING_POSITIVES_PER_TYPE = 6
# The free tier counts every text in a batch against 100 embed requests per
# minute, so calibration sends at most this many new texts per minute.
GEMINI_TEXTS_PER_MINUTE = 80
GEMINI_PAUSE_SECONDS = 61
# Seller input that matches no type; every pair with these is a negative.
JUNK_TITLES = ["asdf qwerty", "zxcv uiop 123", "test test test", "aaaa bbbb cccc"]


def rates(pairs, threshold):
    """Recall of positives and false-positive rate of negatives at a cutoff."""
    positives = [score for score, label in pairs if label]
    negatives = [score for score, label in pairs if not label]
    recall = sum(score >= threshold for score in positives) / len(positives)
    fpr = sum(score >= threshold for score in negatives) / len(negatives)
    return {"recall": round(recall, 4), "fpr": round(fpr, 4)}


def match_threshold(pairs, rule, target):
    """Strictest cutoff keeping recall >= target, or loosest keeping fpr <= target."""
    if rule == "recall":
        return max(t for t in GRID if rates(pairs, t)["recall"] >= target)
    return min(t for t in GRID if rates(pairs, t)["fpr"] <= target)


def auc(pairs):
    """Chance a random positive outscores a random negative (ties count half)."""
    positives = [score for score, label in pairs if label]
    negatives = [score for score, label in pairs if not label]
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return round(wins / (len(positives) * len(negatives)), 4)


def _vectors(values):
    return [[float(value) for value in vector] for vector in values]


def _cosine(left, right):
    # Both encoders return normalized vectors, so the dot product is the cosine.
    return sum(a * b for a, b in zip(left, right))


class Command(BaseCommand):
    help = "Choose Gemini similarity thresholds that match the A9 MiniLM behavior."

    def _encode(self, backend, encoder, texts, *, query=False):
        """Encode texts, pacing Gemini batches to stay under the free-tier quota."""
        def run(chunk):
            if query:
                return encode_query(encoder, chunk)
            return encoder.encode(chunk, normalize_embeddings=True)

        if backend != "gemini":
            return _vectors(run(texts))
        vectors = []
        for start in range(0, len(texts), GEMINI_TEXTS_PER_MINUTE):
            if self._gemini_batches:
                self.stdout.write(f"Waiting {GEMINI_PAUSE_SECONDS}s for the Gemini free-tier quota...")
                sleep(GEMINI_PAUSE_SECONDS)
            vectors += _vectors(run(texts[start:start + GEMINI_TEXTS_PER_MINUTE]))
            self._gemini_batches += 1
        return vectors

    def add_arguments(self, parser):
        parser.add_argument(
            "--datasets", nargs="+", choices=("search", "pricing"), default=["search", "pricing"],
            help="Re-embed only these datasets; other results in the report are kept.",
        )
        parser.add_argument(
            "--set", action="append", default=[], metavar="NAME=VALUE",
            help="Use a chosen Gemini cutoff (e.g. search=0.62) and report its rates "
                 "next to the matched value.",
        )

    def handle(self, *args, **options):
        self._gemini_batches = 0
        if not settings.GEMINI_API_KEY:
            raise CommandError("GEMINI_API_KEY is required for calibration.")
        manual = self._parse_manual(options["set"])
        encoders = {
            "local": load_encoder("local", local_model_name=MODEL_NAME, api_key="",
                                  gemini_model_name=""),
            "gemini": GeminiEncoder(settings.GEMINI_API_KEY,
                                    model_name=settings.GEMINI_EMBEDDING_MODEL),
        }
        report = (json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
                  if OUTPUT_PATH.exists() else {})
        report.update({"gemini_model": settings.GEMINI_EMBEDDING_MODEL, "local_model": MODEL_NAME})
        for key in ("pairs", "auc", "thresholds"):
            report.setdefault(key, {})
        for row in report["thresholds"].values():
            # Reports written before --set existed held only the matched value.
            row.setdefault("matched", {k: v for k, v in row["gemini"].items() if k != "source"})
            row["gemini"].setdefault("source", "matched")
        datasets = {}
        if "search" in options["datasets"]:
            datasets["search"], report["embedding_only_ndcg5"] = self._search_pairs(encoders)
        if "pricing" in options["datasets"]:
            datasets["pricing"] = self._pricing_pairs(encoders)

        for dataset, pairs in datasets.items():
            report["pairs"][dataset] = {"total": len(pairs["local"]),
                                        "positive": sum(label for _, label in pairs["local"])}
            report["auc"][dataset] = {backend: auc(pairs[backend]) for backend in encoders}
        for name, rule in MATCH_RULES.items():
            dataset = "pricing" if name == "pricing" else "search"
            if dataset not in datasets:
                continue
            pairs = datasets[dataset]
            local_cutoff = SIMILARITY_THRESHOLDS["local"][name]
            local_rates = rates(pairs["local"], local_cutoff)
            matched = match_threshold(pairs["gemini"], rule, local_rates[rule])
            row = {
                "rule": f"keep MiniLM {rule}",
                "local": {"threshold": local_cutoff, **local_rates},
                "matched": {"threshold": matched, **rates(pairs["gemini"], matched)},
            }
            chosen = manual.get(name, matched)
            row["gemini"] = {"threshold": chosen, "source": "manual" if name in manual else "matched",
                             **rates(pairs["gemini"], chosen)}
            report["thresholds"][name] = row
        report["proposed_gemini_thresholds"] = {
            name: row["gemini"]["threshold"] for name, row in report["thresholds"].items()
        }
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self._print(report)
        self.stdout.write(self.style.SUCCESS(f"Wrote {OUTPUT_PATH.relative_to(settings.BASE_DIR)}"))

    def _parse_manual(self, values):
        manual = {}
        for value in values:
            name, _, number = value.partition("=")
            if name not in MATCH_RULES:
                raise CommandError(f"--set name must be one of {', '.join(MATCH_RULES)}.")
            try:
                manual[name] = round(float(number), 3)
            except ValueError as error:
                raise CommandError(f"--set {value}: the value must be a number.") from error
        return manual

    # ---------------------------------------------------------------- search
    def _search_pairs(self, encoders):
        listings = json.loads(A6_LISTINGS.read_text(encoding="utf-8"))["results"]
        documents = [
            listing_document({"title": row["title"], "category": row["category"]["name"],
                              "description": row["description"]})
            for row in listings
        ]
        cases = [
            {"case": f"S{gold['query_id']}", "query": gold["query"], "filters": {},
             "relevant": gold["relevant"], "acceptable": gold["acceptable"]}
            for gold in json.loads(A6_GOLD.read_text(encoding="utf-8"))
        ] + EXTRA_SEARCH_CASES
        queries = [case["query"][:200] for case in cases]
        pairs = {backend: [] for backend in encoders}
        ranking = {backend: {} for backend in encoders}
        for backend, encoder in encoders.items():
            doc_vectors = self._encode(backend, encoder, documents)
            query_vectors = self._encode(backend, encoder, queries, query=True)
            for case, query_vector in zip(cases, query_vectors):
                # Price filters shrink the candidate set exactly as browse does.
                max_price = float(case["filters"].get("max_price", "inf"))
                positives = set(case["relevant"]) | set(case["acceptable"])
                scored = []
                for row, doc_vector in zip(listings, doc_vectors):
                    if float(row["price"]) > max_price:
                        continue
                    score = _cosine(query_vector, doc_vector)
                    pairs[backend].append((score, row["id"] in positives))
                    scored.append((score, row["id"]))
                ranked = [listing_id for _, listing_id in sorted(scored, reverse=True)]
                value = ndcg5(ranked, case["relevant"], case["acceptable"])
                if value is not None:
                    ranking[backend][case["case"]] = round(value, 4)
        means = {
            backend: round(sum(values.values()) / len(values), 4)
            for backend, values in ranking.items()
        }
        return pairs, {"mean": means, "cases": ranking}

    # --------------------------------------------------------------- pricing
    def _pricing_pairs(self, encoders):
        records, _ = load_source()
        types = self._source_types()
        eligible, texts = type_documents(records, types)
        queries = []
        for kind, group, examples in eligible:
            held_out = sorted({record.name for record in group if record.name} - set(examples))
            if not held_out:
                continue
            step = max(1, len(held_out) // PRICING_POSITIVES_PER_TYPE)
            for title in held_out[::step][:PRICING_POSITIVES_PER_TYPE]:
                queries.append((title, kind.pk))
        queries += [(title, None) for title in JUNK_TITLES]
        pairs = {backend: [] for backend in encoders}
        for backend, encoder in encoders.items():
            doc_vectors = self._encode(backend, encoder, texts)
            query_vectors = self._encode(backend, encoder, [title for title, _ in queries], query=True)
            for (title, type_id), query_vector in zip(queries, query_vectors):
                for (kind, _, _), doc_vector in zip(eligible, doc_vectors):
                    pairs[backend].append((_cosine(query_vector, doc_vector), kind.pk == type_id))
        return pairs

    def _source_types(self):
        """Display labels for every source type, as sync_pricing_taxonomy adds them."""
        labels = {}
        with SOURCE_PATH.open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                key = (normalize(row["moveon_category"]), normalize(row["moveon_item_type"]))
                labels.setdefault(key, (row["moveon_category"].strip(), row["moveon_item_type"].strip()))
        return [
            SimpleNamespace(pk=index, category_id=index, item_type_name=type_name,
                            category=SimpleNamespace(category_name=category_name))
            for index, (category_name, type_name) in enumerate(labels.values(), start=1)
        ]

    def _print(self, report):
        self.stdout.write(f"Pairs: {json.dumps(report['pairs'])}")
        self.stdout.write(f"AUC: {json.dumps(report['auc'])}")
        self.stdout.write(f"Embedding-only nDCG@5 (mean): {json.dumps(report['embedding_only_ndcg5']['mean'])}")
        self.stdout.write(f"{'name':<14}{'rule':<20}{'MiniLM t / recall / fpr':<28}"
                          f"{'Gemini matched':<28}Gemini chosen")
        for name, row in report["thresholds"].items():
            cells = [
                f"{part['threshold']:<6.3f} {part['recall']:<7.3f} {part['fpr']:<12.3f}"
                for part in (row["local"], row["matched"], row["gemini"])
            ]
            self.stdout.write(f"{name:<14}{row['rule']:<20}" + "".join(cells) + row["gemini"]["source"])
