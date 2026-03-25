"""Tests for cost analyzer tools."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.agents.cost_analyzer import (
    _aggregate_rows,
    _build_query,
    _format_rows,
    compare_periods,
    export_cost_diff,
    query_costs,
    top_spenders,
)


class TestBuildQuery:
    def test_month_to_date(self) -> None:
        query_def, label = _build_query("MonthToDate", "ResourceGroupName")
        assert query_def.timeframe == "MonthToDate"
        assert label == "ResourceGroupName"

    def test_custom_timeframe(self) -> None:
        query_def, _ = _build_query("Custom", "ServiceName", days=30)
        assert query_def.timeframe == "Custom"
        assert query_def.time_period is not None


class TestFormatRows:
    def test_formats_rows(self) -> None:
        rows = [[100.50, "rg-prod", "EUR"], [50.25, "rg-dev", "EUR"]]
        result = _format_rows(rows, "ResourceGroupName")
        assert "rg-prod" in result
        assert "100.50" in result
        assert "TOTAL" in result

    def test_empty_result(self) -> None:
        result = _format_rows([], "ResourceGroupName")
        assert "No cost data" in result


class TestAggregateRows:
    def test_merges_duplicates(self) -> None:
        rows = [[10.0, "rg-a", "EUR"], [20.0, "rg-a", "EUR"], [5.0, "rg-b", "EUR"]]
        result = _aggregate_rows(rows)
        merged = {str(r[1]): r[0] for r in result}
        assert merged["rg-a"] == 30.0
        assert merged["rg-b"] == 5.0


class TestQueryCosts:
    def test_returns_formatted_costs(self, mock_azure_clients) -> None:
        mock_result = MagicMock()
        mock_result.rows = [[100.0, "rg-prod", "EUR"]]
        mock_result.columns = []
        mock_azure_clients.cost.query.usage.return_value = mock_result
        result = query_costs.func("MonthToDate", "ResourceGroupName")
        assert "rg-prod" in result
        assert "100.00" in result

    def test_handles_empty(self, mock_azure_clients) -> None:
        mock_result = MagicMock()
        mock_result.rows = []
        mock_azure_clients.cost.query.usage.return_value = mock_result
        result = query_costs.func("MonthToDate", "ResourceGroupName")
        assert "No cost data" in result


class TestComparePeriods:
    def test_shows_change(self, mock_azure_clients) -> None:
        current = MagicMock()
        current.rows = [[100.0, "rg-a", "EUR"]]
        previous = MagicMock()
        previous.rows = [[80.0, "rg-a", "EUR"]]
        mock_azure_clients.cost.query.usage.side_effect = [previous, current]
        result = compare_periods.func(30)
        assert "100.00" in result
        assert "80.00" in result


class TestTopSpenders:
    def test_returns_top_resources(self, mock_azure_clients) -> None:
        mock_result = MagicMock()
        mock_result.rows = [
            [500.0, "/sub/rg/providers/res/expensive", "EUR"],
            [100.0, "/sub/rg/providers/res/cheap", "EUR"],
        ]
        mock_azure_clients.cost.query.usage.return_value = mock_result
        result = top_spenders.func(5)
        assert "expensive" in result
        assert "500.00" in result


class TestExportCostDiff:
    def test_returns_table(self, mock_azure_clients) -> None:
        previous = MagicMock()
        previous.rows = [[80.0, "rg-a", "EUR"]]
        current = MagicMock()
        current.rows = [[100.0, "rg-a", "EUR"]]
        mock_azure_clients.cost.query.usage.side_effect = [previous, current]
        result = export_cost_diff.func(30, "ResourceGroupName")
        assert "rg-a" in result
        assert "TOTAL" in result
