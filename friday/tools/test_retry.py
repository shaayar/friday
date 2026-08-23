"""Tests for retry utilities."""

import pytest

from friday.tools.retry import (
    RetryConfig,
    calculate_delay,
    retry_async,
    retry_sync,
    retryable,
)


class TestRetryConfig:
    def test_default_config(self):
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 30.0
        assert config.exponential_base == 2.0
        assert config.jitter is True
        assert config.retryable_exceptions == (Exception,)

    def test_custom_config(self):
        config = RetryConfig(
            max_attempts=5,
            base_delay=0.5,
            max_delay=10.0,
            exponential_base=3.0,
            jitter=False,
            retryable_exceptions=(ConnectionError, ValueError),
        )
        assert config.max_attempts == 5
        assert config.base_delay == 0.5
        assert config.max_delay == 10.0
        assert config.exponential_base == 3.0
        assert config.jitter is False
        assert config.retryable_exceptions == (ConnectionError, ValueError)


class TestCalculateDelay:
    def test_exponential_backoff_no_jitter(self):
        config = RetryConfig(
            base_delay=1.0, exponential_base=2.0, max_delay=30.0, jitter=False
        )
        assert calculate_delay(config, 0) == 1.0
        assert calculate_delay(config, 1) == 2.0
        assert calculate_delay(config, 2) == 4.0
        assert calculate_delay(config, 3) == 8.0

    def test_max_delay_cap(self):
        config = RetryConfig(
            base_delay=10.0, exponential_base=2.0, max_delay=15.0, jitter=False
        )
        assert calculate_delay(config, 0) == 10.0
        assert calculate_delay(config, 1) == 15.0  # capped at max_delay
        assert calculate_delay(config, 2) == 15.0  # capped at max_delay

    def test_jitter_range(self):
        config = RetryConfig(
            base_delay=10.0, exponential_base=2.0, max_delay=100.0, jitter=True
        )
        # With jitter, delay should be between 0.5x and 1.5x of base
        for _ in range(100):
            delay = calculate_delay(config, 0)
            assert 5.0 <= delay <= 15.0, f"Delay {delay} out of expected range [5, 15]"


class TestRetrySync:
    def test_success_on_first_attempt(self):
        calls = []

        def operation():
            calls.append(1)
            return "success"

        result = retry_sync(
            operation, config=RetryConfig(max_attempts=3, base_delay=0.01)
        )
        assert result == "success"
        assert len(calls) == 1

    def test_success_after_retries(self):
        calls = []

        def operation():
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("fail")
            return "success"

        result = retry_sync(
            operation,
            config=RetryConfig(
                max_attempts=5, base_delay=0.01, retryable_exceptions=(ConnectionError,)
            ),
        )
        assert result == "success"
        assert len(calls) == 3

    def test_failure_after_exhausted_retries(self):
        calls = []

        def operation():
            calls.append(1)
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            retry_sync(
                operation,
                config=RetryConfig(
                    max_attempts=3,
                    base_delay=0.01,
                    retryable_exceptions=(ConnectionError,),
                ),
            )
        assert len(calls) == 3

    def test_non_retryable_exception(self):
        calls = []

        def operation():
            calls.append(1)
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            retry_sync(
                operation,
                config=RetryConfig(
                    max_attempts=3,
                    base_delay=0.01,
                    retryable_exceptions=(ConnectionError,),
                ),
            )
        assert len(calls) == 1  # Should not retry on non-retryable exception

    def test_with_args_and_kwargs(self):
        def operation(a, b, c=10):
            return a + b + c

        result = retry_sync(
            operation, 1, 2, c=3, config=RetryConfig(max_attempts=3, base_delay=0.01)
        )
        assert result == 6


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        calls = []

        async def operation():
            calls.append(1)
            return "success"

        result = await retry_async(
            operation, config=RetryConfig(max_attempts=3, base_delay=0.01)
        )
        assert result == "success"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_success_after_retries(self):
        calls = []

        async def operation():
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("fail")
            return "success"

        result = await retry_async(
            operation,
            config=RetryConfig(
                max_attempts=5, base_delay=0.01, retryable_exceptions=(ConnectionError,)
            ),
        )
        assert result == "success"
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_failure_after_exhausted_retries(self):
        calls = []

        async def operation():
            calls.append(1)
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            await retry_async(
                operation,
                config=RetryConfig(
                    max_attempts=3,
                    base_delay=0.01,
                    retryable_exceptions=(ConnectionError,),
                ),
            )
        assert len(calls) == 3


class TestRetryableDecorator:
    def test_sync_decorator(self):
        calls = []

        @retryable(
            max_attempts=3, base_delay=0.01, retryable_exceptions=(ConnectionError,)
        )
        def operation():
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("fail")
            return "success"

        result = operation()
        assert result == "success"
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_async_decorator(self):
        calls = []

        @retryable(
            max_attempts=3, base_delay=0.01, retryable_exceptions=(ConnectionError,)
        )
        async def operation():
            calls.append(1)
            if len(calls) < 2:
                raise ConnectionError("fail")
            return "success"

        result = await operation()
        assert result == "success"
        assert len(calls) == 2

    def test_sync_decorator_exhausted(self):
        calls = []

        @retryable(
            max_attempts=2, base_delay=0.01, retryable_exceptions=(ConnectionError,)
        )
        def operation():
            calls.append(1)
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            operation()
        assert len(calls) == 2
