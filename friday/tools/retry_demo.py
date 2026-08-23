"""
Retry Feature Demo — demonstrates using retry utilities for resilient operations.
This file implements a feature that uses exponential backoff retry logic.
"""

import asyncio
import logging
import random
from typing import Any

from friday.tools.retry import RetryConfig, retry_async, retry_sync, retryable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class FlakyService:
    """Simulates a flaky external service that fails intermittently."""

    def __init__(self, fail_rate: float = 0.7):
        self.fail_rate = fail_rate
        self.call_count = 0

    async def async_call(self, data: str) -> str:
        """Simulate an async service call that may fail."""
        self.call_count += 1
        await asyncio.sleep(0.1)  # Simulate network delay

        if random.random() < self.fail_rate:
            raise ConnectionError(f"Service unavailable (attempt {self.call_count})")

        return f"Success: {data} (attempt {self.call_count})"

    def sync_call(self, data: str) -> str:
        """Simulate a sync service call that may fail."""
        self.call_count += 1

        if random.random() < self.fail_rate:
            raise ConnectionError(f"Service unavailable (attempt {self.call_count})")

        return f"Success: {data} (attempt {self.call_count})"


class DataProcessor:
    """Processes data with automatic retry on transient failures."""

    def __init__(self, max_attempts: int = 5, base_delay: float = 0.2):
        self.config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=5.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(ConnectionError, TimeoutError, IOError),
        )
        self.service = FlakyService(fail_rate=0.6)

    @retryable(max_attempts=3, base_delay=0.2, retryable_exceptions=(ConnectionError,))
    async def process_with_decorator(self, item: str) -> dict[str, Any]:
        """Process an item using the @retryable decorator."""
        result = await self.service.async_call(item)
        return {"item": item, "result": result, "method": "decorator"}

    async def process_with_explicit_retry(self, item: str) -> dict[str, Any]:
        """Process an item using explicit retry_async."""
        result = await retry_async(self.service.async_call, item, config=self.config)
        return {"item": item, "result": result, "method": "explicit_retry"}

    def process_sync_with_retry(self, item: str) -> dict[str, Any]:
        """Process an item synchronously with retry."""
        result = retry_sync(self.service.sync_call, item, config=self.config)
        return {"item": item, "result": result, "method": "sync_retry"}

    async def process_batch(self, items: list[str]) -> list[dict[str, Any]]:
        """Process multiple items concurrently with retry."""
        tasks = [self.process_with_explicit_retry(item) for item in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append(
                    {
                        "item": items[i],
                        "result": None,
                        "method": "batch_retry",
                        "error": str(result),
                    }
                )
            else:
                processed.append(result)
        return processed


async def main() -> None:
    """Run the retry feature demo."""
    print("=" * 60)
    print("RETRY FEATURE DEMO — Resilient Operations with Exponential Backoff")
    print("=" * 60)

    processor = DataProcessor(max_attempts=5, base_delay=0.1)

    # Demo 1: Using @retryable decorator
    print("\n--- Demo 1: @retryable decorator ---")
    try:
        result = await processor.process_with_decorator("data-item-1")
        print(f"Success: {result}")
    except ConnectionError as e:
        print(f"Failed after retries: {e}")

    # Demo 2: Using explicit retry_async
    print("\n--- Demo 2: Explicit retry_async ---")
    try:
        result = await processor.process_with_explicit_retry("data-item-2")
        print(f"Success: {result}")
    except ConnectionError as e:
        print(f"Failed after retries: {e}")

    # Demo 3: Using sync retry
    print("\n--- Demo 3: Sync retry_sync ---")
    try:
        result = processor.process_sync_with_retry("data-item-3")
        print(f"Success: {result}")
    except ConnectionError as e:
        print(f"Failed after retries: {e}")

    # Demo 4: Batch processing with retry
    print("\n--- Demo 4: Batch processing with retry ---")
    items = [f"batch-item-{i}" for i in range(5)]
    results = await processor.process_batch(items)
    for result in results:
        if "error" in result:
            print(f"  Failed: {result['item']} - {result['error']}")
        else:
            print(f"  Success: {result['item']} - {result['result']}")

    print("\n" + "=" * 60)
    print("RETRY FEATURE DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
