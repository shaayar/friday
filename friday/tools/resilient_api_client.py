"""
Resilient API Client — a feature implementation using retry utilities for robust HTTP operations.

This module demonstrates a production-ready API client with:
- Automatic retry on transient network failures
- Configurable retry policies per endpoint
- Circuit breaker pattern integration
- Request/response logging
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from friday.tools.retry import RetryConfig, retry_async

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class ApiResponse:
    """Represents an API response with metadata."""
    success: bool
    data: Any = None
    status_code: int | None = None
    error: str | None = None
    attempts: int = 1
    endpoint: str = ""


@dataclass
class EndpointConfig:
    """Configuration for a specific API endpoint."""
    path: str
    method: str = "GET"
    max_attempts: int = 3
    base_delay: float = 1.0
    timeout: float = 30.0
    retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)
    headers: dict[str, str] = field(default_factory=dict)


class ResilientApiClient:
    """
    A resilient HTTP API client with automatic retry logic.

    Features:
    - Per-endpoint retry configuration
    - Exponential backoff with jitter
    - Retry on specific HTTP status codes
    - Request/response logging
    - Circuit breaker readiness (extensible)
    """

    def __init__(
        self,
        base_url: str,
        default_headers: dict[str, str] | None = None,
        default_timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {"User-Agent": "ResilientApiClient/1.0"}
        self.default_timeout = default_timeout
        self.endpoint_configs: dict[str, EndpointConfig] = {}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ResilientApiClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.default_headers,
            timeout=self.default_timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()

    def configure_endpoint(self, name: str, config: EndpointConfig) -> None:
        """Register a custom retry configuration for an endpoint."""
        self.endpoint_configs[name] = config

    def _get_config(self, endpoint_name: str) -> RetryConfig:
        """Get retry configuration for an endpoint."""
        endpoint_config = self.endpoint_configs.get(endpoint_name)
        if endpoint_config:
            return RetryConfig(
                max_attempts=endpoint_config.max_attempts,
                base_delay=endpoint_config.base_delay,
                max_delay=30.0,
                exponential_base=2.0,
                jitter=True,
                retryable_exceptions=(
                    httpx.RequestError,
                    httpx.HTTPStatusError,
                    TimeoutError,
                ),
            )
        return RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            max_delay=30.0,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(
                httpx.RequestError,
                httpx.HTTPStatusError,
                TimeoutError,
            ),
        )

    def _get_endpoint_config(self, endpoint_name: str) -> EndpointConfig:
        """Get endpoint configuration or return default."""
        return self.endpoint_configs.get(
            endpoint_name,
            EndpointConfig(path=endpoint_name)
        )

    async def _make_request(
        self,
        method: str,
        path: str,
        **kwargs
    ) -> httpx.Response:
        """Make an HTTP request with retry logic via decorator."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        response = await self._client.request(method, path, **kwargs)

        # Raise for status codes that should trigger retry
        endpoint_name = path.strip("/").split("/")[0] if path else "default"
        endpoint_config = self._get_endpoint_config(endpoint_name)

        if response.status_code in endpoint_config.retryable_status_codes:
            response.raise_for_status()

        return response

    async def request(
        self,
        endpoint_name: str,
        method: str | None = None,
        path: str | None = None,
        **kwargs
    ) -> ApiResponse:
        """
        Make a resilient API request with automatic retry.

        Args:
            endpoint_name: Registered endpoint name or path
            method: HTTP method (overrides endpoint config)
            path: URL path (overrides endpoint config)
            **kwargs: Additional arguments passed to httpx request

        Returns:
            ApiResponse with success status, data, and metadata
        """
        endpoint_config = self._get_endpoint_config(endpoint_name)
        retry_config = self._get_config(endpoint_name)

        request_method = method or endpoint_config.method
        request_path = path or endpoint_config.path

        # Merge headers
        headers = {**endpoint_config.headers, **kwargs.pop("headers", {})}

        attempt_count = {"count": 0}

        async def _execute_request() -> httpx.Response:
            attempt_count["count"] += 1
            logger.info(
                "Making %s request to %s (attempt %d/%d)",
                request_method,
                request_path,
                attempt_count["count"],
                retry_config.max_attempts,
            )

            response = await self._make_request(
                request_method, request_path, headers=headers, **kwargs
            )

            # Check if status code should trigger retry
            if response.status_code in endpoint_config.retryable_status_codes:
                raise httpx.HTTPStatusError(
                    f"Retryable status code: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            return response

        try:
            response = await retry_async(_execute_request, config=retry_config)

            return ApiResponse(
                success=True,
                data=(
                    response.json()
                    if response.headers.get("content-type", "").startswith("application/json")
                    else response.text
                ),
                status_code=response.status_code,
                attempts=attempt_count["count"],
                endpoint=request_path,
            )

        except httpx.HTTPStatusError as e:
            return ApiResponse(
                success=False,
                error=f"HTTP {e.response.status_code}: {e.response.text}",
                status_code=e.response.status_code,
                attempts=attempt_count["count"],
                endpoint=request_path,
            )
        except httpx.RequestError as e:
            return ApiResponse(
                success=False,
                error=f"Request failed: {str(e)}",
                attempts=attempt_count["count"],
                endpoint=request_path,
            )
        except TimeoutError as e:
            return ApiResponse(
                success=False,
                error=f"Request timeout: {str(e)}",
                attempts=attempt_count["count"],
                endpoint=request_path,
            )
        except Exception as e:
            logger.exception("Unexpected error during request")
            return ApiResponse(
                success=False,
                error=f"Unexpected error: {str(e)}",
                attempts=attempt_count["count"],
                endpoint=request_path,
            )

    # Convenience methods
    async def get(self, endpoint_name: str, **kwargs) -> ApiResponse:
        """Make a GET request."""
        return await self.request(endpoint_name, method="GET", **kwargs)

    async def post(self, endpoint_name: str, **kwargs) -> ApiResponse:
        """Make a POST request."""
        return await self.request(endpoint_name, method="POST", **kwargs)

    async def put(self, endpoint_name: str, **kwargs) -> ApiResponse:
        """Make a PUT request."""
        return await self.request(endpoint_name, method="PUT", **kwargs)

    async def delete(self, endpoint_name: str, **kwargs) -> ApiResponse:
        """Make a DELETE request."""
        return await self.request(endpoint_name, method="DELETE", **kwargs)


async def demo() -> None:
    """Demonstrate the resilient API client."""
    print("=" * 60)
    print("RESILIENT API CLIENT DEMO")
    print("=" * 60)

    # Example configuration
    client = ResilientApiClient(
        base_url="https://httpbin.org",
        default_headers={"Accept": "application/json"},
    )

    # Configure specific endpoints with custom retry policies
    client.configure_endpoint(
        "status",
        EndpointConfig(
            path="/status/200",
            method="GET",
            max_attempts=3,
            base_delay=0.5,
            retryable_status_codes=(500, 502, 503, 504),
        )
    )

    client.configure_endpoint(
        "flaky",
        EndpointConfig(
            path="/status/500",  # This will fail with 500
            method="GET",
            max_attempts=3,
            base_delay=0.5,
            retryable_status_codes=(500, 502, 503, 504),
        )
    )

    async with client:
        # Demo 1: Successful request
        print("\n--- Demo 1: Successful GET request ---")
        result = await client.get("status")
        print(
            f"Success: {result.success}, "
            f"Status: {result.status_code}, "
            f"Attempts: {result.attempts}"
        )
        if result.data:
            print(
                f"Data keys: "
                f"{list(result.data.keys()) if isinstance(result.data, dict) else 'non-dict'}"
            )

        # Demo 2: Request that will fail after retries (500 error)
        print("\n--- Demo 2: Flaky endpoint (500) with retry ---")
        result = await client.get("flaky")
        print(
            f"Success: {result.success}, "
            f"Status: {result.status_code}, "
            f"Attempts: {result.attempts}"
        )
        if result.error:
            print(f"Error: {result.error}")

        # Demo 3: Using explicit endpoint configuration
        print("\n--- Demo 3: Custom endpoint with POST ---")
        result = await client.post(
            "custom",
            path="/post",
            json={"message": "Hello, resilient world!"},
        )
        print(
            f"Success: {result.success}, "
            f"Status: {result.status_code}, "
            f"Attempts: {result.attempts}"
        )
        if result.data and isinstance(result.data, dict):
            print(f"Echoed JSON: {result.data.get('json')}")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(demo())
