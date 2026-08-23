"""
Resilient Task Processor — Demonstrates retry feature for task processing operations.

This module implements a task processor that automatically retries failed operations
with exponential backoff, using the retry utilities from friday.tools.retry.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from friday.tools.retry import RetryConfig, retry_async, retryable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Represents the result of a task execution."""

    task_id: str
    success: bool
    result: Any = None
    attempts: int = 0
    error: str | None = None


class ResilientTaskProcessor:
    """
    A task processor with built-in retry logic for handling transient failures.

    Supports:
    - Individual task retry with @retryable decorator
    - Batch task processing with explicit retry_async
    - Configurable retry policies per task type
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 10.0,
    ):
        self.config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(ConnectionError, TimeoutError, IOError, OSError),
        )
        self._task_attempts: dict[str, int] = {}

    @retryable(
        max_attempts=3,
        base_delay=0.5,
        retryable_exceptions=(ConnectionError, TimeoutError),
    )
    async def process_task(self, task_id: str, payload: dict) -> TaskResult:
        """
        Process a single task with automatic retry on transient failures.

        Simulates transient failures on first attempts for demonstration.
        """
        await asyncio.sleep(0.05)  # Simulate processing delay

        if task_id not in self._task_attempts:
            self._task_attempts[task_id] = 0
        self._task_attempts[task_id] += 1

        # Simulate transient failure on first attempt
        if self._task_attempts[task_id] == 1:
            raise ConnectionError(f"Transient connection failure for task {task_id}")

        # Success on retry
        result = {"processed": True, "task_id": task_id, "output": payload.get("data", "default")}
        return TaskResult(
            task_id=task_id,
            success=True,
            result=result,
            attempts=self._task_attempts[task_id],
        )

    @retryable(
        max_attempts=4,
        base_delay=0.3,
        retryable_exceptions=(TimeoutError, IOError),
    )
    async def process_critical_task(self, task_id: str, payload: dict) -> TaskResult:
        """
        Process a critical task with more aggressive retry policy.

        Uses shorter delays and more attempts for critical operations.
        """
        await asyncio.sleep(0.05)

        if task_id not in self._task_attempts:
            self._task_attempts[task_id] = 0
        self._task_attempts[task_id] += 1

        # Simulate transient failure on first 2 attempts for critical tasks
        if self._task_attempts[task_id] <= 2:
            raise TimeoutError(
                f"Critical task {task_id} timed out (attempt {self._task_attempts[task_id]})"
            )

        result = {
            "processed": True,
            "task_id": task_id,
            "priority": "high",
            "output": payload.get("data"),
        }
        return TaskResult(
            task_id=task_id,
            success=True,
            result=result,
            attempts=self._task_attempts[task_id],
        )

    async def process_batch_with_retry(self, tasks: list[dict]) -> list[TaskResult]:
        """
        Process a batch of tasks with individual retry logic.

        Uses explicit retry_async for fine-grained control over each task.
        """
        results = []

        for task in tasks:
            task_id = task.get("id", "unknown")

            async def _process_single(current_task_id: str = task_id) -> TaskResult:
                await asyncio.sleep(0.05)
                return TaskResult(
                    task_id=current_task_id,
                    success=True,
                    result={"processed": True, "task_id": current_task_id},
                    attempts=1,
                )

            try:
                result = await retry_async(_process_single, config=self.config)
                results.append(result)
            except (OSError, ConnectionError, TimeoutError) as e:
                results.append(
                    TaskResult(
                        task_id=task_id,
                        success=False,
                        attempts=self.config.max_attempts,
                        error=str(e),
                    )
                )

        return results

    async def process_with_compound_retry(self, task_chain: list[dict]) -> TaskResult:
        """
        Process a chain of dependent tasks with compound retry logic.

        If any step fails, the entire chain is retried.
        """

        async def _execute_chain() -> TaskResult:
            chain_results = []
            for step in task_chain:
                await asyncio.sleep(0.05)
                chain_results.append({"step": step.get("name"), "status": "completed"})

            return TaskResult(
                task_id=task_chain[0].get("id", "chain"),
                success=True,
                result={"steps": chain_results},
                attempts=1,
            )

        return await retry_async(_execute_chain, config=self.config)


async def main() -> None:
    """Run the resilient task processor demo."""
    print("=" * 60)
    print("RESILIENT TASK PROCESSOR WITH RETRY - DEMO")
    print("=" * 60)

    processor = ResilientTaskProcessor(max_attempts=4, base_delay=0.3)

    # Demo 1: Standard task processing with @retryable
    print("\n--- Demo 1: Standard task with @retryable decorator ---")
    try:
        result = await processor.process_task("task-001", {"data": "sample payload"})
        print(f"Success: {result}")
    except (ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 2: Critical task with aggressive retry
    print("\n--- Demo 2: Critical task with aggressive retry ---")
    try:
        result = await processor.process_critical_task("task-critical-001", {"data": "important"})
        print(f"Success: {result}")
    except (ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 3: Batch processing with explicit retry_async
    print("\n--- Demo 3: Batch processing with explicit retry_async ---")
    batch_tasks = [{"id": f"batch-task-{i}", "data": f"item-{i}"} for i in range(3)]
    results = await processor.process_batch_with_retry(batch_tasks)
    for result in results:
        print(f"  {result}")

    # Demo 4: Compound retry for task chain
    print("\n--- Demo 4: Task chain with compound retry ---")
    task_chain = [
        {"id": "chain-001", "name": "validate"},
        {"id": "chain-001", "name": "transform"},
        {"id": "chain-001", "name": "store"},
    ]
    try:
        result = await processor.process_with_compound_retry(task_chain)
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
