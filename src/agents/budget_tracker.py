"""Budget Tracker agent — Azure budget monitoring and forecasting."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langchain_core.tools import tool

from src.agents._context import get_clients
from src.config import config
from src.retry import with_retry

if TYPE_CHECKING:
    from azure.mgmt.consumption.models import Budget

    from src.azure_clients import AzureClients


def _get_all_budgets(clients: AzureClients) -> list[Budget]:
    from azure.mgmt.consumption import ConsumptionManagementClient

    all_budgets: list[Budget] = []
    for sub_id in clients.subscription_ids:
        consumption = ConsumptionManagementClient(clients.credential, sub_id)
        scope = f"/subscriptions/{sub_id}"
        all_budgets.extend(with_retry(consumption.budgets.list, scope))
    return all_budgets


@tool
def get_budget_status() -> str:
    """Get current budget utilization for all budgets in scope."""
    clients = get_clients()
    budgets = _get_all_budgets(clients)

    if not budgets:
        return "No budgets configured for this scope."

    now = datetime.now(tz=UTC)
    lines = [f"Budget Status ({len(budgets)} budgets):\n"]

    for budget in budgets:
        amount = float(budget.amount or 0)
        current = float(budget.current_spend.amount) if budget.current_spend else 0.0
        pct = (current / amount * 100) if amount > 0 else 0.0

        time_grain = getattr(budget, "time_grain", "Monthly")
        end = getattr(budget.time_period, "end_date", now)
        days_left = max(0, (end - now).days) if end else 0

        status = "AT RISK" if pct > config.budget_risk_threshold * 100 else "OK"

        lines.append(
            f"  {budget.name} ({time_grain}):\n"
            f"    Budget:    {amount:>10.2f}\n"
            f"    Spent:     {current:>10.2f} ({pct:.1f}%)\n"
            f"    Remaining: {amount - current:>10.2f}\n"
            f"    Days left: {days_left}\n"
            f"    Status:    {status}"
        )

    at_risk = sum(
        1
        for b in budgets
        if b.current_spend
        and float(b.current_spend.amount or 0) / float(b.amount or 1)
        > config.budget_risk_threshold
    )
    if at_risk:
        lines.append(f"\n{at_risk} budget(s) at risk (>80% consumed).")

    return "\n".join(lines)


@tool
def get_budget_forecast() -> str:
    """Forecast end-of-period spend based on current burn rate."""
    clients = get_clients()
    budgets = _get_all_budgets(clients)

    if not budgets:
        return "No budgets configured for this scope."

    now = datetime.now(tz=UTC)
    lines = ["Budget Forecasts:\n"]

    for budget in budgets:
        amount = float(budget.amount or 0)
        current = float(budget.current_spend.amount) if budget.current_spend else 0.0

        start = getattr(budget.time_period, "start_date", now)
        end = getattr(budget.time_period, "end_date", now)
        elapsed = max(1, (now - start).days)
        total_days = max(1, (end - start).days)
        daily_rate = current / elapsed
        forecast = daily_rate * total_days

        over_under = forecast - amount
        indicator = "OVER" if over_under > 0 else "UNDER"

        lines.append(
            f"  {budget.name}:\n"
            f"    Budget:       {amount:>10.2f}\n"
            f"    Current:      {current:>10.2f} (day {elapsed}/{total_days})\n"
            f"    Daily rate:   {daily_rate:>10.2f}\n"
            f"    Forecast:     {forecast:>10.2f}\n"
            f"    {indicator} budget by: {abs(over_under):>10.2f}"
        )

    return "\n".join(lines)
