"""A9 Part 3: evaluate the integrated local AI features through the app code paths.

Usage (use a throwaway database; seeding expects an empty listings table):

    DATABASE_PATH=data/eval.sqlite3 python manage.py migrate
    DATABASE_PATH=data/eval.sqlite3 python manage.py sync_pricing_taxonomy
    DATABASE_PATH=data/eval.sqlite3 python manage.py evaluate_ai --seed --label after

Search cases run through ``browse_context`` (the same function the home and
browse pages render), so candidate selection, the Llama ranking, the lexical
relevance gate, the database recheck, and the random fallback all apply.
Pricing cases call ``suggest_types`` and ``recommend`` as the seller endpoint does.
"""

import json
import math
import statistics
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test import RequestFactory

from marketplace import local_llm
from marketplace.browse import browse_context
from marketplace.models import ItemCategory, ItemType, Listing
from marketplace.pricing.initial import recommend
from marketplace.pricing.semantic import suggest_types, suggestion_source

ROOT = Path(settings.BASE_DIR)
A6_LISTINGS = ROOT / "llm-test" / "listings.json"
A6_GOLD = ROOT / "llm-test" / "gold_labels.json"
OUTPUT_DIR = ROOT / "docs" / "A9-part3"

# Item types for the A6 catalogue (A6 stored only the broad category).
A6_ITEM_TYPES = {
    1: "Chair", 2: "Nightstand", 10: "Sofa", 12: "Bookshelf", 14: "Sofa",
    17: "Coffee Table", 24: "Bookshelf", 26: "Sofa", 27: "Desk", 29: "Dresser",
    33: "Coffee Table", 34: "Dresser", 36: "Coffee Table", 38: "Bookshelf",
    39: "Desk", 3: "Rug", 4: "Curtains", 6: "Lamp", 8: "Curtains", 13: "Vase",
    15: "Planter", 16: "Rug", 19: "Wall Art", 20: "Lamp", 21: "Rug",
    25: "Throw Blanket", 28: "Lamp", 31: "Wall Art", 32: "Lamp", 37: "Pillow",
    40: "Curtains", 5: "Television", 7: "Monitor", 9: "Television",
    18: "Speaker", 22: "Speaker", 30: "Television", 11: "Utensils",
    23: "Microwave", 35: "Microwave",
}

# Search inputs: the eight A6 gold queries plus app-specific edge cases.
EXTRA_SEARCH_CASES = [
    {
        "case": "S9",
        "query": "comfy couch for my apartment",
        "filters": {"max_price": "60"},
        "relevant": [10, 26],
        "acceptable": [],
        "note": "Price filter: only sofas at or under $60 are eligible (Blue Sofa $65 is excluded).",
    },
    {
        "case": "S10",
        "query": "snowboard for winter break",
        "filters": {},
        "relevant": [],
        "acceptable": [],
        "note": "Nothing in the catalogue matches; expect an empty AI result and a labelled fallback.",
    },
]

PRICING_CASES = [
    ("P1", "IKEA Malm 6-drawer dresser, white", "GOOD", "IKEA"),
    ("P2", "Mini fridge for dorm room", "LIKE_NEW", ""),
    ("P3", "LED desk lamp with USB port", "GOOD", ""),
    ("P4", "Queen size memory foam mattress topper", "GOOD", ""),
    ("P5", "Xbox wireless controller", "GOOD", "Microsoft"),
    ("P6", "asdf qwerty", "GOOD", ""),
]


def ndcg5(ranked, relevant, acceptable):
    gains = {**{i: 1 for i in acceptable}, **{i: 2 for i in relevant}}
    dcg = sum(gains.get(i, 0) / math.log2(r + 2) for r, i in enumerate(ranked[:5]))
    ideal = sorted(gains.values(), reverse=True)[:5]
    idcg = sum(g / math.log2(r + 2) for r, g in enumerate(ideal))
    return dcg / idcg if idcg else None


def recall5(ranked, relevant):
    return len(set(ranked[:5]) & set(relevant)) / len(relevant) if relevant else None


