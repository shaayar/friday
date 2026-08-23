"""
Database connection retry demo — demonstrates resilient database operations
with automatic retry logic for transient connection failures.
"""

import asyncio
import logging
from dataclasses import dataclass

from friday.tools.retry import RetryConfig, retry_async, retryable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class DatabaseResult:
    """Represents the result of a database operation."""

    success: bool
    query: str
    rows_affected: int
    attempts: int
    error: str | None = None


class ResilientDatabaseClient:
    """
    A database client that automatically retries failed operations with exponential backoff.

    This demonstrates using the retry utilities for:
    - Connecting to database with retry on transient connection failures
    - Executing queries with retry on temporary errors
    - Transaction handling with retry logic
    """

    def __init__(self, connection_string: str, max_attempts: int = 3, base_delay: float = 1.0):
        self.connection_string = connection_string
        self.config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=15.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(ConnectionError, TimeoutError, IOError),
        )
        self._connect_attempts = 0
        self._query_attempts: dict[str, int] = {}
        self._connected = False
        self._txn_attempts = 0
        self._health_attempts = 0

    @retryable(max_attempts=4, base_delay=0.5, retryable_exceptions=(ConnectionError, TimeoutError))
    async def connect(self) -> DatabaseResult:
        """
        Connect to database with automatic retry on transient connection failures.

        Simulates transient failures on first 2 attempts for demonstration.
        """
        await asyncio.sleep(0.1)  # Simulate connection delay

        self._connect_attempts += 1

        # Simulate transient failures (fail first 2 attempts)
        if self._connect_attempts <= 2:
            raise ConnectionError(
                f"Failed to connect to {self.connection_string} (attempt {self._connect_attempts})"
            )

        self._connected = True
        return DatabaseResult(
            success=True,
            query="CONNECT",
            rows_affected=0,
            attempts=self._connect_attempts,
        )

    @retryable(
        max_attempts=3,
        base_delay=0.3,
        retryable_exceptions=(ConnectionError, TimeoutError, IOError),
    )
    async def execute_query(self, query: str) -> DatabaseResult:
        """
        Execute a query with automatic retry on transient failures.

        Simulates transient failures on first attempt for demonstration.
        """
        if not self._connected:
            raise ConnectionError("Not connected to database")

        await asyncio.sleep(0.05)  # Simulate query execution delay

        if query not in self._query_attempts:
            self._query_attempts[query] = 0
        self._query_attempts[query] += 1

        # Simulate transient failure on first attempt for SELECT queries
        if query.strip().upper().startswith("SELECT") and self._query_attempts[query] <= 1:
            raise TimeoutError(f"Query timeout: {query} (attempt {self._query_attempts[query]})")

        # Simulate rows affected
        rows = 10 if query.strip().upper().startswith("SELECT") else 1

        return DatabaseResult(
            success=True,
            query=query,
            rows_affected=rows,
            attempts=self._query_attempts[query],
        )

    async def execute_transaction(self, queries: list[str]) -> list[DatabaseResult]:
        """
        Execute multiple queries in a transaction with retry logic.

        Uses explicit retry_async for more control over the transaction.
        """

        async def _do_transaction() -> list[DatabaseResult]:
            if not self._connected:
                raise ConnectionError("Not connected to database")

            results = []
            for query in queries:
                await asyncio.sleep(0.02)
                # Simulate a random transient failure
                self._txn_attempts += 1

                if self._txn_attempts <= 1:
                    raise ConnectionError("Transaction deadlock detected")

                results.append(
                    DatabaseResult(
                        success=True,
                        query=query,
                        rows_affected=1,
                        attempts=self._txn_attempts,
                    )
                )
            return results

        return await retry_async(_do_transaction, config=self.config)

    async def health_check(self) -> DatabaseResult:
        """
        Check database health with retry logic.

        Demonstrates using explicit retry_async for a simple operation.
        """

        async def _check() -> DatabaseResult:
            await asyncio.sleep(0.02)

            self._health_attempts += 1

            if self._health_attempts <= 1:
                raise OSError("Health check failed: connection pool exhausted")

            return DatabaseResult(
                success=True,
                query="HEALTH CHECK",
                rows_affected=0,
                attempts=self._health_attempts,
            )

        return await retry_async(_check, config=self.config)


async def main() -> None:
    """Run the resilient database client demo."""
    print("=" * 60)
    print("RESILIENT DATABASE CLIENT WITH RETRY - DEMO")
    print("=" * 60)

    client = ResilientDatabaseClient(
        "postgresql://user:pass@localhost:5432/mydb", max_attempts=4, base_delay=0.3
    )

    # Demo 1: Connect with @retryable decorator
    print("\n--- Demo 1: @retryable decorator on connect ---")
    try:
        result = await client.connect()
        print(f"Success: {result}")
    except (ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 2: Execute SELECT query with @retryable decorator
    print("\n--- Demo 2: @retryable decorator on SELECT query ---")
    try:
        result = await client.execute_query("SELECT * FROM users WHERE id = 1")
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 3: Execute INSERT query with @retryable decorator
    print("\n--- Demo 3: @retryable decorator on INSERT query ---")
    try:
        result = await client.execute_query("INSERT INTO users (name) VALUES ('Test User')")
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 4: Execute transaction with explicit retry_async
    print("\n--- Demo 4: Transaction with explicit retry_async ---")
    try:
        queries = [
            "BEGIN",
            "INSERT INTO orders (user_id, total) VALUES (1, 100.00)",
            "UPDATE users SET order_count = order_count + 1 WHERE id = 1",
            "COMMIT",
        ]
        results = await client.execute_transaction(queries)
        for result in results:
            print(f"  {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 5: Health check with explicit retry_async
    print("\n--- Demo 5: Health check with explicit retry_async ---")
    try:
        result = await client.health_check()
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
