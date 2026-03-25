"""Tests for the shared retry utility."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.retry import with_retry


class TestWithRetry:
    def test_returns_on_first_success(self) -> None:
        fn = MagicMock(return_value="ok")
        result = with_retry(fn, "a", key="b")
        assert result == "ok"
        fn.assert_called_once_with("a", key="b")

    @patch("src.retry.time.sleep")
    def test_retries_on_429_then_succeeds(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(
            side_effect=[Exception("HTTP 429 Too Many Requests"), "ok"],
        )
        result = with_retry(fn)
        assert result == "ok"
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(2.0)

    @patch("src.retry.time.sleep")
    def test_raises_after_retries_exhausted(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(
            side_effect=Exception("HTTP 429 Too Many Requests"),
        )
        with pytest.raises(Exception, match="429"):
            with_retry(fn)
        assert fn.call_count == 3
        assert mock_sleep.call_count == 2

    def test_raises_non_429_immediately(self) -> None:
        fn = MagicMock(side_effect=ValueError("bad input"))
        with pytest.raises(ValueError, match="bad input"):
            with_retry(fn)
        fn.assert_called_once()

    @patch("src.retry.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(
            side_effect=[
                Exception("429"),
                Exception("429"),
                "ok",
            ],
        )
        result = with_retry(fn)
        assert result == "ok"
        assert mock_sleep.call_args_list[0].args == (2.0,)
        assert mock_sleep.call_args_list[1].args == (4.0,)
