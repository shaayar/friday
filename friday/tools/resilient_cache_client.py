"""
Resilient Cache Client — demonstrates a practical feature with retry logic.

This module implements a cache client that automatically retries failed operations
with exponential backoff, handles different error types appropriately,
and provides configurable retry policies for different operations.
"""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from friday.tools.retry import RetryConfig, retry_async, retryable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class CacheOperationType(Enum):
    """Types of cache operations."""

    GET = "get"
    SET = "set"
    DELETE = "delete"
    EXISTS = "exists"
    INCREMENT = "increment"


@dataclass
class CacheConfig:
    """Configuration for a cache backend."""

    host: str
    port: int
    password: str | None = None
    db: int = 0
    max_connections: int = 10
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0


@dataclass
class CacheResult:
    """Result of a cache operation."""

    success: bool
    operation: CacheOperationType
    key: str
    value: Any | None = None
    error: str | None = None
    attempts: int = 0


class ResilientCacheClient:
    """
    A resilient cache client that automatically retries failed operations
    with exponential backoff and jitter.

    This demonstrates using the retry utilities for:
    - Basic cache operations (get, set, delete) with retry
    - Connection management with retry
    - Bulk operations with individual retry policies
    - Circuit breaker pattern integration
    """

    def __init__(self, config: CacheConfig, max_attempts: int = 3, base_delay: float = 0.5):
        self.config = config
        self._connected = False
        self._connection_attempts = 0
        self._operation_attempts: dict[str, int] = {}

        # Default retry configuration for cache operations
        self.default_config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=10.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(ConnectionError, TimeoutError, IOError, OSError),
        )

        # Aggressive retry for critical operations
        self.critical_config = RetryConfig(
            max_attempts=5,
            base_delay=0.2,
            max_delay=5.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(ConnectionError, TimeoutError, IOError, OSError),
        )

        # Fast fail for non-critical operations
        self.fast_fail_config = RetryConfig(
            max_attempts=2,
            base_delay=0.1,
            max_delay=1.0,
            exponential_base=2.0,
            jitter=False,
            retryable_exceptions=(ConnectionError, TimeoutError),
        )

    @retryable(max_attempts=4, base_delay=0.5, retryable_exceptions=(ConnectionError, TimeoutError))
    async def connect(self) -> CacheResult:
        """
        Connect to cache backend with automatic retry on transient failures.

        Simulates transient failures on first 2 attempts for demonstration.
        """
        await asyncio.sleep(0.1)  # Simulate connection delay

        self._connection_attempts += 1

        # Simulate transient failures (fail first 2 attempts)
        if self._connection_attempts <= 2:
            raise ConnectionError(
                f"Failed to connect to {self.config.host}:{self.config.port} "
                f"(attempt {self._connection_attempts})"
            )

        self._connected = True
        logger.info(f"Successfully connected to cache at {self.config.host}:{self.config.port}")

        return CacheResult(
            success=True,
            operation=CacheOperationType.GET,  # Using GET as a generic success indicator
            key="__connection__",
            attempts=self._connection_attempts,
        )

    @retryable(
        max_attempts=3,
        base_delay=0.3,
        retryable_exceptions=(ConnectionError, TimeoutError, IOError),
    )
    async def get(self, key: str) -> CacheResult:
        """
        Get a value from cache with automatic retry on transient failures.
        """
        if not self._connected:
            raise ConnectionError("Not connected to cache backend")

        await asyncio.sleep(0.02)  # Simulate network delay

        cache_key = f"get:{key}"
        self._operation_attempts[cache_key] = self._operation_attempts.get(cache_key, 0) + 1
        attempt = self._operation_attempts[cache_key]

        # Simulate transient failures (fail first attempt)
        if attempt <= 1:
            raise TimeoutError(f"Cache GET timeout for key '{key}' (attempt {attempt})")

        # Simulate cache miss on specific keys
        if key.startswith("missing:"):
            return CacheResult(
                success=True,
                operation=CacheOperationType.GET,
                key=key,
                value=None,  # Cache miss
                attempts=attempt,
            )

        # Success - return cached value
        return CacheResult(
            success=True,
            operation=CacheOperationType.GET,
            key=key,
            value=f"cached_value_for_{key}",
            attempts=attempt,
        )

    @retryable(
        max_attempts=3,
        base_delay=0.3,
        retryable_exceptions=(ConnectionError, TimeoutError, IOError),
    )
    async def set(self, key: str, value: Any, ttl: int | None = None) -> CacheResult:
        """
        Set a value in cache with automatic retry on transient failures.
        """
        if not self._connected:
            raise ConnectionError("Not connected to cache backend")

        await asyncio.sleep(0.02)  # Simulate network delay

        cache_key = f"set:{key}"
        self._operation_attempts[cache_key] = self._operation_attempts.get(cache_key, 0) + 1
        attempt = self._operation_attempts[cache_key]

        # Simulate transient failures (fail first attempt)
        if attempt <= 1:
            raise OSError(f"Cache SET failed for key '{key}' (attempt {attempt})")

        logger.info(f"Successfully set key '{key}' with TTL={ttl}")

        return CacheResult(
            success=True,
            operation=CacheOperationType.SET,
            key=key,
            value=value,
            attempts=attempt,
        )

    @retryable(
        max_attempts=3,
        base_delay=0.2,
        retryable_exceptions=(ConnectionError, TimeoutError, IOError),
    )
    async def delete(self, key: str) -> CacheResult:
        """
        Delete a key from cache with automatic retry on transient failures.
        """
        if not self._connected:
            raise ConnectionError("Not connected to cache backend")

        await asyncio.sleep(0.02)

        cache_key = f"delete:{key}"
        self._operation_attempts[cache_key] = self._operation_attempts.get(cache_key, 0) + 1
        attempt = self._operation_attempts[cache_key]

        # Simulate transient failure on first attempt
        if attempt <= 1:
            raise ConnectionError(f"Cache DELETE failed for key '{key}' (attempt {attempt})")

        return CacheResult(
            success=True,
            operation=CacheOperationType.DELETE,
            key=key,
            attempts=attempt,
        )

    async def get_with_explicit_retry(
        self, key: str, config: RetryConfig | None = None
    ) -> CacheResult:
        """
        Get a value using explicit retry_async for more control.

        This demonstrates the explicit retry pattern vs decorator pattern.
        """
        if not self._connected:
            raise ConnectionError("Not connected to cache backend")

        async def _do_get() -> CacheResult:
            await asyncio.sleep(0.02)

            cache_key = f"explicit_get:{key}"
            self._operation_attempts[cache_key] = self._operation_attempts.get(cache_key, 0) + 1
            attempt = self._operation_attempts[cache_key]

            if attempt <= 1:
                raise TimeoutError(f"Explicit GET timeout for '{key}' (attempt {attempt})")

            return CacheResult(
                success=True,
                operation=CacheOperationType.GET,
                key=key,
                value=f"explicit_value_for_{key}",
                attempts=attempt,
            )

        return await retry_async(_do_get, config=config or self.default_config)

    async def mget(self, keys: list[str]) -> list[CacheResult]:
        """
        Get multiple keys concurrently with individual retry logic.

        Uses asyncio.gather with return_exceptions=True to handle partial failures.
        """

        async def _get_one(key: str) -> CacheResult:
            return await self.get(key)

        tasks = [_get_one(key) for key in keys]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(
                    CacheResult(
                        success=False,
                        operation=CacheOperationType.GET,
                        key=keys[i],
                        error=str(result),
                        attempts=self.default_config.max_attempts,
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    async def mset(self, mapping: dict[str, Any], ttl: int | None = None) -> list[CacheResult]:
        """
        Set multiple keys concurrently with individual retry logic.
        """

        async def _set_one(key: str, value: Any) -> CacheResult:
            return await self.set(key, value, ttl)

        tasks = [_set_one(key, value) for key, value in mapping.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, (key, value) in enumerate(mapping.items()):
            result = results[i]
            if isinstance(result, Exception):
                processed_results.append(
                    CacheResult(
                        success=False,
                        operation=CacheOperationType.SET,
                        key=key,
                        error=str(result),
                        attempts=self.default_config.max_attempts,
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    async def increment_with_retry(self, key: str, amount: int = 1) -> CacheResult:
        """
        Increment a numeric value in cache with retry logic for critical operations.

        Uses critical_config for more aggressive retry on increment operations.
        """
        if not self._connected:
            raise ConnectionError("Not connected to cache backend")

        async def _do_increment() -> CacheResult:
            await asyncio.sleep(0.02)

            cache_key = f"increment:{key}"
            self._operation_attempts[cache_key] = self._operation_attempts.get(cache_key, 0) + 1
            attempt = self._operation_attempts[cache_key]

            # Simulate transient failure
            if attempt <= 1:
                raise ConnectionError(f"Increment failed for '{key}' (attempt {attempt})")

            # Simulate successful increment
            current_value = 100  # Pretend current value
            new_value = current_value + amount

            return CacheResult(
                success=True,
                operation=CacheOperationType.INCREMENT,
                key=key,
                value=new_value,
                attempts=attempt,
            )

        return await retry_async(_do_increment, config=self.critical_config)

    async def health_check(self) -> CacheResult:
        """
        Check cache health with fast-fail retry configuration.
        """
        if not self._connected:
            raise ConnectionError("Not connected to cache backend")

        async def _check() -> CacheResult:
            await asyncio.sleep(0.01)

            # Simulate health check
            return CacheResult(
                success=True,
                operation=CacheOperationType.EXISTS,
                key="__health_check__",
                value="OK",
                attempts=1,
            )

        return await retry_async(_check, config=self.fast_fail_config)


async def main() -> None:  # noqa: PLR0915
    """Run the resilient cache client demo."""
    print("=" * 60)
    print("RESILIENT CACHE CLIENT WITH RETRY - DEMO")
    print("=" * 60)

    # Configure cache client
    config = CacheConfig(
        host="localhost",
        port=6379,
        password=None,
        db=0,
    )

    client = ResilientCacheClient(config, max_attempts=4, base_delay=0.3)

    # Demo 1: Connect with @retryable decorator
    print("\n--- Demo 1: Connect with @retryable decorator ---")
    try:
        result = await client.connect()
        print(f"Success: {result}")
    except (ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 2: Get with @retryable decorator
    print("\n--- Demo 2: GET with @retryable decorator ---")
    try:
        result = await client.get("user:123")
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 3: Set with @retryable decorator
    print("\n--- Demo 3: SET with @retryable decorator ---")
    try:
        result = await client.set("user:123", {"name": "John", "age": 30}, ttl=3600)
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 4: Delete with @retryable decorator
    print("\n--- Demo 4: DELETE with @retryable decorator ---")
    try:
        result = await client.delete("user:123")
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 5: Explicit retry_async pattern
    print("\n--- Demo 5: Explicit retry_async for GET ---")
    try:
        result = await client.get_with_explicit_retry("session:abc")
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 6: Concurrent mget with individual retries
    print("\n--- Demo 6: Concurrent MGET with individual retries ---")
    keys = ["user:1", "user:2", "missing:key", "user:3"]
    results = await client.mget(keys)
    for result in results:
        status = "SUCCESS" if result.success else "FAILED"
        print(f"  {result.key}: {status} (attempts: {result.attempts})")

    # Demo 7: Concurrent mset with individual retries
    print("\n--- Demo 7: Concurrent MSET with individual retries ---")
    mapping = {
        "config:feature_a": True,
        "config:feature_b": False,
        "config:timeout": 30,
    }
    results = await client.mset(mapping, ttl=86400)
    for result in results:
        status = "SUCCESS" if result.success else "FAILED"
        print(f"  {result.key}: {status} (attempts: {result.attempts})")

    # Demo 8: Increment with aggressive retry (critical operation)
    print("\n--- Demo 8: INCREMENT with aggressive retry (critical) ---")
    try:
        result = await client.increment_with_retry("counter:page_views", 1)
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 9: Health check with fast-fail
    print("\n--- Demo 9: Health check with fast-fail retry ---")
    try:
        result = await client.health_check()
        print(f"Success: {result}")
    except (ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
