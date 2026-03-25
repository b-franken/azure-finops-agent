"""Tests for budget tracker tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from src.agents.budget_tracker import get_budget_forecast, get_budget_status


def _make_budget(
    name: str,
    amount: float,
    spent: float,
    days_total: int = 30,
    days_elapsed: int = 15,
) -> MagicMock:
    now = datetime.now(tz=UTC)
    budget = MagicMock()
    budget.name = name
    budget.amount = amount
    budget.current_spend = MagicMock()
    budget.current_spend.amount = spent
    budget.time_grain = "Monthly"
    budget.time_period = MagicMock()
    budget.time_period.start_date = now - timedelta(days=days_elapsed)
    budget.time_period.end_date = now + timedelta(days=days_total - days_elapsed)
    return budget


class TestGetBudgetStatus:
    @patch("azure.mgmt.consumption.ConsumptionManagementClient")
    def test_shows_at_risk_budget(
        self, mock_consumption_cls: MagicMock, mock_azure_clients: MagicMock
    ) -> None:
        budgets = [
            _make_budget("budget-ok", 1000.0, 500.0),
            _make_budget("budget-risk", 1000.0, 900.0),
        ]
        mock_consumption_cls.return_value.budgets.list.return_value = budgets
        result = get_budget_status.func()
        assert "budget-ok" in result
        assert "budget-risk" in result
        assert "AT RISK" in result

    @patch("azure.mgmt.consumption.ConsumptionManagementClient")
    def test_no_budgets(
        self, mock_consumption_cls: MagicMock, mock_azure_clients: MagicMock
    ) -> None:
        mock_consumption_cls.return_value.budgets.list.return_value = []
        result = get_budget_status.func()
        assert "No budgets configured" in result


class TestGetBudgetForecast:
    @patch("azure.mgmt.consumption.ConsumptionManagementClient")
    def test_forecasts_over_budget(
        self, mock_consumption_cls: MagicMock, mock_azure_clients: MagicMock
    ) -> None:
        budget = _make_budget(
            "budget-over", 1000.0, 800.0, days_total=30, days_elapsed=15
        )
        mock_consumption_cls.return_value.budgets.list.return_value = [budget]
        result = get_budget_forecast.func()
        assert "budget-over" in result
        assert "OVER" in result

    @patch("azure.mgmt.consumption.ConsumptionManagementClient")
    def test_no_budgets(
        self, mock_consumption_cls: MagicMock, mock_azure_clients: MagicMock
    ) -> None:
        mock_consumption_cls.return_value.budgets.list.return_value = []
        result = get_budget_forecast.func()
        assert "No budgets configured" in result
