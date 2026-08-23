"""
Resilient File Processor with Retry — Feature implementation using retry utilities.
Demonstrates a practical feature: processing files with automatic retry on transient failures.
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from friday.tools.retry import RetryConfig, retryable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    """Represents the result of a file processing operation."""

    file_path: str
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0


class ResilientFileProcessor:
    """
    A file processor that automatically retries failed operations with exponential backoff.
    Handles transient failures like network issues, lock contention, and temporary I/O errors.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ):
        self.config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(
                ConnectionError,
                TimeoutError,
                IOError,
                OSError,
                PermissionError,
            ),
        )
        self._operation_counts: dict[str, int] = {}

    @retryable(max_attempts=3, base_delay=1.0, retryable_exceptions=(IOError, OSError))
    async def read_file(self, file_path: str) -> str:
        """
        Read file content with automatic retry on I/O errors.

        Args:
            file_path: Path to the file to read

        Returns:
            File content as string

        Raises:
            IOError: If all retry attempts fail
        """
        path = Path(file_path)

        # Track attempts for this file
        key = f"read:{file_path}"
        self._operation_counts[key] = self._operation_counts.get(key, 0) + 1
        attempt = self._operation_counts[key]

        # Simulate transient I/O failures (fail first attempt)
        if attempt == 1 and random.random() < 0.3:
            raise OSError(f"Transient I/O error reading {file_path}")

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = path.read_text(encoding="utf-8")
        logger.info("Successfully read %s on attempt %d", file_path, attempt)
        return content

    @retryable(
        max_attempts=3,
        base_delay=0.5,
        retryable_exceptions=(IOError, OSError, PermissionError),
    )
    async def write_file(self, file_path: str, content: str) -> ProcessResult:
        """
        Write content to file with automatic retry on I/O errors.

        Args:
            file_path: Path to the file to write
            content: Content to write

        Returns:
            ProcessResult with operation details
        """
        path = Path(file_path)

        # Track attempts for this file
        key = f"write:{file_path}"
        self._operation_counts[key] = self._operation_counts.get(key, 0) + 1
        attempt = self._operation_counts[key]

        # Simulate transient write failures (fail first attempt for some files)
        if attempt == 1 and "fail" in file_path.lower():
            raise PermissionError(f"Transient permission error writing {file_path}")

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(content, encoding="utf-8")
        logger.info("Successfully wrote %s on attempt %d", file_path, attempt)

        return ProcessResult(
            file_path=file_path,
            success=True,
            data={"bytes_written": len(content.encode("utf-8"))},
            attempts=attempt,
        )

    @retryable(max_attempts=5, base_delay=0.5, retryable_exceptions=(ConnectionError, TimeoutError))
    async def download_and_process(self, url: str, output_path: str) -> ProcessResult:
        """
        Simulate downloading a file from URL and processing it with retry.

        Args:
            url: URL to download from
            output_path: Local path to save processed content

        Returns:
            ProcessResult with operation details
        """
        # Track attempts for this URL
        key = f"download:{url}"
        self._operation_counts[key] = self._operation_counts.get(key, 0) + 1
        attempt = self._operation_counts[key]

        # Simulate network call
        await asyncio.sleep(0.1)

        # Simulate transient network failures (fail first 2 attempts for certain URLs)
        if attempt <= 2 and "unreliable" in url:
            raise ConnectionError(f"Network error downloading from {url}")

        # Simulate successful download
        content = f"Downloaded content from {url} (attempt {attempt})"

        # Write the downloaded content
        await self.write_file(output_path, content)

        return ProcessResult(
            file_path=output_path,
            success=True,
            data={"source_url": url, "size": len(content)},
            attempts=attempt,
        )

    async def process_batch(
        self, file_paths: list[str], operation: str = "read"
    ) -> list[ProcessResult]:
        """
        Process multiple files concurrently with individual retry logic.

        Args:
            file_paths: List of file paths to process
            operation: Operation type ('read' or 'write')

        Returns:
            List of ProcessResult for each file
        """
        tasks = []

        for file_path in file_paths:
            if operation == "read":
                task = self._process_single_read(file_path)
            elif operation == "write":
                task = self._process_single_write(file_path)
            else:
                raise ValueError(f"Unknown operation: {operation}")
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(
                    ProcessResult(
                        file_path=file_paths[i],
                        success=False,
                        error=str(result),
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    async def _process_single_read(self, file_path: str) -> ProcessResult:
        """Process a single file read with error handling."""
        try:
            content = await self.read_file(file_path)
            return ProcessResult(
                file_path=file_path,
                success=True,
                data={"content": content, "size": len(content)},
                attempts=self._operation_counts.get(f"read:{file_path}", 1),
            )
        except Exception as e:
            return ProcessResult(
                file_path=file_path,
                success=False,
                error=str(e),
                attempts=self._operation_counts.get(f"read:{file_path}", 1),
            )

    async def _process_single_write(self, file_path: str) -> ProcessResult:
        """Process a single file write with error handling."""
        content = f"Processed content for {file_path} at {time.time()}"
        try:
            return await self.write_file(file_path, content)
        except Exception as e:
            return ProcessResult(
                file_path=file_path,
                success=False,
                error=str(e),
                attempts=self._operation_counts.get(f"write:{file_path}", 1),
            )

    def get_stats(self) -> dict[str, int]:
        """Get operation statistics."""
        return dict(self._operation_counts)


async def main() -> None:
    """Run the resilient file processor demo."""
    print("=" * 60)
    print("RESILIENT FILE PROCESSOR WITH RETRY - DEMO")
    print("=" * 60)

    processor = ResilientFileProcessor(max_attempts=3, base_delay=0.2)

    # Create test files
    test_dir = Path("/tmp/friday_retry_test")
    test_dir.mkdir(exist_ok=True)

    test_files = [
        test_dir / "file1.txt",
        test_dir / "file2.txt",
        test_dir / "fail_write.txt",  # This will simulate a failure
        test_dir / "file3.txt",
    ]

    # Write initial test content
    for i, f in enumerate(test_files):
        if "fail" not in str(f):
            f.write_text(f"Test content for file {i + 1}\nLine 2\nLine 3")

    print(f"\n--- Created test files in {test_dir} ---")

    # Demo 1: Read files with retry
    print("\n--- Demo 1: Reading files with @retryable decorator ---")
    read_results = await processor.process_batch([str(f) for f in test_files], operation="read")

    _print_results(read_results)

    # Demo 2: Write files with retry
    print("\n--- Demo 2: Writing files with @retryable decorator ---")
    write_files = [
        test_dir / "output1.txt",
        test_dir / "fail_output.txt",  # This will simulate a failure
        test_dir / "output2.txt",
    ]

    write_results = await processor.process_batch([str(f) for f in write_files], operation="write")

    _print_results(write_results)

    # Demo 3: Download and process with retry
    print("\n--- Demo 3: Download and process with retry ---")
    download_tasks = [
        processor.download_and_process(
            "https://api.example.com/data/1", str(test_dir / "downloaded1.txt")
        ),
        processor.download_and_process(
            "https://unreliable.example.com/data/2", str(test_dir / "downloaded2.txt")
        ),
        processor.download_and_process(
            "https://api.example.com/data/3", str(test_dir / "downloaded3.txt")
        ),
    ]

    download_results = await asyncio.gather(*download_tasks, return_exceptions=True)

    _print_download_results(download_results)

    # Show stats
    print("\n--- Operation Statistics ---")
    stats = processor.get_stats()
    for op, count in stats.items():
        print(f"  {op}: {count} attempts")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


def _print_results(results: list[ProcessResult]) -> None:
    """Print process results."""
    for result in results:
        if result.success:
            if result.data and "size" in result.data:
                print(
                    f"  ✓ {result.file_path}: "
                    f"{result.data['size']} bytes "
                    f"(attempts: {result.attempts})"
                )
            elif result.data and "bytes_written" in result.data:
                print(
                    f"  ✓ {result.file_path}: "
                    f"{result.data['bytes_written']} bytes written "
                    f"(attempts: {result.attempts})"
                )
        else:
            print(f"  ✗ {result.file_path}: {result.error} (attempts: {result.attempts})")


def _print_download_results(
    results: list[ProcessResult | BaseException],
) -> None:
    """Print download results."""
    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            print(f"  ✗ Download {i + 1}: {result}")
        elif result.success:
            print(
                f"  ✓ Download {i + 1}: "
                f"{result.data['size']} bytes from "
                f"{result.data['source_url']} "
                f"(attempts: {result.attempts})"
            )
        else:
            print(f"  ✗ Download {i + 1}: {result.error} (attempts: {result.attempts})")


if __name__ == "__main__":
    asyncio.run(main())
