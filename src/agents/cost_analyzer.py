"""Cost Analyzer agent — queries Azure Cost Management for spend data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from azure.mgmt.costmanagement.models import (
    QueryAggregation,
    QueryDataset,
    QueryDefinition,
    QueryGrouping,
    QueryTimePeriod,
)
from langchain_core.tools import tool
from pydantic import Field

from src.agents._context import get_clients
from src.retry import with_retry

CostRow = list[float | str | int]

if TYPE_CHECKING:
    from src.azure_clients import AzureClients


def _query_with_retry(
    clients: AzureClients,
    scope: str,
    query_def: QueryDefinition,
) -> list[CostRow]:
    result = with_retry(clients.cost.query.usage, scope=scope, parameters=query_def)
    return result.rows if result and result.rows else []


def _query_all_scopes(
    clients: AzureClients,
    query_def: QueryDefinition,
) -> list[CostRow]:
    all_rows: list[CostRow] = []
    for scope in clients.cost_scopes:
        all_rows.extend(_query_with_retry(clients, scope, query_def))
    return all_rows


def _aggregate_rows(rows: list[CostRow]) -> list[CostRow]:
    merged: dict[str, CostRow] = {}
    for row in rows:
        cost, key = float(row[0]), str(row[1])
        currency = row[2] if len(row) > 2 else ""
        if key in merged:
            merged[key] = [float(merged[key][0]) + cost, *merged[key][1:]]
        else:
            merged[key] = [cost, key, currency]
    return list(merged.values())


def _build_query(
    timeframe: str,
    group_by: str,
    days: int | None = None,
) -> tuple[QueryDefinition, str]:
    """Build a Cost Management query definition."""
    valid = {"ResourceGroupName", "ServiceName", "ResourceId", "SubscriptionId"}
    if group_by not in valid:
        options = ", ".join(sorted(valid))
        msg = f"Invalid group_by '{group_by}'. Must be one of: {options}"
        raise ValueError(msg)

    aggregation = {
        "totalCost": QueryAggregation(
            name="PreTaxCost",
            function="Sum",
        ),
    }
    grouping = [QueryGrouping(type="Dimension", name=group_by)]

    time_period = None
    if timeframe == "Custom" and days:
        end = datetime.now(tz=UTC)
        start = end - timedelta(days=days)
        time_period = QueryTimePeriod(
            from_property=start,
            to=end,
        )

    query_def = QueryDefinition(
        type="ActualCost",
        timeframe=timeframe,
        time_period=time_period,
        dataset=QueryDataset(
            granularity="None",
            aggregation=aggregation,
            grouping=grouping,
        ),
    )
    return query_def, group_by


def _format_rows(rows: list[CostRow], group_label: str) -> str:
    if not rows:
        return "No cost data found for this period."

    lines: list[str] = [f"{'Name':<40} {'Cost':>12} {'Currency':>8}"]
    lines.append("-" * 62)

    total = 0.0
    for row in rows:
        cost, name = float(row[0]), str(row[1])
        currency = str(row[2]) if len(row) > 2 and row[2] else "USD"
        total += cost
        lines.append(f"{name:<40} {cost:>12.2f} {currency:>8}")

    lines.append("-" * 62)
    lines.append(f"{'TOTAL':<40} {total:>12.2f}")
    return "\n".join(lines)


@tool
def query_costs(
    timeframe: Annotated[
        str,
        Field(
            description=(
                "Time range: MonthToDate, TheLastMonth, "
                "BillingMonthToDate, or TheLastBillingMonth"
            ),
        ),
    ] = "MonthToDate",
    group_by: Annotated[
        str,
        Field(
            description=(
                "Group costs by: ResourceGroupName, ServiceName, or ResourceId"
            ),
        ),
    ] = "ResourceGroupName",
) -> str:
    """Query Azure costs grouped by a dimension."""
    clients = get_clients()
    query_def, label = _build_query(timeframe, group_by)
    rows = _aggregate_rows(_query_all_scopes(clients, query_def))
    if not rows:
        return "No cost data returned."
    rows.sort(key=lambda r: -float(r[0]))
    return _format_rows(rows, label)


def _format_change(current: float, previous: float) -> str:
    if previous > 0:
        delta_pct = ((current - previous) / previous) * 100
        arrow = "\u2191" if delta_pct > 0 else "\u2193"
        direction = "up" if delta_pct > 0 else "down"
    elif current > 0:
        return "\u2191 new spend"
    else:
        delta_pct = 0.0
        arrow = "\u2192"
        direction = "flat"
    return f"{arrow} {abs(delta_pct):.1f}% {direction}"


@tool
def compare_periods(
    days: Annotated[
        int,
        Field(description="Period length in days to compare"),
    ] = 30,
) -> str:
    """Compare current period costs with the previous period."""
    clients = get_clients()

    previous_query, current_query = _build_period_queries(days, "ResourceGroupName")
    current_total = sum(float(r[0]) for r in _query_all_scopes(clients, current_query))
    previous_total = sum(
        float(r[0]) for r in _query_all_scopes(clients, previous_query)
    )

    return (
        f"Period comparison ({days} days):\n"
        f"  Current:  {current_total:>10.2f}\n"
        f"  Previous: {previous_total:>10.2f}\n"
        f"  Change:   {_format_change(current_total, previous_total)}"
    )


@tool
def top_spenders(
    count: Annotated[
        int,
        Field(description="Number of top resources to return"),
    ] = 10,
) -> str:
    """Find the most expensive resources this month."""
    clients = get_clients()
    query_def, _ = _build_query("MonthToDate", "ResourceId")
    rows = _aggregate_rows(_query_all_scopes(clients, query_def))
    if not rows:
        return "No cost data found."

    sorted_rows = sorted(
        rows,
        key=lambda r: float(r[0]),
        reverse=True,
    )[:count]

    lines = [f"Top {count} most expensive resources (month to date):\n"]
    for i, row in enumerate(sorted_rows, 1):
        cost = float(row[0])
        resource_id = str(row[1]).split("/")[-1] or str(row[1])
        lines.append(f"  {i}. {resource_id}: {cost:.2f}")

    total = sum(float(r[0]) for r in rows)
    lines.append(f"\nTotal subscription spend: {total:.2f}")
    return "\n".join(lines)


def _build_period_queries(
    days: int,
    group_by: str,
) -> tuple[QueryDefinition, QueryDefinition]:
    now = datetime.now(tz=UTC)
    current_start = now - timedelta(days=days)
    previous_start = current_start - timedelta(days=days)

    dataset = QueryDataset(
        granularity="None",
        aggregation={
            "totalCost": QueryAggregation(name="PreTaxCost", function="Sum"),
        },
        grouping=[QueryGrouping(type="Dimension", name=group_by)],
    )

    current = QueryDefinition(
        type="ActualCost",
        timeframe="Custom",
        time_period=QueryTimePeriod(from_property=current_start, to=now),
        dataset=dataset,
    )
    previous = QueryDefinition(
        type="ActualCost",
        timeframe="Custom",
        time_period=QueryTimePeriod(from_property=previous_start, to=current_start),
        dataset=dataset,
    )
    return previous, current


def _rows_to_dict(rows: list[CostRow]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows:
        cost, key = float(row[0]), str(row[1])
        result[key] = result.get(key, 0.0) + cost
    return result


def _build_diff_data(
    clients: AzureClients, days: int, group_by: str
) -> tuple[dict[str, float], dict[str, float]]:
    previous_query, current_query = _build_period_queries(days, group_by)
    previous = _rows_to_dict(_query_all_scopes(clients, previous_query))
    current = _rows_to_dict(_query_all_scopes(clients, current_query))
    return previous, current


def _format_diff_table(
    previous: dict[str, float],
    current: dict[str, float],
    days: int,
    label: str,
) -> str:
    all_keys = sorted(set(previous) | set(current))
    if not all_keys:
        return "No cost data available for the selected period."

    header = f"| {label} | Previous {days}d | Current {days}d | Difference | Change % |"
    separator = "|---|---|---|---|---|"
    rows = [header, separator]

    prev_total = 0.0
    curr_total = 0.0
    for key in all_keys:
        prev, curr = previous.get(key, 0.0), current.get(key, 0.0)
        diff = curr - prev
        pct = (diff / prev * 100) if prev > 0 else 0.0
        display_key = key.split("/")[-1] if "/" in key else key
        rows.append(
            f"| {display_key} | {prev:.2f} | {curr:.2f} | {diff:+.2f} | {pct:+.1f}% |"
        )
        prev_total += prev
        curr_total += curr

    total_diff = curr_total - prev_total
    total_pct = (total_diff / prev_total * 100) if prev_total > 0 else 0.0
    rows.append(
        f"| **TOTAL** | **{prev_total:.2f}** | **{curr_total:.2f}** "
        f"| **{total_diff:+.2f}** | **{total_pct:+.1f}%** |"
    )
    return "\n".join(rows)


@tool
def export_cost_diff(
    days: Annotated[
        int,
        Field(description="Period length in days to compare"),
    ] = 30,
    group_by: Annotated[
        str,
        Field(
            description="Group by: ResourceGroupName, SubscriptionId, or ServiceName",
        ),
    ] = "ResourceGroupName",
) -> str:
    """Export cost comparison as a markdown table."""
    clients = get_clients()
    previous, current = _build_diff_data(clients, days, group_by)
    label = group_by.replace("Name", "").replace("Id", "")
    return _format_diff_table(previous, current, days, label)
