"""Aggregate AISearchLog rows into the AI search analytics dashboard.

Every widget answers one question from the A10 analytics design:
system performance (P1-P3), user behavior (U1-U3) and cost (C1-C3).
Aggregation is plain Python so it runs where pandas is not installed.
"""

import math
import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

# Validated categorical palette (dataviz reference, light mode), assigned in
# slot order so adjacent colors stay distinguishable for color-blind readers.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
NEUTRAL = "#b5b0a6"
INK, MUTED, GRID = "#35332f", "#78736a", "#ece9e2"

OUTCOMES = [
    ("ai", "Ranked by AI", BLUE),
    ("semantic_only", "Semantic only", ORANGE),
    ("semantic_fallback_empty", "LLM found no pick", AQUA),
    ("semantic_fallback_error", "LLM failed, fallback", YELLOW),
    ("unavailable", "AI unavailable", MAGENTA),
    ("no_results", "No close matches", NEUTRAL),
]
OUTCOME_LABELS = {state: label for state, label, _ in OUTCOMES}
DEGRADED_STATES = {"semantic_fallback_error", "unavailable"}
FILTER_LABELS = {
    "category": "Category", "item_type": "Item type", "condition": "Condition",
    "fulfillment": "Fulfillment", "min_price": "Min price", "max_price": "Max price",
    "bundle": "Bundle eligible",
}
# A7 daily cost ranges (docs/A7-part1/system_design.md section 2.5) at 5 requests/DAU/day.
A7_REQUESTS_PER_DAU = 5
A7_DAILY_COST = [
    # DAU, AWS self-host low/high, HF API low/high (USD per day)
    (1_000, 28.90, 28.90, 0.02, 0.23),
    (10_000, 57.79, 260.06, 0.24, 2.25),
    (100_000, 433.44, 2513.95, 2.40, 22.50),
    (1_000_000, 4189.92, 24966.14, 24.05, 225.05),
    (10_000_000, 41812.51, 249430.27, 240.46, 2250.50),
    (100_000_000, 417922.85, 2494100.45, 2404.60, 22505.00),
]
RANGES = {"7": 7, "30": 30, "all": None}
SOURCES = {"all": None, "real": False, "simulated": True}


