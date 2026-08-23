"""
Resilient Data Fetcher — Feature implementation using retry utilities.

This module demonstrates a production-ready data fetching service with:
- Automatic retry with exponential backoff for transient failures
- Configurable retry policies per operation type
- Circuit breaker pattern integration
- Comprehensive logging and metrics
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from friday.tools.retry import RetryConfig, retry_async, retryable

T = TypeVar("T")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DataSourceType(Enum):
    """Types of data sources with different reliability profiles."""

    REST_API = "rest_api"
    DATABASE = "database"
    CACHE = "cache"
    MESSAGE_QUEUE = "message_queue"
    FILE_SYSTEM = "file_system"


@dataclass
class FetchResult:
    """Result of a data fetch operation."""

    success: bool
    data: Any = None
    source: str = ""
    source_type: DataSourceType = DataSourceType.REST_API
    attempts: int = 0
    elapsed_ms: float = 0.0
    error: str | None = None
    from_cache: bool = False


@dataclass
class DataSourceConfig:
    """Configuration for a specific data source."""

    name: str
    source_type: DataSourceType
    base_url: str = ""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    timeout_seconds: float = 10.0
    circuit_breaker_threshold: int = 5
    retryable_exceptions: tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        IOError,
    )


class CircuitBreaker:
    """Simple circuit breaker to prevent cascading failures."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.state = "closed"  # closed, open, half-open

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def can_execute(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.last_failure_time and (
                time.time() - self.last_failure_time > self.recovery_timeout
            ):
                self.state = "half-open"
                logger.info("Circuit breaker entering half-open state")
                return True
            return False
        # half-open state allows one request through
        return True


class ResilientDataFetcher:
    """
    A resilient data fetcher with automatic retry, circuit breaker, and metrics.

    Features:
    - Per-source retry configuration
    - Circuit breaker per source
    - Request/response logging
    - Latency metrics
    - Support for both sync and async operations
    """

    def __init__(self):
        self.sources: dict[str, DataSourceConfig] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.metrics: dict[str, dict[str, Any]] = {}
        self._db_attempts: dict[str, int] = {}
        self._cache_attempts: dict[str, int] = {}

    def register_source(self, config: DataSourceConfig) -> None:
        """Register a data source with its configuration."""
        self.sources[config.name] = config
        self.circuit_breakers[config.name] = CircuitBreaker(
            failure_threshold=config.circuit_breaker_threshold,
            recovery_timeout=60.0,
        )
        self.metrics[config.name] = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_retries": 0,
            "total_latency_ms": 0.0,
        }
        logger.info(f"Registered data source: {config.name} ({config.source_type.value})")

    def _get_retry_config(self, source_name: str) -> RetryConfig:
        """Get retry configuration for a source."""
        source = self.sources[source_name]
        return RetryConfig(
            max_attempts=source.max_attempts,
            base_delay=source.base_delay,
            max_delay=source.max_delay,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=source.retryable_exceptions,
        )

    def _record_metrics(
        self, source_name: str, success: bool, latency_ms: float, retries: int = 0
    ) -> None:
        """Record metrics for a source."""
        m = self.metrics[source_name]
        m["total_requests"] += 1
        m["total_latency_ms"] += latency_ms
        m["total_retries"] += retries
        if success:
            m["successful_requests"] += 1
        else:
            m["failed_requests"] += 1

    def get_metrics(self, source_name: str | None = None) -> dict[str, Any]:
        """Get metrics for a source or all sources."""
        if source_name:
            m = self.metrics[source_name].copy()
            if m["total_requests"] > 0:
                m["avg_latency_ms"] = m["total_latency_ms"] / m["total_requests"]
                m["success_rate"] = m["successful_requests"] / m["total_requests"]
            return m
        return {name: self.get_metrics(name) for name in self.metrics}

    @retryable(
        max_attempts=3,
        base_delay=0.5,
        retryable_exceptions=(ConnectionError, TimeoutError),
    )
    async def fetch_from_rest_api(self, source_name: str, endpoint: str) -> FetchResult:
        """
        Fetch data from a REST API with automatic retry.

        Uses the @retryable decorator for simple retry logic.
        """
        source = self.sources[source_name]
        circuit_breaker = self.circuit_breakers[source_name]
        start_time = time.time()

        if not circuit_breaker.can_execute():
            raise ConnectionError(f"Circuit breaker open for {source_name}")

        try:
            # Simulate network call
            await asyncio.sleep(0.1)

            # Simulate occasional failures (20% failure rate for demo)
            import random

            def _maybe_raise_connection_error() -> None:
                error_msg = f"Failed to connect to {source.base_url}{endpoint}"
                raise ConnectionError(error_msg)

            if random.random() < 0.2:
                _maybe_raise_connection_error()

            data = {
                "endpoint": endpoint,
                "data": f"Response from {endpoint}",
                "timestamp": time.time(),
            }

            circuit_breaker.record_success()
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_metrics(source_name, True, elapsed_ms)

            return FetchResult(
                success=True,
                data=data,
                source=source_name,
                source_type=source.source_type,
                attempts=1,  # The decorator handles retries internally
                elapsed_ms=elapsed_ms,
            )

        except Exception:
            circuit_breaker.record_failure()
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_metrics(source_name, False, elapsed_ms)
            raise

    async def fetch_from_database(self, source_name: str, query: str) -> FetchResult:
        """
        Fetch data from a database with explicit retry control.

        Uses retry_async for more granular control over the retry logic.
        """
        source = self.sources[source_name]
        circuit_breaker = self.circuit_breakers[source_name]
        retry_config = self._get_retry_config(source_name)
        start_time = time.time()

        if not circuit_breaker.can_execute():
            raise ConnectionError(f"Circuit breaker open for {source_name}")

        async def _execute_query() -> FetchResult:
            await asyncio.sleep(0.05)  # Simulate DB latency

            # Simulate transient failures
            if not hasattr(self, "_db_attempts"):
                self._db_attempts = {}
            key = f"{source_name}:{query}"
            self._db_attempts[key] = self._db_attempts.get(key, 0) + 1

            if self._db_attempts[key] <= 1:  # Fail first attempt
                raise TimeoutError(f"Database query timeout: {query}")

            return FetchResult(
                success=True,
                data={"query": query, "rows": [{"id": 1, "value": "test"}]},
                source=source_name,
                source_type=source.source_type,
                attempts=self._db_attempts[key],
                elapsed_ms=(time.time() - start_time) * 1000,
            )

        try:
            result = await retry_async(_execute_query, config=retry_config)
            circuit_breaker.record_success()
            self._record_metrics(source_name, True, result.elapsed_ms, result.attempts - 1)
            return result
        except Exception:
            circuit_breaker.record_failure()
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_metrics(source_name, False, elapsed_ms, retry_config.max_attempts - 1)
            raise

    @retryable(
        max_attempts=5,
        base_delay=0.1,
        retryable_exceptions=(ConnectionError, IOError),
    )
    async def fetch_from_cache(self, source_name: str, key: str) -> FetchResult:
        """
        Fetch data from cache with fast retry for transient issues.

        Cache failures are typically very fast to retry.
        """
        source = self.sources[source_name]
        circuit_breaker = self.circuit_breakers[source_name]
        start_time = time.time()

        if not circuit_breaker.can_execute():
            raise ConnectionError(f"Circuit breaker open for {source_name}")

        await asyncio.sleep(0.01)  # Cache is fast

        # Simulate cache miss on first attempt (transient)
        if not hasattr(self, "_cache_attempts"):
            self._cache_attempts = {}
        self._cache_attempts[key] = self._cache_attempts.get(key, 0) + 1

        if self._cache_attempts[key] == 1:
            raise ConnectionError(f"Cache connection reset for key: {key}")

        circuit_breaker.record_success()
        elapsed_ms = (time.time() - start_time) * 1000
        self._record_metrics(source_name, True, elapsed_ms)

        return FetchResult(
            success=True,
            data={"key": key, "value": f"cached_value_for_{key}", "ttl": 300},
            source=source_name,
            source_type=source.source_type,
            attempts=self._cache_attempts[key],
            elapsed_ms=elapsed_ms,
            from_cache=True,
        )

    async def fetch_with_fallback(
        self,
        primary_source: str,
        fallback_source: str,
        operation: Callable[..., Awaitable[FetchResult]],
        *args: Any,
        **kwargs: Any,
    ) -> FetchResult:
        """
        Fetch from primary source, fallback to secondary on failure.

        Demonstrates resilient patterns with retry + fallback.
        """
        # Try primary source
        try:
            result = await operation(primary_source, *args, **kwargs)
            logger.info(f"Primary source {primary_source} succeeded")
            return result
        except Exception as e:
            logger.warning(f"Primary source {primary_source} failed: {e}. Trying fallback...")

        # Try fallback source
        try:
            result = await operation(fallback_source, *args, **kwargs)
            logger.info(f"Fallback source {fallback_source} succeeded")
            return result
        except Exception:
            logger.exception("Fallback source %s also failed", fallback_source)
            raise


