"""Reporter agent — generates cost optimization reports with savings."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from langchain_core.tools import tool

from src.agents._context import get_clients

logger = logging.getLogger(__name__)

_TOTAL_COST_PATTERN = re.compile(
    r"Total (?:idle|orphaned) resource cost: ~\$(\d+\.?\d*)/mo"
)
_PER_ITEM_COST_PATTERN = re.compile(r"~\$(\d+\.?\d*)/mo")


def _extract_savings(text: str) -> float:
    totals = _TOTAL_COST_PATTERN.findall(text)
    if totals:
        return sum(float(m) for m in totals)
    per_item = _PER_ITEM_COST_PATTERN.findall(text)
    return sum(float(m) for m in per_item)


def _count_findings(text: str) -> int:
    return text.count("\n  - ")


@tool
def generate_report() -> str:
    """Generate a full cost optimization report with savings potential."""
    clients = get_clients()

    from src.agents.advisor import get_prioritized_recommendations
    from src.agents.cost_analyzer import compare_periods, query_costs
    from src.agents.waste_detector import (
        find_idle_resources,
        find_orphaned_resources,
        find_oversized_resources,
    )

    sections_data: dict[str, str] = {}
    calls = [
        (
            "costs",
            query_costs,
            {"timeframe": "MonthToDate", "group_by": "ResourceGroupName"},
        ),
        ("trend", compare_periods, {"days": 30}),
        ("idle", find_idle_resources, {}),
        ("orphaned", find_orphaned_resources, {}),
        ("oversized", find_oversized_resources, {}),
        ("recommendations", get_prioritized_recommendations, {}),
    ]
    for label, tool_fn, args in calls:
        try:
            sections_data[label] = tool_fn.invoke(args)
        except Exception:
            logger.exception("Failed to fetch %s", label)
            sections_data[label] = f"Error fetching {label}."

    costs = sections_data["costs"]
    trend = sections_data["trend"]
    idle = sections_data["idle"]
    orphaned = sections_data["orphaned"]
    oversized = sections_data["oversized"]
    recommendations = sections_data["recommendations"]

    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    idle_savings = _extract_savings(idle)
    orphaned_savings = _extract_savings(orphaned)
    total_savings = idle_savings + orphaned_savings

    sections = [
        "# Cost Optimization Report",
        f"**Subscription:** {', '.join(clients.subscription_ids)}",
        f"**Generated:** {now}",
        f"**Total savings potential: ~${total_savings:.2f}/mo**"
        if total_savings > 0
        else "",
        "",
        "## 1. Spend Overview",
        costs,
        "",
        "## 2. Trend (30 days)",
        trend,
        "",
        "## 3. Idle Resources",
        idle,
        "",
        "## 4. Orphaned Resources",
        orphaned,
        "",
        "## 5. Oversized Resources",
        oversized,
        "",
        "## 6. Advisor Recommendations",
        recommendations,
        "",
        "## 7. Action Plan",
        _build_action_plan(
            idle,
            orphaned,
            oversized,
            recommendations,
            idle_savings,
            orphaned_savings,
        ),
    ]
    return "\n".join(sections)


def _build_action_plan(
    idle: str,
    orphaned: str,
    oversized: str,
    recommendations: str,
    idle_savings: float,
    orphaned_savings: float,
) -> str:
    actions: list[tuple[float, str, str, str]] = []

    idle_count = _count_findings(idle)
    if idle_count:
        actions.append(
            (
                idle_savings,
                "High",
                f"Review {idle_count} idle resources",
                "Stop or deallocate",
            )
        )

    orphaned_count = _count_findings(orphaned)
    if orphaned_count:
        actions.append(
            (
                orphaned_savings,
                "High",
                f"Delete {orphaned_count} orphaned resources",
                "Safe to delete",
            )
        )

    oversized_count = _count_findings(oversized)
    if oversized_count:
        actions.append(
            (
                0.0,
                "Medium",
                f"Downsize {oversized_count} oversized resources",
                "Review workload before changing",
            )
        )

    if "high-impact" in recommendations.lower():
        actions.append(
            (
                0.0,
                "High",
                "Implement Advisor recommendations",
                "See section 6",
            )
        )

    if not actions:
        return "No immediate actions required."

    actions.sort(key=lambda a: -a[0])

    total = sum(a[0] for a in actions)
    lines = [
        "| Priority | Action | Savings | Next step |",
        "|----------|--------|---------|-----------|",
    ]
    for savings, priority, action, step in actions:
        savings_str = f"~${savings:.2f}/mo" if savings > 0 else "-"
        lines.append(f"| {priority} | {action} | {savings_str} | {step} |")

    lines.append(
        f"\n**{len(actions)} actions, ~${total:.2f}/mo total savings potential.**"
    )
    return "\n".join(lines)
