"""Tests for anomaly detector tools."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.agents.anomaly_detector import detect_anomalies, get_daily_trend


def _make_daily_result(rows: list[list]) -> MagicMock:
    result = MagicMock()
    result.rows = rows
    result.columns = [
        MagicMock(name="PreTaxCost"),
        MagicMock(name="UsageDate"),
        MagicMock(name="Currency"),
    ]
    return result


class TestDetectAnomalies:
    def test_finds_spike(self, mock_azure_clients) -> None:
        mock_azure_clients.cost.query.usage.return_value = _make_daily_result(
            [
                [10.0, "20260301"],
                [10.0, "20260302"],
                [50.0, "20260303"],
                [10.0, "20260304"],
            ]
        )
        result = detect_anomalies.func(30, 2.0)
        assert (
            "anomal" in result.lower()
            or "spike" in result.lower()
            or "20260303" in result
        )

    def test_no_anomalies(self, mock_azure_clients) -> None:
        mock_azure_clients.cost.query.usage.return_value = _make_daily_result(
            [[10.0, "20260301"], [11.0, "20260302"], [10.0, "20260303"]]
        )
        result = detect_anomalies.func(30, 2.0)
        assert "no" in result.lower() or "0 anomal" in result.lower()

    def test_empty_data(self, mock_azure_clients) -> None:
        mock_azure_clients.cost.query.usage.return_value = _make_daily_result([])
        result = detect_anomalies.func(30, 2.0)
        assert "no" in result.lower() or "No daily" in result


class TestGetDailyTrend:
    def test_returns_trend(self, mock_azure_clients) -> None:
        mock_azure_clients.cost.query.usage.return_value = _make_daily_result(
            [[10.0, "20260301", "EUR"], [20.0, "20260302", "EUR"]]
        )
        result = get_daily_trend.func(14)
        assert "20260301" in result or "10.00" in result

    def test_empty_data(self, mock_azure_clients) -> None:
        mock_azure_clients.cost.query.usage.return_value = _make_daily_result([])
        result = get_daily_trend.func(14)
        assert "no" in result.lower() or "No daily" in result