def percentile(values, q):
    """Linear-interpolated percentile (q in 0-100) of a non-empty list."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q / 100
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def search_cost(row):
    """Paid-tier USD for one logged search, split by component."""
    prices = settings.AI_TOKEN_PRICES
    llm = prices.get(row["llm_model"] or "", {})
    embedding = prices.get(row["embedding_model"] or "", {})
    embed_tokens = (row["embedding_chars"] or 0) / settings.EMBEDDING_CHARS_PER_TOKEN
    return {
        "llm_input": (row["prompt_tokens"] or 0) * llm.get("input", 0) / 1e6,
        # Completion tokens already include the model's reasoning tokens.
        "llm_output": (row["completion_tokens"] or 0) * llm.get("output", 0) / 1e6,
        "embedding": embed_tokens * embedding.get("input", 0) / 1e6,
    }


def _day(row):
    return timezone.localtime(row["created_at"]).date()


def _base_spec(height=220, **extra):
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "width": "container", "height": height, "background": "transparent",
        "config": {
            "font": "system-ui, sans-serif",
            "view": {"stroke": None},
            "axis": {"labelColor": MUTED, "titleColor": MUTED, "gridColor": GRID,
                     "domainColor": GRID, "tickColor": GRID, "labelFontSize": 11,
                     "titleFontSize": 11, "titleFontWeight": "normal"},
            # Recessive grid: horizontal guides only.
            "axisX": {"grid": False},
            "axisY": {"grid": True, "gridColor": GRID},
            "legend": {"labelColor": INK, "titleColor": MUTED, "orient": "top",
                       "labelFontSize": 11, "titleFontSize": 11, "titleFontWeight": "normal"},
            "bar": {"cornerRadiusEnd": 4},
            "line": {"strokeWidth": 2},
        },
        **extra,
    }


def _color(labels_colors, title=None):
    return {"field": "series", "type": "nominal", "title": title,
            "scale": {"domain": [label for label, _ in labels_colors],
                      "range": [color for _, color in labels_colors]}}


def _chart(spec, columns, rows, caption):
    return {"spec": spec, "table": {"columns": columns, "rows": rows}, "caption": caption}


class Report:
    def __init__(self, rows, *, days, now=None):
        self.rows = rows
        self.ai = [row for row in rows if row["mode"] == "ai"]
        self.days = days
        self.now = now or timezone.now()

    def build(self):
        if not self.rows:
            return {"empty": True}
        return {
            "empty": False,
            "kpis": self.kpis(),
            "charts": {
                "latency": self.latency_distribution(),
                "stages": self.stage_breakdown(),
                "outcomes": self.outcomes_by_day(),
                "modes": self.searches_by_day(),
                "query_length": self.query_length(),
                "filters": self.filter_usage(),
                "cost_daily": self.cost_by_day(),
                "tokens": self.tokens_vs_candidates(),
                "projection": self.cost_projection(),
            },
            "tables": {
                "errors": self.error_codes(),
                "top_queries": self.top_queries(),
                "zero_result_queries": self.zero_result_queries(),
                "token_heavy": self.token_heavy_queries(),
            },
        }

    # ------------------------------------------------------------- headline
    def kpis(self):
        ai_latency = [row["total_ms"] / 1000 for row in self.ai]
        degraded = sum(row["state"] in DEGRADED_STATES for row in self.ai)
        costs = [sum(search_cost(row).values()) for row in self.ai]
        groq_minutes = Counter()
        groq_days = Counter()
        for row in self.ai:
            tokens = (row["prompt_tokens"] or 0) + (row["completion_tokens"] or 0)
            if tokens:
                stamp = timezone.localtime(row["created_at"])
                groq_minutes[stamp.replace(second=0, microsecond=0)] += tokens
                groq_days[stamp.date()] += tokens
        limits = settings.AI_FREE_TIER_LIMITS
        return {
            "searches": len(self.rows),
            "ai_searches": len(self.ai),
            "ai_share": len(self.ai) / len(self.rows),
            "p50_s": percentile(ai_latency, 50) if ai_latency else None,
            "p95_s": percentile(ai_latency, 95) if ai_latency else None,
            "degraded_rate": degraded / len(self.ai) if self.ai else None,
            "degraded": degraded,
            "cost_per_1k": statistics.mean(costs) * 1000 if costs else None,
            "cost_p95_per_1k": percentile(costs, 95) * 1000 if costs else None,
            "peak_tpm": max(groq_minutes.values(), default=0),
            "tpm_limit": limits["groq_tokens_per_minute"],
            "peak_tpd": max(groq_days.values(), default=0),
            "tpd_limit": limits["groq_tokens_per_day"],
        }

    # ------------------------------------------------- system performance
    def latency_distribution(self):
        """P1: how AI search latency is distributed, with p50/p95 marked."""
        values = [{"seconds": round(row["total_ms"] / 1000, 3)} for row in self.ai]
        if not values:
            return None
        seconds = [value["seconds"] for value in values]
        markers = [{"label": f"p50 {percentile(seconds, 50):.2f}s", "seconds": percentile(seconds, 50)},
                   {"label": f"p95 {percentile(seconds, 95):.2f}s", "seconds": percentile(seconds, 95)}]
        spec = _base_spec(layer=[
            {"data": {"values": values}, "mark": {"type": "bar", "color": BLUE, "binSpacing": 2},
             "encoding": {
                 "x": {"field": "seconds", "bin": {"maxbins": 30}, "title": "AI search time (s)"},
                 "y": {"aggregate": "count", "title": "Searches"},
                 "tooltip": [{"field": "seconds", "bin": {"maxbins": 30}, "title": "Seconds"},
                             {"aggregate": "count", "title": "Searches"}]}},
            {"data": {"values": markers}, "mark": {"type": "rule", "color": INK, "strokeDash": [4, 3]},
             "encoding": {"x": {"field": "seconds", "type": "quantitative"},
                          "tooltip": [{"field": "label", "title": "Percentile"}]}},
            {"data": {"values": markers},
             "mark": {"type": "text", "align": "left", "dx": 4, "dy": -4, "color": INK, "fontSize": 11},
             "encoding": {"x": {"field": "seconds", "type": "quantitative"},
                          "y": {"value": 8}, "text": {"field": "label"}}},
        ])
        buckets = Counter(min(int(value // 0.5) * 0.5, 5.0) for value in seconds)
        rows = [[f"{start:.1f}–{start + 0.5:.1f}s" if start < 5 else "5.0s+", count]
                for start, count in sorted(buckets.items())]
        return _chart(spec, ["Time", "Searches"], rows, f"n = {len(values)} AI searches")

    def _stage_group(self, row):
        if row["embedding_texts_sent"] is None:
            return "Local models"
        # One text is the query itself; more means listings missed the cache.
        return "Cache miss" if row["embedding_texts_sent"] > 1 else "Cache hit"

    def stage_breakdown(self):
        """P2: which stage dominates AI search time, with and without cache hits."""
        groups = defaultdict(list)
        for row in self.ai:
            if row["embedding_ms"] is not None:
                groups[self._stage_group(row)].append(row)
        if not groups:
            return None
        series = [("Embedding retrieval", BLUE), ("LLM ranking", ORANGE), ("Other server work", NEUTRAL)]
        values, rows = [], []
        for group, items in sorted(groups.items()):
            embed = statistics.mean(row["embedding_ms"] for row in items)
            llm = statistics.mean(row["llm_ms"] or 0 for row in items)
            other = max(0.0, statistics.mean(row["total_ms"] for row in items) - embed - llm)
            label = f"{group} (n={len(items)})"
            for index, ((name, _), value) in enumerate(zip(series, (embed, llm, other))):
                values.append({"group": label, "series": name, "ms": round(value), "order": index})
            rows.append([group, len(items), round(embed), round(llm), round(other)])
        spec = _base_spec(height=40 + 44 * len(groups), data={"values": values},
                          mark={"type": "bar", "stroke": "#fffefa", "strokeWidth": 2},
                          encoding={
                              "y": {"field": "group", "type": "nominal", "title": None, "sort": None,
                                    "axis": {"grid": False}},
                              "x": {"field": "ms", "type": "quantitative", "stack": True,
                                    "title": "Mean time (ms)", "axis": {"grid": True}},
                              "color": _color(series),
                              "order": {"field": "order", "type": "quantitative"},
                              "tooltip": [{"field": "group", "title": "Group"},
                                          {"field": "series", "title": "Stage"},
                                          {"field": "ms", "title": "Mean ms"}]})
        return _chart(spec, ["Group", "Searches", "Embedding ms", "LLM ms", "Other ms"], rows,
                      "Mean time per stage. A cache miss re-embeds listings (after a deploy "
                      "or when listings change); a hit embeds only the query.")

    def outcomes_by_day(self):
        """P3: how often AI search degrades or fails, day by day."""
        counts = Counter((_day(row), row["state"] or "no_results") for row in self.ai)
        if not counts:
            return None
        series = [(label, color) for _, label, color in OUTCOMES]
        order = {state: index for index, (state, _, _) in enumerate(OUTCOMES)}
        values = [{"day": day.isoformat(), "series": OUTCOME_LABELS.get(state, state), "count": count,
                   "order": order.get(state, len(order))}
                  for (day, state), count in sorted(counts.items())]
        spec = _base_spec(data={"values": values},
                          mark={"type": "bar", "stroke": "#fffefa", "strokeWidth": 1},
                          encoding={
                              "x": {"field": "day", "type": "temporal", "timeUnit": "yearmonthdate",
                                    "title": None, "axis": {"format": "%b %d"}},
                              "y": {"field": "count", "type": "quantitative", "stack": True,
                                    "title": "AI searches"},
                              "color": _color(series, "Outcome"),
                              "order": {"field": "order", "type": "quantitative"},
                              "tooltip": [{"field": "day", "type": "temporal", "title": "Day"},
                                          {"field": "series", "title": "Outcome"},
                                          {"field": "count", "title": "Searches"}]})
        totals = Counter(row["state"] or "no_results" for row in self.ai)
        rows = [[label, totals.get(state, 0), f"{totals.get(state, 0) / len(self.ai):.1%}"]
                for state, label, _ in OUTCOMES]
        return _chart(spec, ["Outcome", "Searches", "Share"], rows,
                      f"n = {len(self.ai)} AI searches")

    def error_codes(self):
        """P3 detail: which service failed and why (rate limits, timeouts)."""
        counts = Counter()
        for row in self.ai:
            if row["llm_error"]:
                counts[("LLM ranking (Groq)", row["llm_error"])] += 1
            if row["embedding_error"]:
                counts[("Embedding (Gemini)", row["embedding_error"])] += 1
        total = len(self.ai) or 1
        return [[stage, code, count, f"{count / total:.1%}"]
                for (stage, code), count in counts.most_common()]

    # ------------------------------------------------------- user behavior
    def searches_by_day(self):
        """U1: how often AI search is used compared with keyword search."""
        counts = Counter((_day(row), row["mode"]) for row in self.rows)
        days = sorted({day for day, _ in counts})
        names = {"ai": "AI search", "keyword": "Keyword search"}
        values = [{"day": day.isoformat(), "series": names[mode], "count": counts.get((day, mode), 0)}
                  for day in days for mode in ("ai", "keyword")]
        series = [("AI search", BLUE), ("Keyword search", ORANGE)]
        spec = _base_spec(data={"values": values},
                          mark={"type": "line", "point": {"size": 64, "filled": True}},
                          encoding={
                              "x": {"field": "day", "type": "temporal", "timeUnit": "yearmonthdate",
                                    "title": None, "axis": {"format": "%b %d"}},
                              "y": {"field": "count", "type": "quantitative", "title": "Searches per day"},
                              "color": _color(series),
                              "tooltip": [{"field": "day", "type": "temporal", "title": "Day"},
                                          {"field": "series", "title": "Mode"},
                                          {"field": "count", "title": "Searches"}]})
        rows = [[day.isoformat(), counts.get((day, "ai"), 0), counts.get((day, "keyword"), 0)]
                for day in days]
        return _chart(spec, ["Day", "AI", "Keyword"], rows, f"n = {len(self.rows)} searches")

    @staticmethod
    def _length_bucket(query):
        words = len(query.split())
        if words <= 2:
            return "1–2 words"
        if words <= 4:
            return "3–4 words"
        if words <= 7:
            return "5–7 words"
        return "8+ words"

    def query_length(self):
        """U3: what inputs shoppers type, and whether longer requests find results."""
        order = ["1–2 words", "3–4 words", "5–7 words", "8+ words"]
        counts = Counter((self._length_bucket(row["query"]), row["result_count"] > 0) for row in self.ai)
        if not counts:
            return None
        series = [("Found results", BLUE), ("No results", ORANGE)]
        values = [{"bucket": bucket, "series": "Found results" if found else "No results", "count": count,
                   "order": 0 if found else 1}
                  for (bucket, found), count in counts.items()]
        spec = _base_spec(data={"values": values},
                          mark={"type": "bar", "stroke": "#fffefa", "strokeWidth": 2},
                          encoding={
                              "x": {"field": "bucket", "type": "ordinal", "sort": order, "title": None,
                                    "axis": {"labelAngle": 0}},
                              "y": {"field": "count", "type": "quantitative", "stack": True,
                                    "title": "AI searches"},
                              "color": _color(series),
                              "order": {"field": "order", "type": "quantitative"},
                              "tooltip": [{"field": "bucket", "title": "Query length"},
                                          {"field": "series", "title": "Result"},
                                          {"field": "count", "title": "Searches"}]})
        rows = []
        for bucket in order:
            found, empty = counts.get((bucket, True), 0), counts.get((bucket, False), 0)
            if found + empty:
                rows.append([bucket, found + empty, f"{empty / (found + empty):.1%}"])
        return _chart(spec, ["Query length", "AI searches", "No-result rate"], rows,
                      "Stacks compare result rates across query lengths")

    def filter_usage(self):
        """U3: which structured filters shoppers combine with a search."""
        counts = Counter(name for row in self.rows for name in row["filters_used"])
        values = [{"filter": FILTER_LABELS.get(name, name),
                   "share": counts.get(name, 0) / len(self.rows), "count": counts.get(name, 0)}
                  for name in FILTER_LABELS]
        spec = _base_spec(height=200, data={"values": values},
                          mark={"type": "bar", "color": BLUE},
                          encoding={
                              "y": {"field": "filter", "type": "nominal", "title": None,
                                    "sort": "-x", "axis": {"grid": False}},
                              "x": {"field": "share", "type": "quantitative", "title": "Share of searches",
                                    "axis": {"format": "%", "grid": True}},
                              "tooltip": [{"field": "filter", "title": "Filter"},
                                          {"field": "count", "title": "Searches"},
                                          {"field": "share", "format": ".1%", "title": "Share"}]})
        rows = [[value["filter"], value["count"], f"{value['share']:.1%}"]
                for value in sorted(values, key=lambda value: -value["count"])]
        none_used = sum(not row["filters_used"] for row in self.rows)
        return _chart(spec, ["Filter", "Searches", "Share"], rows,
                      f"{none_used / len(self.rows):.0%} of searches used no filter")

    def top_queries(self, limit=10):
        """U2: the most common queries and how well they are served."""
        groups = defaultdict(list)
        for row in self.rows:
            groups[" ".join(row["query"].lower().split())].append(row)
        ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))[:limit]
        return [[query, len(items), f"{sum(r['mode'] == 'ai' for r in items) / len(items):.0%}",
                 f"{statistics.mean(r['result_count'] for r in items):.1f}",
                 sum(r["result_count"] == 0 for r in items)]
                for query, items in ranked]

    def zero_result_queries(self, limit=10):
        """U2: queries that found nothing, a signal of missing inventory."""
        counts = Counter(" ".join(row["query"].lower().split())
                         for row in self.rows if row["result_count"] == 0)
        return [[query, count] for query, count in counts.most_common(limit)]

    # ---------------------------------------------------------------- cost
    def cost_by_day(self):
        """C1: what an AI search costs (paid-tier equivalent) and what drives it."""
        by_day = defaultdict(list)
        for row in self.ai:
            by_day[_day(row)].append(search_cost(row))
        if not by_day:
            return None
        series = [("LLM input", BLUE), ("LLM output + reasoning", ORANGE), ("Embedding (estimated)", AQUA)]
        keys = ["llm_input", "llm_output", "embedding"]
        values, rows = [], []
        for day, costs in sorted(by_day.items()):
            means = [statistics.mean(cost[key] for cost in costs) * 1000 for key in keys]
            for index, ((name, _), mean) in enumerate(zip(series, means)):
                values.append({"day": day.isoformat(), "series": name, "usd": round(mean, 5),
                               "order": index})
            rows.append([day.isoformat(), len(costs)] + [f"${mean:.4f}" for mean in means])
        spec = _base_spec(data={"values": values},
                          mark={"type": "bar", "stroke": "#fffefa", "strokeWidth": 1},
                          encoding={
                              "x": {"field": "day", "type": "temporal", "timeUnit": "yearmonthdate",
                                    "title": None, "axis": {"format": "%b %d"}},
                              "y": {"field": "usd", "type": "quantitative", "stack": True,
                                    "title": "USD per 1,000 AI searches"},
                              "color": _color(series),
                              "order": {"field": "order", "type": "quantitative"},
                              "tooltip": [{"field": "day", "type": "temporal", "title": "Day"},
                                          {"field": "series", "title": "Component"},
                                          {"field": "usd", "format": "$.4f", "title": "USD / 1k searches"}]})
        return _chart(spec, ["Day", "AI searches", "LLM input", "LLM output", "Embedding"], rows,
                      "Paid-tier list prices; the free tier bills $0")

    def tokens_vs_candidates(self):
        """C2: whether token use grows with the candidates sent to the LLM."""
        values = [{"candidates": row["retrieved_count"],
                   "tokens": (row["prompt_tokens"] or 0) + (row["completion_tokens"] or 0),
                   "query": row["query"]}
                  for row in self.ai if row["prompt_tokens"] and row["retrieved_count"] is not None]
        if not values:
            return None
        spec = _base_spec(data={"values": values}, layer=[
            {"transform": [{"calculate": "datum.candidates + (random() - 0.5) * 0.4", "as": "jittered"}],
             "mark": {"type": "circle", "size": 64, "color": BLUE, "opacity": 0.4},
             "encoding": {
                 "x": {"field": "jittered", "type": "quantitative", "title": "Candidates sent to the LLM",
                       "scale": {"domain": [0, 9]}, "axis": {"tickMinStep": 1}},
                 "y": {"field": "tokens", "type": "quantitative", "title": "Tokens per search"},
                 "tooltip": [{"field": "query", "title": "Query"},
                             {"field": "candidates", "title": "Candidates"},
                             {"field": "tokens", "title": "Tokens"}]}},
            {"mark": {"type": "line", "color": INK, "strokeWidth": 2,
                      "point": {"size": 64, "filled": True, "color": INK}},
             "encoding": {"x": {"field": "candidates", "type": "quantitative"},
                          "y": {"aggregate": "mean", "field": "tokens", "type": "quantitative"},
                          "tooltip": [{"field": "candidates", "title": "Candidates"},
                                      {"aggregate": "mean", "field": "tokens", "format": ".0f",
                                       "title": "Mean tokens"}]}},
        ])
        by_count = defaultdict(list)
        for value in values:
            by_count[value["candidates"]].append(value["tokens"])
        rows = [[count, len(tokens), round(statistics.mean(tokens))]
                for count, tokens in sorted(by_count.items())]
        return _chart(spec, ["Candidates", "Searches", "Mean tokens"], rows,
                      "Dots are searches (jittered); the line is the mean")

    def token_heavy_queries(self, limit=8):
        """C2 detail: the individual searches that used the most tokens."""
        ranked = sorted((row for row in self.ai if row["prompt_tokens"]),
                        key=lambda row: -((row["prompt_tokens"] or 0) + (row["completion_tokens"] or 0)))
        return [[row["query"], row["retrieved_count"], row["prompt_tokens"], row["completion_tokens"],
                 f"${sum(search_cost(row).values()) * 1000:.4f}"]
                for row in ranked[:limit]]

    def cost_projection(self):
        """C3: monthly cost as traffic grows, against A7's AWS and HF API estimates."""
        costs = [sum(search_cost(row).values()) for row in self.ai]
        if not costs:
            return None
        per_search = statistics.mean(costs)
        values, rows = [], []
        for dau, aws_low, aws_high, hf_low, hf_high in A7_DAILY_COST:
            moveon = per_search * A7_REQUESTS_PER_DAU * dau * 30
            values += [
                {"dau": dau, "series": "MoveOn observed (Groq + Gemini)", "low": moveon, "high": moveon},
                {"dau": dau, "series": "A7 HF API estimate", "low": hf_low * 30, "high": hf_high * 30},
                {"dau": dau, "series": "A7 AWS self-host estimate", "low": aws_low * 30, "high": aws_high * 30},
            ]
            rows.append([f"{dau:,}", f"${moveon:,.2f}", f"${hf_low * 30:,.0f}–${hf_high * 30:,.0f}",
                         f"${aws_low * 30:,.0f}–${aws_high * 30:,.0f}"])
        series = [("MoveOn observed (Groq + Gemini)", BLUE), ("A7 HF API estimate", ORANGE),
                  ("A7 AWS self-host estimate", AQUA)]
        decades = [10 ** power for power in range(-2, 9)]
        legend = {"symbolType": "stroke", "symbolStrokeWidth": 3, "symbolOpacity": 1,
                  "labelLimit": 320, "columns": 1, "title": None}
        x = {"field": "dau", "type": "quantitative", "scale": {"type": "log"}, "title": "Daily active users",
             "axis": {"format": "~s", "values": [dau for dau, *_ in A7_DAILY_COST]}}
        y_scale = {"type": "quantitative", "scale": {"type": "log"},
                   "title": "USD per month (log scale)", "axis": {"format": "$~s", "values": decades}}
        spec = _base_spec(height=260, data={"values": values}, layer=[
            {"mark": {"type": "area", "opacity": 0.15},
             "encoding": {"x": x, "y": {"field": "low", "stack": None, **y_scale},
                          "y2": {"field": "high"}, "color": {**_color(series), "legend": legend}}},
            {"mark": {"type": "line", "point": {"size": 64, "filled": True}},
             "encoding": {"x": x, "y": {"field": "high", **y_scale},
                          "color": {**_color(series), "legend": legend},
                          "tooltip": [{"field": "series", "title": "Estimate"},
                                      {"field": "dau", "format": ",", "title": "DAU"},
                                      {"field": "low", "format": "$,.2f", "title": "Low / month"},
                                      {"field": "high", "format": "$,.2f", "title": "High / month"}]}},
        ])
        return _chart(spec, ["DAU", "MoveOn / month", "A7 HF API / month", "A7 AWS / month"], rows,
                      f"{A7_REQUESTS_PER_DAU} AI searches per user per day, as in A7; bands show A7's model range")


def load_rows(queryset):
    return list(queryset.values(
        "created_at", "mode", "query", "filters_used", "state", "result_count", "candidate_count",
        "retrieved_count", "total_ms", "embedding_ms", "llm_ms", "embedding_model",
        "embedding_texts_sent", "embedding_chars", "embedding_error", "llm_model", "prompt_tokens",
        "completion_tokens", "reasoning_tokens", "llm_error",
    ))


def build_dashboard(queryset, *, range_key="30", source_key="all", now=None):
    """Filter logs by time window and data source, then build every widget."""
    now = now or timezone.now()
    days = RANGES.get(range_key, 30)
    if days is not None:
        queryset = queryset.filter(created_at__gte=now - timedelta(days=days))
    simulated = SOURCES.get(source_key)
    if simulated is not None:
        queryset = queryset.filter(is_simulated=simulated)
    return Report(load_rows(queryset), days=days, now=now).build()
