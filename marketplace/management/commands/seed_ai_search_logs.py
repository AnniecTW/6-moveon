"""Generate simulated AISearchLog history for the analytics dashboard.

Usage:

    python manage.py seed_ai_search_logs                 # 14 days, about 600 searches
    python manage.py seed_ai_search_logs --replace       # drop earlier simulated rows first

Every row is marked is_simulated=True, so the dashboard can show or hide it and
real logs are never touched. Distributions follow measurements from the live
system on 2026-11-15 (local server, Gemini embeddings + Groq gpt-oss-20b):

* Embedding: about 0.2 s when only the query is embedded (cache hit), about
  1.3 s when all listings are re-embedded (cache miss, 43 texts / ~3,200 chars).
* Groq ranking: median about 0.32 s; prompt tokens grow by about 44 per
  candidate from a ~175-token base; ~40-70 completion tokens, most of them reasoning.
* Free-tier limits: a class demo sends 80 AI searches in 4 minutes, about
  11K tokens/minute against Groq's 8K, so a third fall back with
  ``rate_limited``; Gemini's 100 texts/minute limit causes rare ``unavailable``.
"""

import random
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from marketplace.models import AISearchLog

# (query, typical AI result count when matched, keyword result count)
AI_STYLE_QUERIES = [
    ("storage for books beside my study desk", 3, 0),
    ("somewhere to sit in a small apartment", 4, 0),
    ("block morning sunlight in my bedroom", 1, 0),
    ("something to heat leftovers in my dorm", 3, 0),
    ("blue accent for a living room", 2, 0),
    ("decor for my living room", 4, 0),
    ("comfy couch for my apartment", 2, 0),
    ("small screen for my desk under $50", 1, 0),
    ("lighting for a dark bedroom", 3, 0),
    ("cheap desk for studying", 2, 1),
    ("furniture to store clothes", 2, 0),
    ("cozy reading chair for a dorm room", 2, 0),
]
SHORT_QUERIES = [
    ("lamp", 3, 4), ("desk", 2, 3), ("sofa", 3, 3), ("microwave", 3, 3), ("bookshelf", 3, 3),
    ("rug", 3, 3), ("curtains", 3, 3), ("chair", 3, 2), ("tv", 2, 2), ("dresser", 2, 2),
]
NO_MATCH_QUERIES = [
    ("snowboard for winter break", 0, 0), ("mini fridge", 0, 0), ("textbooks for chem 102", 0, 0),
    ("bike", 0, 0), ("printer", 0, 0),
]
FILTER_RATES = {"max_price": 0.28, "category": 0.16, "condition": 0.07, "fulfillment": 0.05,
                "item_type": 0.04, "min_price": 0.03, "bundle": 0.02}
DEMO_SEARCHES = 80
DEMO_SECONDS = 240
# Shoppers browse more in the afternoon and evening (local hours).
HOUR_WEIGHTS = [1, 1, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 6, 6, 7, 8, 9, 10, 10, 9, 7, 4, 2]


