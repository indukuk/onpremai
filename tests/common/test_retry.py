"""Tests for common.retry decorator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from common.retry import retry


class TestRetryDecorator:
    """Tests for the async retry decorator with exponential backoff."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Function succeeds immediately, no retry needed."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_on_second_attempt(self):
        """Function fails once then succeeds on second attempt."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, exceptions=(ValueError,))
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("transient")
            return "recovered"

        result = await fail_then_succeed()
        assert result == "recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_max_attempts_exhausted(self):
        """All attempts fail; the last exception is re-raised."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, exceptions=(RuntimeError,))
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"attempt {call_count}")

        with pytest.raises(RuntimeError, match="attempt 3"):
            await always_fail()
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_matching_exception_propagates_immediately(self):
        """Exceptions not in the filter list propagate without retry."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, exceptions=(ValueError,))
        async def wrong_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retryable")

        with pytest.raises(TypeError, match="not retryable"):
            await wrong_error()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        """Verify delays grow exponentially between retries."""
        delays_observed: list[float] = []

        @retry(max_attempts=4, base_delay=0.1, jitter=False, exceptions=(IOError,))
        async def fail_and_track():
            raise IOError("fail")

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(IOError):
                await fail_and_track()

            # 3 retries => 3 sleeps
            assert mock_sleep.call_count == 3
            calls = [c.args[0] for c in mock_sleep.call_args_list]
            # base_delay * 2^attempt: 0.1, 0.2, 0.4
            assert abs(calls[0] - 0.1) < 0.001
            assert abs(calls[1] - 0.2) < 0.001
            assert abs(calls[2] - 0.4) < 0.001

    @pytest.mark.asyncio
    async def test_max_delay_cap(self):
        """Delay never exceeds max_delay."""

        @retry(
            max_attempts=5,
            base_delay=10.0,
            max_delay=15.0,
            jitter=False,
            exceptions=(IOError,),
        )
        async def fail():
            raise IOError("fail")

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(IOError):
                await fail()

            for call in mock_sleep.call_args_list:
                assert call.args[0] <= 15.0

    @pytest.mark.asyncio
    async def test_jitter_adds_randomness(self):
        """With jitter enabled, delays include randomness between 0.5x and 1.5x."""

        @retry(max_attempts=3, base_delay=1.0, jitter=True, exceptions=(IOError,))
        async def fail():
            raise IOError("fail")

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch("random.random", return_value=0.5):
                with pytest.raises(IOError):
                    await fail()

                # With random()=0.5, jitter multiplier = 0.5 + 0.5 = 1.0
                # First delay: 1.0 * 2^0 * 1.0 = 1.0
                calls = [c.args[0] for c in mock_sleep.call_args_list]
                assert abs(calls[0] - 1.0) < 0.001

    @pytest.mark.asyncio
    async def test_single_attempt_no_retry(self):
        """With max_attempts=1, exception propagates immediately (no retry)."""

        @retry(max_attempts=1, base_delay=0.01, exceptions=(ValueError,))
        async def fail_once():
            raise ValueError("one shot")

        with pytest.raises(ValueError, match="one shot"):
            await fail_once()

    @pytest.mark.asyncio
    async def test_preserves_function_metadata(self):
        """The decorator preserves __name__ and __doc__ via functools.wraps."""

        @retry(max_attempts=2, base_delay=0.01)
        async def my_function():
            """My docstring."""
            return True

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    @pytest.mark.asyncio
    async def test_multiple_exception_types(self):
        """Retry works for multiple exception types in the tuple."""
        call_count = 0

        @retry(max_attempts=4, base_delay=0.01, exceptions=(ValueError, IOError))
        async def alternate_errors():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first")
            if call_count == 2:
                raise IOError("second")
            return "done"

        result = await alternate_errors()
        assert result == "done"
        assert call_count == 3
