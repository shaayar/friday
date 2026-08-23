"""
Feature implementation using retry utilities — demonstrates resilient file operations
with automatic retry logic for transient failures.
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
class FileOperationResult:
    """Represents the result of a file operation."""
    success: bool
    file_path: str
    operation: str
    attempts: int
    error: str | None = None


class ResilientFileManager:
    """
    A file manager that automatically retries failed operations with exponential backoff.

    This demonstrates using the retry utilities for:
    - Reading files with retry on transient I/O errors
    - Writing files with retry on temporary failures
    - Batch operations with individual retry policies
    """

    def __init__(self, max_attempts: int = 3, base_delay: float = 0.5):
        self.config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=10.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(IOError, OSError, ConnectionError, TimeoutError),
        )
        self._read_attempts: dict[str, int] = {}
        self._write_attempts: dict[str, int] = {}

    @retryable(
        max_attempts=3,
        base_delay=0.5,
        retryable_exceptions=(IOError, OSError)
    )
    async def read_file_with_retry(self, file_path: str) -> FileOperationResult:
        """
        Read a file with automatic retry on transient I/O errors.

        Simulates transient failures on first 2 attempts for demonstration.
        """
        await asyncio.sleep(0.05)  # Simulate I/O delay

        if file_path not in self._read_attempts:
            self._read_attempts[file_path] = 0
        self._read_attempts[file_path] += 1

        # Simulate transient failures (fail first 2 attempts)
        if self._read_attempts[file_path] <= 2:
            raise OSError(f"Transient read failure for {file_path} (attempt {self._read_attempts[file_path]})")

        # Success - return file content
        return FileOperationResult(
            success=True,
            file_path=file_path,
            operation="read",
            attempts=self._read_attempts[file_path],
        )

    @retryable(
        max_attempts=4,
        base_delay=0.3,
        retryable_exceptions=(IOError, OSError, TimeoutError)
    )
    async def write_file_with_retry(self, file_path: str, content: str) -> FileOperationResult:
        """
        Write a file with automatic retry on transient I/O errors.

        Simulates transient failures on first attempt for demonstration.
        """
        await asyncio.sleep(0.05)  # Simulate I/O delay

        if file_path not in self._write_attempts:
            self._write_attempts[file_path] = 0
        self._write_attempts[file_path] += 1

        # Simulate transient failure on first attempt
        if self._write_attempts[file_path] <= 1:
            raise TimeoutError(f"Write timeout for {file_path} (attempt {self._write_attempts[file_path]})")

        # Success
        return FileOperationResult(
            success=True,
            file_path=file_path,
            operation="write",
            attempts=self._write_attempts[file_path],
        )

    async def batch_read_with_retry(self, file_paths: list[str]) -> list[FileOperationResult]:
        """
        Read multiple files concurrently with individual retry policies.

        Uses explicit retry_async for more control over each operation.
        """
        async def _read_one(path: str) -> FileOperationResult:
            await asyncio.sleep(0.05)
            return FileOperationResult(
                success=True,
                file_path=path,
                operation="batch_read",
                attempts=1,
            )

        # Use retry_async for each file
        results = []
        for path in file_paths:
            try:
                result = await retry_async(_read_one, path, config=self.config)
                results.append(result)
            except (OSError, ConnectionError, TimeoutError) as e:
                results.append(FileOperationResult(
                    success=False,
                    file_path=path,
                    operation="batch_read",
                    attempts=self.config.max_attempts,
                    error=str(e)
                ))
        return results

    async def copy_file_with_retry(self, src: str, dst: str) -> FileOperationResult:
        """
        Copy a file with retry logic using explicit retry_async.

        Demonstrates the explicit retry pattern for compound operations.
        """
        async def _do_copy() -> FileOperationResult:
            # Read source
            read_result = await self.read_file_with_retry(src)
            if not read_result.success:
                raise OSError(f"Failed to read source: {read_result.error}")

            # Write destination (simulate)
            await asyncio.sleep(0.1)
            return FileOperationResult(
                success=True,
                file_path=dst,
                operation="copy",
                attempts=1,
            )

        return await retry_async(_do_copy, config=self.config)


async def main() -> None:
    """Run the resilient file manager demo."""
    print("=" * 60)
    print("RESILIENT FILE MANAGER WITH RETRY - DEMO")
    print("=" * 60)

    manager = ResilientFileManager(max_attempts=4, base_delay=0.3)

    # Demo 1: Read file with @retryable decorator
    print("\n--- Demo 1: @retryable decorator on read_file ---")
    try:
        result = await manager.read_file_with_retry("/tmp/test_read.txt")
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 2: Write file with @retryable decorator
    print("\n--- Demo 2: @retryable decorator on write_file ---")
    try:
        result = await manager.write_file_with_retry("/tmp/test_write.txt", "Hello, World!")
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 3: Batch read with explicit retry_async
    print("\n--- Demo 3: Batch read with explicit retry_async ---")
    file_paths = [f"/tmp/file_{i}.txt" for i in range(3)]
    results = await manager.batch_read_with_retry(file_paths)
    for result in results:
        print(f"  {result}")

    # Demo 4: Copy file with compound retry
    print("\n--- Demo 4: Copy file with compound retry ---")
    try:
        result = await manager.copy_file_with_retry("/tmp/source.txt", "/tmp/dest.txt")
        print(f"Success: {result}")
    except (OSError, ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