class Command(BaseCommand):
    help = "Insert simulated AI and keyword search logs (is_simulated=True)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--searches", type=int, default=600)
        parser.add_argument("--seed", type=int, default=490)
        parser.add_argument("--replace", action="store_true",
                            help="Delete existing simulated rows first; real rows are kept.")

    def handle(self, *args, **options):
        if options["days"] < 1 or options["searches"] < 1:
            raise CommandError("--days and --searches must be positive.")
        rng = random.Random(options["seed"])
        # Campus time, so the afternoon and evening peaks fall at Illinois hours.
        now = timezone.localtime(timezone=ZoneInfo(settings.ANALYTICS_TIME_ZONE))
        rows = [self._row(rng, created_at) for created_at in self._timestamps(rng, now, options)]
        with transaction.atomic():
            removed = AISearchLog.objects.filter(is_simulated=True).delete()[0] if options["replace"] else 0
            AISearchLog.objects.bulk_create(rows, batch_size=500)
        self.stdout.write(self.style.SUCCESS(
            f"Inserted {len(rows)} simulated searches over {options['days']} days"
            + (f" (removed {removed} earlier simulated rows)." if options["replace"] else ".")
        ))

    def _timestamps(self, rng, now, options):
        days, total = options["days"], options["searches"]
        # A class-demo spike: 80 AI searches in four minutes, three days ago.
        self.demo_hour = (now - timedelta(days=min(3, days - 1))).replace(hour=15, minute=0, second=0,
                                                                         microsecond=0)
        # With --days 1 before 3 pm the burst would be in the future; end it now instead.
        self.demo_hour = min(self.demo_hour, now - timedelta(seconds=DEMO_SECONDS))
        stamps = []
        # Traffic grows slightly over the window as more students discover the site.
        weights = [0.75 + 0.5 * index / max(1, days - 1) for index in range(days)]
        while len(stamps) < max(0, total - DEMO_SEARCHES):
            day = rng.choices(range(days), weights=weights)[0]
            hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
            stamp = (now - timedelta(days=days - 1 - day)).replace(
                hour=hour, minute=rng.randrange(60), second=rng.randrange(60), microsecond=0)
            # Redraw times later today that have not happened yet, keeping the count exact.
            if stamp <= now:
                stamps.append(stamp)
        stamps += [self.demo_hour + timedelta(seconds=rng.randrange(DEMO_SECONDS))
                   for _ in range(min(total, DEMO_SEARCHES))]
        return sorted(stamps)

    def _row(self, rng, created_at):
        in_demo = 0 <= (created_at - self.demo_hour).total_seconds() < DEMO_SECONDS
        # AI search adoption: about two thirds of searches, nearly all during the demo.
        mode = "ai" if in_demo or rng.random() < 0.66 else "keyword"
        pool = rng.choices([AI_STYLE_QUERIES, SHORT_QUERIES, NO_MATCH_QUERIES],
                           weights=[6, 3, 1] if mode == "ai" else [2, 7, 1])[0]
        query, ai_results, keyword_results = rng.choice(pool)
        filters = [name for name, rate in FILTER_RATES.items() if rng.random() < rate]
        row = AISearchLog(created_at=created_at, mode=mode, query=query, filters_used=filters,
                          is_simulated=True)
        if mode == "keyword":
            row.result_count = max(0, keyword_results + rng.choice([-1, 0, 0, 1])) if keyword_results else 0
            row.total_ms = rng.randint(5, 35)
            return row
        return self._ai_row(rng, row, ai_results, in_demo)

    def _ai_row(self, rng, row, ai_results, in_demo):
        row.candidate_count = rng.randint(30, 45)
        row.embedding_model = "gemini-embedding-001"
        cache_miss = rng.random() < 0.08
        row.embedding_texts_sent = row.candidate_count + 1 if cache_miss else 1
        row.embedding_chars = 75 * row.candidate_count + len(row.query) if cache_miss else len(row.query)
        row.embedding_ms = round(rng.lognormvariate(7.17, 0.15) if cache_miss else rng.lognormvariate(5.3, 0.3))
        overhead = rng.randint(12, 45)
        if rng.random() < (0.02 if in_demo else 0.008):
            # Gemini free tier: 100 embedded texts per minute.
            row.state, row.embedding_error = "unavailable", "rate_limited"
            row.embedding_texts_sent, row.embedding_chars, row.retrieved_count = 0, 0, 0
            row.result_count, row.total_ms = 0, row.embedding_ms + overhead
            return row
        row.retrieved_count = 0 if ai_results == 0 and rng.random() < 0.7 else rng.randint(max(1, ai_results), 8)
        if row.retrieved_count == 0:
            row.state, row.result_count, row.total_ms = "no_results", 0, row.embedding_ms + overhead
            return row
        row.llm_model = "openai/gpt-oss-20b"
        llm_failure = rng.random() < (0.35 if in_demo else 0.015)
        timeout = not llm_failure and rng.random() < 0.006
        if llm_failure or timeout:
            row.llm_error = "rate_limited" if llm_failure else "timeout"
            row.state = "semantic_fallback_error"
            row.result_count = rng.randint(1, min(5, row.retrieved_count))
            # A 429 returns quickly; a timeout waits the full 15 s. Either is LLM time.
            row.llm_ms = rng.randint(80, 200) if llm_failure else 15_000
            row.total_ms = row.embedding_ms + row.llm_ms + overhead
            return row
        row.llm_ms = round(rng.lognormvariate(5.77, 0.25))
        row.prompt_tokens = round((175 + 44 * row.retrieved_count) * rng.uniform(0.95, 1.05))
        row.reasoning_tokens = rng.randint(15, 60)
        row.completion_tokens = row.reasoning_tokens + rng.randint(8, 25)
        row.total_ms = row.embedding_ms + row.llm_ms + overhead
        if ai_results == 0:
            row.state, row.result_count = "no_results", 0
        elif rng.random() < 0.05:
            row.state = "semantic_fallback_empty"
            row.result_count = rng.randint(1, min(3, row.retrieved_count))
        else:
            row.state = "ai"
            row.result_count = max(1, min(row.retrieved_count, ai_results + rng.choice([-1, 0, 0, 1])))
        return row
