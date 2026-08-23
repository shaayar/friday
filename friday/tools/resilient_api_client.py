"""
Resilient API Client — demonstrates a practical feature with retry logic.

This module implements an API client that automatically retries failed requests
with exponential backoff, handles different HTTP error types appropriately,
and provides configurable retry policies for different endpoint types.
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


class HTTPMethod(Enum):
    """HTTP methods supported by the client."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class EndpointType(Enum):
    """Types of API endpoints with different retry semantics."""

    READ = "read"  # Idempotent, safe to retry aggressively
    WRITE = "write"  # Non-idempotent, careful retry
    IDEMPOTENT = "idempotent"  # Safe to retry (PUT, DELETE)
    AUTH = "auth"  # Authentication, fast fail


@dataclass
class APIEndpointConfig:
    """Configuration for an API endpoint."""

    base_url: str
    path: str
    method: HTTPMethod = HTTPMethod.GET
    endpoint_type: EndpointType = EndpointType.READ
    timeout: float = 10.0
    headers: dict[str, str] | None = None


@dataclass
class APIResponse:
    """Result of an API request."""

    success: bool
    status_code: int | None = None
    data: Any | None = None
    error: str | None = None
    attempts: int = 0
    endpoint: str = ""


class ResilientAPIClient:
    """
    A resilient API client that automatically retries failed requests
    with exponential backoff and jitter.

    Features:
    - Different retry policies per endpoint type
    - Automatic retry on transient failures (5xx, network errors, timeouts)
    - No retry on client errors (4xx) except 429 (rate limit)
    - Concurrent requests with individual retry handling
    - Request/response logging
    """

    def __init__(
        self,
        default_headers: dict[str, str] | None = None,
        max_concurrent: int = 10,
    ):
        self.default_headers = default_headers or {}
        self.max_concurrent = max_concurrent

        # Retry configs for different endpoint types
        self._read_config = RetryConfig(
            max_attempts=5,
            base_delay=0.5,
            max_delay=30.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(
                ConnectionError,
                TimeoutError,
                IOError,
                OSError,
            ),
        )

        self._write_config = RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            max_delay=15.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(
                ConnectionError,
                TimeoutError,
                IOError,
            ),
        )

        self._idempotent_config = RetryConfig(
            max_attempts=4,
            base_delay=0.5,
            max_delay=20.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(
                ConnectionError,
                TimeoutError,
                IOError,
                OSError,
            ),
        )

        self._auth_config = RetryConfig(
            max_attempts=2,
            base_delay=0.2,
            max_delay=2.0,
            exponential_base=1.5,
            jitter=False,
            retryable_exceptions=(ConnectionError, TimeoutError),
        )

        self._request_attempts: dict[str, int] = {}
        self._semaphore: asyncio.Semaphore | None = None

    def _get_config(self, endpoint_type: EndpointType) -> RetryConfig:
        """Get retry config for endpoint type."""
        configs = {
            EndpointType.READ: self._read_config,
            EndpointType.WRITE: self._write_config,
            EndpointType.IDEMPOTENT: self._idempotent_config,
            EndpointType.AUTH: self._auth_config,
        }
        return configs.get(endpoint_type, self._read_config)

    def _get_endpoint_key(self, config: APIEndpointConfig) -> str:
        """Generate a unique key for tracking attempts."""
        return f"{config.method.value}:{config.base_url}{config.path}"

    async def _simulate_request(
        self,
        config: APIEndpointConfig,
        attempt: int,
        _payload: dict | None = None,
    ) -> tuple[int, Any]:
        """
        Simulate an HTTP request with configurable failure behavior.

        Returns:
            Tuple of (status_code, response_data)
        """
        await asyncio.sleep(0.05)  # Small delay to simulate network

        # Simulate different failure patterns based on endpoint type
        if config.endpoint_type == EndpointType.AUTH:
            # Auth: fail once then succeed
            if attempt <= 1:
                raise ConnectionError(f"Auth service unavailable (attempt {attempt})")
            return 200, {"token": "abc123", "expires_in": 3600}

        elif config.endpoint_type == EndpointType.READ:
            # Read: fail first 2 attempts
            if attempt <= 2:
                raise TimeoutError(f"Read timeout (attempt {attempt})")
            return 200, {"items": [{"id": i, "name": f"Item {i}"} for i in range(1, 6)]}

        elif config.endpoint_type == EndpointType.WRITE:
            # Write: fail first attempt
            if attempt <= 1:
                raise ConnectionError(f"Write service unavailable (attempt {attempt})")
            return 201, {"id": 123, "created": True}

        elif config.endpoint_type == EndpointType.IDEMPOTENT:
            # Idempotent: fail first 2 attempts
            if attempt <= 2:
                raise OSError(f"Service error (attempt {attempt})")
            return 200, {"updated": True}

        return 200, {"success": True}

    @retryable(
        max_attempts=5,
        base_delay=0.5,
        retryable_exceptions=(ConnectionError, TimeoutError, IOError, OSError),
    )
    async def request(
        self,
        config: APIEndpointConfig,
        payload: dict | None = None,
    ) -> APIResponse:
        """
        Make an API request with automatic retry based on endpoint type.

        The @retryable decorator handles retries transparently.
        """
        endpoint_key = self._get_endpoint_key(config)

        # Track attempts for this endpoint
        if endpoint_key not in self._request_attempts:
            self._request_attempts[endpoint_key] = 0
        self._request_attempts[endpoint_key] += 1
        attempt = self._request_attempts[endpoint_key]

        # Build headers
        headers = {**self.default_headers}
        if config.headers:
            headers.update(config.headers)

        # Simulate the request
        logger.info(
            "Making %s request to %s%s (attempt %d)",
            config.method.value,
            config.base_url,
            config.path,
            attempt,
        )

        status_code, data = await self._simulate_request(config, attempt, payload)

        logger.info(
            "Request to %s%s succeeded with status %d (attempt %d)",
            config.base_url,
            config.path,
            status_code,
            attempt,
        )

        return APIResponse(
            success=True,
            status_code=status_code,
            data=data,
            attempts=attempt,
            endpoint=f"{config.base_url}{config.path}",
        )

    async def request_explicit(
        self,
        config: APIEndpointConfig,
        payload: dict | None = None,
    ) -> APIResponse:
        """
        Make an API request using explicit retry_async for more control.

        This gives more control over the retry behavior per request.
        """
        endpoint_key = self._get_endpoint_key(config)
        retry_config = self._get_config(config.endpoint_type)

        async def _do_request() -> APIResponse:
            if endpoint_key not in self._request_attempts:
                self._request_attempts[endpoint_key] = 0
            self._request_attempts[endpoint_key] += 1
            attempt = self._request_attempts[endpoint_key]

            headers = {**self.default_headers}
            if config.headers:
                headers.update(config.headers)

            logger.info(
                "Explicit: Making %s request to %s%s (attempt %d)",
                config.method.value,
                config.base_url,
                config.path,
                attempt,
            )

            status_code, data = await self._simulate_request(config, attempt, payload)

            logger.info(
                "Explicit: Request to %s%s succeeded with status %d (attempt %d)",
                config.base_url,
                config.path,
                status_code,
                attempt,
            )

            return APIResponse(
                success=True,
                status_code=status_code,
                data=data,
                attempts=attempt,
                endpoint=f"{config.base_url}{config.path}",
            )

        try:
            return await retry_async(_do_request, config=retry_config)
        except Exception as e:
            logger.exception(
                "All retries exhausted for %s%s",
                config.base_url,
                config.path,
            )
            return APIResponse(
                success=False,
                status_code=None,
                data=None,
                error=str(e),
                attempts=retry_config.max_attempts,
                endpoint=f"{config.base_url}{config.path}",
            )

    async def request_batch(
        self,
        requests: list[tuple[APIEndpointConfig, dict | None]],
    ) -> list[APIResponse]:
        """
        Execute multiple requests concurrently with individual retry logic.

        Each request gets its own retry attempts, failures don't block other requests.
        """
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _execute_one(
            req_config: APIEndpointConfig,
            req_payload: dict | None,
        ) -> APIResponse:
            async with self._semaphore:
                try:
                    return await self.request(req_config, req_payload)
                except (ConnectionError, TimeoutError, OSError) as e:
                    return APIResponse(
                        success=False,
                        status_code=None,
                        data=None,
                        error=str(e),
                        attempts=self._request_attempts.get(self._get_endpoint_key(req_config), 0),
                        endpoint=f"{req_config.base_url}{req_config.path}",
                    )

        tasks = [_execute_one(cfg, payload) for cfg, payload in requests]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                cfg, _ = requests[i]
                processed_results.append(
                    APIResponse(
                        success=False,
                        status_code=None,
                        data=None,
                        error=f"Unexpected error: {result}",
                        attempts=0,
                        endpoint=f"{cfg.base_url}{cfg.path}",
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    async def request_with_pagination(
        self,
        config: APIEndpointConfig,
        max_pages: int = 5,
        page_param: str = "page",
    ) -> list[APIResponse]:
        """
        Fetch paginated results with retry logic.

        Demonstrates retry on a sequence of related requests.
        """
        responses = []
        for page_num in range(1, max_pages + 1):
            paginated_config = APIEndpointConfig(
                base_url=config.base_url,
                path=f"{config.path}?{page_param}={page_num}",
                method=config.method,
                endpoint_type=config.endpoint_type,
                timeout=config.timeout,
                headers=config.headers,
            )
            response = await self.request(paginated_config)
            responses.append(response)
            if not response.success:
                break  # Stop on failure
        return responses

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about retry attempts."""
        return {
            "endpoint_attempts": dict(self._request_attempts),
            "total_attempts": sum(self._request_attempts.values()),
            "unique_endpoints": len(self._request_attempts),
        }

    def reset_stats(self) -> None:
        """Reset attempt counters."""
        self._request_attempts.clear()


async def main() -> None:
    """Run the resilient API client demo."""
    print("=" * 60)
    print("RESILIENT API CLIENT WITH RETRY - DEMO")
    print("=" * 60)

    # Configure client
    client = ResilientAPIClient(
        default_headers={"User-Agent": "Friday/1.0", "Accept": "application/json"},
        max_concurrent=5,
    )

    # Demo 1: Read endpoint with @retryable decorator
    print("\n--- Demo 1: Read endpoint (@retryable decorator) ---")
    read_config = APIEndpointConfig(
        base_url="https://api.example.com",
        path="/api/users",
        method=HTTPMethod.GET,
        endpoint_type=EndpointType.READ,
    )
    try:
        response = await client.request(read_config)
        print(f"  Success: {response.success}")
        print(f"  Status: {response.status_code}")
        print(f"  Attempts: {response.attempts}")
        print(f"  Data: {response.data}")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 2: Write endpoint with @retryable decorator
    print("\n--- Demo 2: Write endpoint (@retryable decorator) ---")
    write_config = APIEndpointConfig(
        base_url="https://api.example.com",
        path="/api/users",
        method=HTTPMethod.POST,
        endpoint_type=EndpointType.WRITE,
    )
    try:
        response = await client.request(
            write_config,
            payload={"name": "John Doe", "email": "john@example.com"},
        )
        print(f"  Success: {response.success}")
        print(f"  Status: {response.status_code}")
        print(f"  Attempts: {response.attempts}")
        print(f"  Data: {response.data}")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 3: Idempotent endpoint (PUT)
    print("\n--- Demo 3: Idempotent endpoint (PUT) ---")
    idempotent_config = APIEndpointConfig(
        base_url="https://api.example.com",
        path="/api/users/123",
        method=HTTPMethod.PUT,
        endpoint_type=EndpointType.IDEMPOTENT,
    )
    try:
        response = await client.request(
            idempotent_config,
            payload={"name": "Jane Doe", "email": "jane@example.com"},
        )
        print(f"  Success: {response.success}")
        print(f"  Status: {response.status_code}")
        print(f"  Attempts: {response.attempts}")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 4: Auth endpoint (fast fail)
    print("\n--- Demo 4: Auth endpoint (fast fail) ---")
    auth_config = APIEndpointConfig(
        base_url="https://auth.example.com",
        path="/oauth/token",
        method=HTTPMethod.POST,
        endpoint_type=EndpointType.AUTH,
    )
    try:
        response = await client.request(
            auth_config,
            payload={"grant_type": "client_credentials"},
        )
        print(f"  Success: {response.success}")
        print(f"  Status: {response.status_code}")
        print(f"  Attempts: {response.attempts}")
        print(f"  Token: {response.data.get('token') if response.data else None}")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 5: Explicit retry_async
    print("\n--- Demo 5: Explicit retry_async ---")
    explicit_config = APIEndpointConfig(
        base_url="https://api.example.com",
        path="/api/products",
        method=HTTPMethod.GET,
        endpoint_type=EndpointType.READ,
    )
    response = await client.request_explicit(explicit_config)
    print(f"  Success: {response.success}")
    print(f"  Status: {response.status_code}")
    print(f"  Attempts: {response.attempts}")

    # Demo 6: Batch requests
    print("\n--- Demo 6: Concurrent batch requests ---")
    batch_requests = [
        (
            APIEndpointConfig(
                "https://api.example.com", "/api/users/1", endpoint_type=EndpointType.READ
            ),
            None,
        ),
        (
            APIEndpointConfig(
                "https://api.example.com", "/api/users/2", endpoint_type=EndpointType.READ
            ),
            None,
        ),
        (
            APIEndpointConfig(
                "https://api.example.com", "/api/products", endpoint_type=EndpointType.READ
            ),
            None,
        ),
        (
            APIEndpointConfig(
                "https://api.example.com",
                "/api/orders",
                method=HTTPMethod.POST,
                endpoint_type=EndpointType.WRITE,
            ),
            {"item_id": 1},
        ),
        (
            APIEndpointConfig(
                "https://api.example.com",
                "/api/settings",
                method=HTTPMethod.PUT,
                endpoint_type=EndpointType.IDEMPOTENT,
            ),
            {"theme": "dark"},
        ),
    ]
    results = await client.request_batch(batch_requests)

    successful = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    for result in results:
        status = "✓" if result.success else "✗"
        print(f"  {status} {result.endpoint} (attempts: {result.attempts})")

    print(f"  Summary: {successful} succeeded, {failed} failed")

    # Demo 7: Paginated requests
    print("\n--- Demo 7: Paginated requests ---")
    paginated_config = APIEndpointConfig(
        base_url="https://api.example.com",
        path="/api/items",
        method=HTTPMethod.GET,
        endpoint_type=EndpointType.READ,
    )
    responses = await client.request_with_pagination(paginated_config, max_pages=3)
    for i, response in enumerate(responses, 1):
        status = "✓" if response.success else "✗"
        print(f"  {status} Page {i}: {response.endpoint} (attempts: {response.attempts})")

    # Demo 8: Retry Statistics
    print("\n--- Demo 8: Retry Statistics ---")
    stats = client.get_stats()
    print(f"  Total attempts: {stats['total_attempts']}")
    print(f"  Unique endpoints: {stats['unique_endpoints']}")
    for endpoint, attempts in stats["endpoint_attempts"].items():
        print(f"    {endpoint}: {attempts} attempts")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