class Command(BaseCommand):
    help = "Seed the A6 catalogue and evaluate local AI search and pricing suggestions."

    def add_arguments(self, parser):
        parser.add_argument("--seed", action="store_true", help="Load the 40 A6 listings first.")
        parser.add_argument("--label", default="run", help="Output file suffix, e.g. before/after.")
        parser.add_argument("--skip-search", action="store_true")
        parser.add_argument("--skip-pricing", action="store_true")

    def handle(self, *args, **options):
        if options["seed"]:
            self._seed()
        report = {"label": options["label"], "model": settings.LOCAL_LLM_MODEL_ID}
        if not options["skip_search"]:
            report["search"] = self._evaluate_search()
        if not options["skip_pricing"]:
            report["pricing"] = self._evaluate_pricing()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUT_DIR / f"results_{options['label']}.json"
        path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {path.relative_to(ROOT)}"))

    # ------------------------------------------------------------------ seed
    def _seed(self):
        if Listing.objects.exists():
            raise CommandError("Seeding needs an empty listings table; use a throwaway DATABASE_PATH.")
        rows = json.loads(A6_LISTINGS.read_text(encoding="utf-8"))["results"]
        User = get_user_model()
        with transaction.atomic():
            seller, _ = User.objects.get_or_create(
                username="a9_eval_seller",
                defaults={"email": "a9-eval@example.invalid", "display_name": "Eval Seller"},
            )
            for row in rows:
                category, _ = ItemCategory.objects.get_or_create(category_name=row["category"]["name"])
                kind, _ = ItemType.objects.get_or_create(
                    category=category, item_type_name=A6_ITEM_TYPES[row["id"]]
                )
                Listing(
                    pk=row["id"], seller=seller, item_type=kind, title=row["title"],
                    description=row["description"], condition=row["condition"],
                    listing_price=Decimal(row["price"]), status=Listing.Status.ACTIVE,
                    fulfillment_option=Listing.Fulfillment.PICKUP,
                ).save()
        self.stdout.write(f"Seeded {len(rows)} A6 listings.")

    # ---------------------------------------------------------------- search
    def _search_cases(self):
        cases = []
        for gold in json.loads(A6_GOLD.read_text(encoding="utf-8")):
            cases.append({
                "case": f"S{gold['query_id']}", "query": gold["query"], "filters": {},
                "relevant": gold["relevant"], "acceptable": gold["acceptable"],
                "distractors": gold.get("distractors", []), "note": "A6 gold query",
            })
        return cases + [{"distractors": [], **case} for case in EXTRA_SEARCH_CASES]

    def _evaluate_search(self):
        factory = RequestFactory()
        captured = {}
        original_generate = local_llm._generate_response

        def instrumented(messages):
            started = perf_counter()
            try:
                text = original_generate(messages)
            finally:
                captured["generation_s"] = perf_counter() - started
            captured["raw"] = text
            return text

        local_llm._generate_response = instrumented
        titles = dict(Listing.objects.values_list("pk", "title"))
        results = []
        try:
            load_started = perf_counter()
            local_llm._load_model()
            load_s = perf_counter() - load_started
            for case in self._search_cases():
                captured.clear()
                request = factory.get("/listings/", {"q": case["query"], "search_mode": "ai", **case["filters"]})
                request.user = AnonymousUser()
                started = perf_counter()
                context = browse_context(request, use_local_llm=True)
                total_s = perf_counter() - started
                shown = [item.pk for item in context["listings"]]
                fallback = context["ai_search_fallback"] or bool(context["ai_search_error"])
                raw = captured.get("raw", "")
                try:
                    model_ids = [i for i in json.loads(raw).get("ids", []) if isinstance(i, int)]
                except (ValueError, AttributeError):
                    model_ids = None
                ai_ids = [] if fallback else shown
                results.append({
                    **case,
                    "model_raw": raw,
                    "model_ids": model_ids,
                    "model_titles": [titles.get(i, "?") for i in (model_ids or [])],
                    "shown_ids": shown,
                    "shown_titles": [titles.get(i, "?") for i in shown],
                    "fallback": fallback,
                    "fallback_title": context["ai_search_fallback_title"] or context["ai_search_error"],
                    "ndcg5_shown": ndcg5(ai_ids, case["relevant"], case["acceptable"]),
                    "ndcg5_model": ndcg5(model_ids or [], case["relevant"], case["acceptable"]),
                    "recall5_shown": recall5(ai_ids, case["relevant"]),
                    "distractors_shown": sorted(set(ai_ids) & set(case["distractors"])),
                    "generation_s": round(captured.get("generation_s", 0.0), 2),
                    "request_s": round(total_s, 2),
                })
                self.stdout.write(
                    f"{case['case']:>4} {total_s:5.1f}s fallback={fallback!s:5} "
                    f"model={model_ids} shown={shown} :: {case['query']}"
                )
        finally:
            local_llm._generate_response = original_generate
        gold = [r for r in results if r["case"] in {f"S{i}" for i in range(1, 9)}]
        summary = {
            "model_load_s": round(load_s, 1),
            "gold_queries": len(gold),
            "mean_ndcg5_shown": round(statistics.mean(r["ndcg5_shown"] for r in gold), 3),
            "mean_ndcg5_model_before_gate": round(statistics.mean(r["ndcg5_model"] for r in gold), 3),
            "mean_recall5_shown": round(statistics.mean(r["recall5_shown"] for r in gold), 3),
            "fallback_count": sum(r["fallback"] for r in results),
            "median_generation_s": round(statistics.median(r["generation_s"] for r in results), 2),
            "median_request_s": round(statistics.median(r["request_s"] for r in results), 2),
        }
        self.stdout.write(json.dumps(summary))
        return {"summary": summary, "cases": results}

    # --------------------------------------------------------------- pricing
    def _evaluate_pricing(self):
        records, _ = suggestion_source()
        types = ItemType.objects.select_related("category")
        started = perf_counter()
        suggest_types(records, types, title="warm up", category="", item_type="")
        warmup_s = perf_counter() - started
        results = []
        for case, title, condition, brand in PRICING_CASES:
            started = perf_counter()
            candidates = suggest_types(records, types, title=title, category="", item_type="")
            for candidate in candidates:
                guide = recommend(records, category=candidate["category"], item_type=candidate["item_type"],
                                  condition=condition, brand=brand)
                candidate["price_guide"] = {
                    key: guide.get(key) for key in
                    ("method", "suggested_listing_price", "range_low", "range_high",
                     "evidence_grade", "comparable_count")
                }
            elapsed = perf_counter() - started
            results.append({"case": case, "title": title, "condition": condition, "brand": brand,
                            "candidates": candidates, "latency_s": round(elapsed, 3)})
            top = candidates[0] if candidates else None
            self.stdout.write(
                f"{case:>4} {elapsed:5.2f}s :: {title} -> "
                + (f"{top['category']} / {top['item_type']} ({top['similarity']}) "
                   f"${top['price_guide']['suggested_listing_price']}" if top else "no suggestion")
            )
        return {"warmup_s": round(warmup_s, 2), "cases": results}