async def main() -> None:
    """Run the resilient data fetcher demo."""
    print("=" * 70)
    print("RESILIENT DATA FETCHER — Feature Demo with Retry & Circuit Breaker")
    print("=" * 70)

    fetcher = ResilientDataFetcher()

    # Register data sources with different configurations
    fetcher.register_source(
        DataSourceConfig(
            name="user-api",
            source_type=DataSourceType.REST_API,
            base_url="https://api.example.com",
            max_attempts=3,
            base_delay=0.5,
            max_delay=10.0,
            circuit_breaker_threshold=3,
        )
    )

    fetcher.register_source(
        DataSourceConfig(
            name="analytics-db",
            source_type=DataSourceType.DATABASE,
            base_url="postgresql://localhost:5432/analytics",
            max_attempts=5,
            base_delay=0.3,
            max_delay=5.0,
            circuit_breaker_threshold=5,
        )
    )

    fetcher.register_source(
        DataSourceConfig(
            name="redis-cache",
            source_type=DataSourceType.CACHE,
            base_url="redis://localhost:6379",
            max_attempts=5,
            base_delay=0.1,
            max_delay=1.0,
            circuit_breaker_threshold=10,
        )
    )

    # Demo 1: REST API with @retryable decorator
    print("\n--- Demo 1: REST API fetch with @retryable decorator ---")
    try:
        result = await fetcher.fetch_from_rest_api("user-api", "/users/123")
        print(f"  Success: {result.data}")
        print(f"  Latency: {result.elapsed_ms:.1f}ms")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 2: Database with explicit retry_async
    print("\n--- Demo 2: Database fetch with explicit retry_async ---")
    try:
        result = await fetcher.fetch_from_database("analytics-db", "SELECT * FROM events LIMIT 10")
        print(f"  Success: {result.data}")
        print(f"  Attempts: {result.attempts}, Latency: {result.elapsed_ms:.1f}ms")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 3: Cache with fast retry
    print("\n--- Demo 3: Cache fetch with fast retry ---")
    try:
        result = await fetcher.fetch_from_cache("redis-cache", "user:123:profile")
        print(f"  Success: {result.data}")
        print(f"  From cache: {result.from_cache}, Attempts: {result.attempts}")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 4: Fallback pattern
    print("\n--- Demo 4: Fallback pattern (primary -> fallback) ---")
    try:
        # Register a fallback source
        fetcher.register_source(
            DataSourceConfig(
                name="backup-api",
                source_type=DataSourceType.REST_API,
                base_url="https://backup.example.com",
                max_attempts=2,
                base_delay=0.5,
            )
        )

        result = await fetcher.fetch_with_fallback(
            "user-api",
            "backup-api",
            fetcher.fetch_from_rest_api,
            "/users/123",
        )
        print(f"  Success via fallback: {result.source}")
        print(f"  Data: {result.data}")
    except Exception as e:
        print(f"  Both sources failed: {e}")

    # Demo 5: Show metrics
    print("\n--- Demo 5: Metrics ---")
    metrics = fetcher.get_metrics()
    for source, m in metrics.items():
        print(f"  {source}:")
        print(
            f"    Requests: {m['total_requests']}, "
            f"Success: {m['successful_requests']}, "
            f"Failed: {m['failed_requests']}"
        )
        print(
            f"    Success rate: {m.get('success_rate', 0):.1%}, "
            f"Avg latency: {m.get('avg_latency_ms', 0):.1f}ms"
        )
        print(f"    Total retries: {m['total_retries']}")

    print("\n" + "=" * 70)
    print("RESILIENT DATA FETCHER DEMO COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
