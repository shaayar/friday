"""
Feature implementation using retry utilities — demonstrates resilient API client with retry logic.
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any

from friday.tools.retry import RetryConfig, retry_async, retryable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class APIResponse:
    """Represents an API response."""

    status_code: int
    data: dict[str, Any]
    headers: dict[str, str]


class ResilientAPIClient:
    """
    An API client that automatically retries failed requests with exponential backoff.
    """

    def __init__(self, base_url: str, max_attempts: int = 3, base_delay: float = 1.0):
        self.base_url = base_url
        self.config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=30.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(ConnectionError, TimeoutError, IOError),
        )

    @retryable(max_attempts=3, base_delay=1.0, retryable_exceptions=(ConnectionError, TimeoutError))
    async def fetch_user(self, user_id: int) -> APIResponse:
        """
        Fetch user data with automatic retry on transient failures.
        """
        # Simulate network call
        await asyncio.sleep(0.1)

        # Simulate transient failures (fail first 2 attempts)
        if not hasattr(self, "_fetch_user_attempts"):
            self._fetch_user_attempts = 0
        self._fetch_user_attempts += 1

        if self._fetch_user_attempts <= 2:
            raise ConnectionError(f"Failed to connect to {self.base_url}/users/{user_id}")

        return APIResponse(
            status_code=200,
            data={"id": user_id, "name": f"User {user_id}", "email": f"user{user_id}@example.com"},
            headers={"content-type": "application/json"},
        )

    async def fetch_user_with_explicit_retry(self, user_id: int) -> APIResponse:
        """
        Fetch user data using explicit retry_async call (alternative to decorator).
        """

        async def _do_fetch() -> APIResponse:
            await asyncio.sleep(0.1)

            if not hasattr(self, "_explicit_fetch_attempts"):
                self._explicit_fetch_attempts = 0
            self._explicit_fetch_attempts += 1

            if self._explicit_fetch_attempts <= 1:
                raise TimeoutError(f"Request to {self.base_url}/users/{user_id} timed out")

            return APIResponse(
                status_code=200,
                data={"id": user_id, "name": f"User {user_id}", "role": "admin"},
                headers={"content-type": "application/json"},
            )

        return await retry_async(_do_fetch, config=self.config)

    @retryable(max_attempts=5, base_delay=0.5, retryable_exceptions=(IOError,))
    async def upload_file(self, file_path: str, content: bytes) -> dict[str, Any]:
        """
        Upload a file with retry logic for transient storage errors.
        """
        # Simulate file upload
        await asyncio.sleep(0.05)

        if not hasattr(self, "_upload_attempts"):
            self._upload_attempts = {}
        if file_path not in self._upload_attempts:
            self._upload_attempts[file_path] = 0
        self._upload_attempts[file_path] += 1

        if self._upload_attempts[file_path] <= 2:
            raise OSError(f"Storage unavailable for {file_path}")

        return {
            "file_id": f"file_{random.randint(1000, 9999)}",
            "path": file_path,
            "size": len(content),
            "status": "uploaded",
        }


async def main() -> None:
    """Run the resilient API client demo."""
    print("=" * 60)
    print("RESILIENT API CLIENT WITH RETRY - DEMO")
    print("=" * 60)

    client = ResilientAPIClient("https://api.example.com", max_attempts=4, base_delay=0.5)

    # Demo 1: Using @retryable decorator
    print("\n--- Demo 1: @retryable decorator on fetch_user ---")
    try:
        user = await client.fetch_user(42)
        print(f"Success: {user.data}")
    except (ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 2: Using explicit retry_async
    print("\n--- Demo 2: Explicit retry_async on fetch_user ---")
    try:
        user = await client.fetch_user_with_explicit_retry(99)
        print(f"Success: {user.data}")
    except (ConnectionError, TimeoutError) as e:
        print(f"Failed: {e}")

    # Demo 3: File upload with retry
    print("\n--- Demo 3: @retryable decorator on upload_file ---")
    try:
        result = await client.upload_file("/tmp/test.txt", b"Hello, World!")
        print(f"Upload result: {result}")
    except OSError as e:
        print(f"Failed: {e}")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
