"""Staff-only AI search analytics dashboard (A10)."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .ai_analytics import RANGES, SOURCES, build_dashboard
from .models import AISearchLog

# Each widget answers one analytics question; the dashboard is ordered by question.
SECTIONS = [
    ("System performance", [
        {"code": "P1", "chart": "latency",
         "question": "How is AI search time distributed, and how far is the slow tail (p95) from a typical search (p50)?"},
        {"code": "P2", "chart": "stages",
         "question": "Which stage dominates AI search time, and how much does the embedding cache change it?"},
        {"code": "P3", "chart": "outcomes", "table": "errors",
         "table_columns": ["Service", "Error", "Searches", "Share of AI searches"],
         "question": "How often does AI search degrade or fail (rate limits, timeouts), and is it getting worse?"},
    ]),
    ("User behavior", [
        {"code": "U1", "chart": "modes",
         "question": "How often do shoppers choose AI search over keyword search, day by day?"},
        {"code": "U2", "table": "top_queries",
         "table_columns": ["Query", "Searches", "AI share", "Mean results", "No-result searches"],
         "second_table": "zero_result_queries", "second_columns": ["Query with no results", "Searches"],
         "question": "What do shoppers search for most, and which requests find nothing (missing inventory)?"},
        {"code": "U3", "chart": "query_length", "second_chart": "filters",
         "question": "What kinds of input do shoppers give: short keywords or full requests, and with which filters?"},
    ]),
    ("Cost", [
        {"code": "C1", "chart": "cost_daily",
         "question": "What does one AI search cost on a paid plan, and is the LLM or embedding the bigger share?"},
        {"code": "C2", "chart": "tokens", "table": "token_heavy",
         "table_columns": ["Query", "Candidates", "Input tokens", "Output tokens", "USD / 1k such searches"],
         "question": "Which searches use the most tokens, and does usage grow with the candidates sent to the LLM?"},
        {"code": "C3", "chart": "projection",
         "question": "How would monthly cost grow with traffic, compared with A7's AWS and Hugging Face estimates?"},
    ]),
]


def _kpi_tiles(kpis):
    """Headline numbers, each tied to the question it summarizes."""
    def seconds(value):
        return "—" if value is None else f"{value:.2f}s"

    def share(value):
        return "—" if value is None else f"{value:.1%}"

    def dollars(value):
        return "—" if value is None else f"${value:.3f}"

    return [
        {"code": "U1", "label": "Searches", "value": f"{kpis['searches']:,}",
         "detail": f"{share(kpis['ai_share'])} used AI search ({kpis['ai_searches']:,})"},
        {"code": "P1", "label": "AI search time p50 / p95",
         "value": f"{seconds(kpis['p50_s'])} / {seconds(kpis['p95_s'])}",
         "detail": "Server time per AI search"},
        {"code": "P3", "label": "Degraded or failed",
         "value": share(kpis["degraded_rate"]),
         "detail": f"{kpis['degraded']:,} AI searches fell back or were unavailable"},
        {"code": "C1", "label": "Cost per 1,000 AI searches",
         "value": dollars(kpis["cost_per_1k"]),
         "detail": f"Paid-tier equivalent; p95 {dollars(kpis['cost_p95_per_1k'])}; billed $0 (free tier)"},
        {"code": "C3", "label": "Peak Groq tokens per minute",
         "value": f"{kpis['peak_tpm']:,} / {kpis['tpm_limit']:,}",
         "detail": f"Busiest day {kpis['peak_tpd']:,} of {kpis['tpd_limit']:,} free daily tokens"},
    ]


def _sections(report):
    sections = []
    for title, widgets in SECTIONS:
        built = []
        for widget in widgets:
            item = {**widget, "spec_id": f"spec-{widget['code'].lower()}"}
            for key in ("chart", "second_chart"):
                if widget.get(key):
                    item[key] = report["charts"].get(widget[key])
            for key in ("table", "second_table"):
                if widget.get(key):
                    item[key] = report["tables"].get(widget[key], [])
            built.append(item)
        sections.append({"title": title, "widgets": built})
    return sections


@login_required
@require_GET
def ai_search_analytics(request):
    if not request.user.is_staff:
        raise PermissionDenied
    range_key = request.GET.get("range", "30")
    range_key = range_key if range_key in RANGES else "30"
    source_key = request.GET.get("source", "all")
    source_key = source_key if source_key in SOURCES else "all"
    report = build_dashboard(AISearchLog.objects.all(), range_key=range_key, source_key=source_key)
    totals = AISearchLog.objects.aggregate(
        real=Count("pk", filter=Q(is_simulated=False)),
        simulated=Count("pk", filter=Q(is_simulated=True)),
    )
    return render(request, "marketplace/ai_search_analytics.html", {
        "report": report,
        "sections": [] if report["empty"] else _sections(report),
        "kpi_tiles": [] if report["empty"] else _kpi_tiles(report["kpis"]),
        "range_key": range_key,
        "source_key": source_key,
        "range_options": [("7", "Last 7 days"), ("30", "Last 30 days"), ("all", "All time")],
        "source_options": [("all", "All data"), ("real", "Real searches"), ("simulated", "Simulated")],
        "totals": totals,
    })
