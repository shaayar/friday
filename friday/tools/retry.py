"""
Retry utilities — generic retry logic with exponential backoff for resilient operations.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions


def calculate_delay(config: RetryConfig, attempt: int) -> float:
    """Calculate delay for the given attempt number (0-indexed)."""
    delay = min(
        config.base_delay * (config.exponential_base**attempt),
        config.max_delay,
    )
    if config.jitter:
        delay *= 0.5 + random.random()  # 0.5x to 1.5x
    return delay


async def retry_async(
    func: Callable[..., Awaitable[T]],
    *args,
    config: RetryConfig | None = None,
    **kwargs,
) -> T:
    """
    Execute an async function with retry logic.

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        config: RetryConfig instance (uses defaults if None)
        **kwargs: Keyword arguments for func

    Returns:
        Result of successful func call

    Raises:
        Last exception if all retries exhausted
    """
    config = config or RetryConfig()
    last_exception: Exception | None = None

    for attempt in range(config.max_attempts):
        try:
            return await func(*args, **kwargs)
        except config.retryable_exceptions as exc:
            last_exception = exc
            if attempt < config.max_attempts - 1:
                delay = calculate_delay(config, attempt)
                logger.warning(
                    "Attempt %d/%d failed for %s: %s. Retrying in %.2fs...",
                    attempt + 1,
                    config.max_attempts,
                    func.__name__,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.exception(
                    "All %d attempts failed for %s. Last error: %s",
                    config.max_attempts,
                    func.__name__,
                    last_exception,
                )

    if last_exception is not None:
        raise last_exception
    raise RuntimeError("retry_async exhausted without exception")


def retry_sync(
    func: Callable[..., T],
    *args,
    config: RetryConfig | None = None,
    **kwargs,
) -> T:
    """
    Execute a sync function with retry logic.

    Args:
        func: Sync function to execute
        *args: Positional arguments for func
        config: RetryConfig instance (uses defaults if None)
        **kwargs: Keyword arguments for func

    Returns:
        Result of successful func call

    Raises:
        Last exception if all retries exhausted
    """
    config = config or RetryConfig()
    last_exception: Exception | None = None

    for attempt in range(config.max_attempts):
        try:
            return func(*args, **kwargs)
        except config.retryable_exceptions as exc:
            last_exception = exc
            if attempt < config.max_attempts - 1:
                delay = calculate_delay(config, attempt)
                logger.warning(
                    "Attempt %d/%d failed for %s: %s. Retrying in %.2fs...",
                    attempt + 1,
                    config.max_attempts,
                    func.__name__,
                    exc,
                    delay,
                )
                time.sleep(delay)
            else:
                logger.exception(
                    "All %d attempts failed for %s. Last error: %s",
                    config.max_attempts,
                    func.__name__,
                    last_exception,
                )

    if last_exception is not None:
        raise last_exception
    raise RuntimeError("retry_sync exhausted without exception")


def retryable(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
):
    """
    Decorator to add retry logic to a function.

    Args:
        max_attempts: Maximum number of attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        jitter: Whether to add random jitter
        retryable_exceptions: Exception types to retry on

    Usage:
        @retryable(max_attempts=3, base_delay=1.0)
        async def unreliable_operation():
            ...
    """
    config = RetryConfig(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func: Callable[..., T]) -> Callable[..., T | Awaitable[T]]:
        if asyncio.iscoroutinefunction(func):

            async def async_wrapper(*args, **kwargs) -> T:
                return await retry_async(func, *args, config=config, **kwargs)

            return async_wrapper
        else:

            def sync_wrapper(*args, **kwargs) -> T:
                return retry_sync(func, *args, config=config, **kwargs)

            return sync_wrapper

    return decorator


__all__ = [
    "RetryConfig",
    "calculate_delay",
    "register",
    "retry_async",
    "retry_sync",
    "retryable",
]


def register(mcp):
    """Register retry utilities as MCP tools (exposes retry config for debugging)."""

    @mcp.tool()
    def get_retry_config() -> dict:
        """Get the default retry configuration."""
        config = RetryConfig()
        return {
            "max_attempts": config.max_attempts,
            "base_delay": config.base_delay,
            "max_delay": config.max_delay,
            "exponential_base": config.exponential_base,
            "jitter": config.jitter,
        }

    @mcp.tool()
    def test_retry_sync(should_fail: int = 2, max_attempts: int = 3) -> dict:
        """
        Test the synchronous retry mechanism.

        Args:
            should_fail: Number of times to fail before succeeding (default: 2)
            max_attempts: Maximum retry attempts (default: 3)
        """
        attempt_count = {"count": 0}

        def flaky_operation():
            attempt_count["count"] += 1
            if attempt_count["count"] <= should_fail:
                raise ConnectionError(f"Simulated failure #{attempt_count['count']}")
            return f"Success on attempt {attempt_count['count']}"

        config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=0.01,
            retryable_exceptions=(ConnectionError,),
        )
        try:
            result = retry_sync(flaky_operation, config=config)
            return {
                "success": True,
                "result": result,
                "attempts": attempt_count["count"],
            }
        except ConnectionError as e:
            return {
                "success": False,
                "error": str(e),
                "attempts": attempt_count["count"],
            }

    @mcp.tool()
    async def test_retry_async(should_fail: int = 2, max_attempts: int = 3) -> dict:
        """
        Test the asynchronous retry mechanism.

        Args:
            should_fail: Number of times to fail before succeeding (default: 2)
            max_attempts: Maximum retry attempts (default: 3)
        """
        attempt_count = {"count": 0}

        async def flaky_async_operation():
            attempt_count["count"] += 1
            if attempt_count["count"] <= should_fail:
                raise ConnectionError(f"Simulated failure #{attempt_count['count']}")
            return f"Success on attempt {attempt_count['count']}"

        config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=0.01,
            retryable_exceptions=(ConnectionError,),
        )
        try:
            result = await retry_async(flaky_async_operation, config=config)
            return {
                "success": True,
                "result": result,
                "attempts": attempt_count["count"],
            }
        except ConnectionError as e:
            return {
                "success": False,
                "error": str(e),
                "attempts": attempt_count["count"],
            }
