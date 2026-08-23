"""
Resilient Web Scraper — Feature implementation using retry utilities.

This module demonstrates a production-ready web scraping service with:
- Automatic retry with exponential backoff for transient network failures
- Configurable retry policies per target site
- Rate limiting and polite scraping
- Comprehensive logging and metrics
- Support for both sync and async operations
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from friday.tools.retry import RetryConfig, retry_async, retryable

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ScraperMode(Enum):
    """Scraper operating modes."""

    SYNC = "sync"
    ASYNC = "async"


@dataclass
class ScrapedContent:
    """Result of a scraping operation."""

    success: bool
    url: str
    content: str = ""
    status_code: int = 0
    attempts: int = 0
    elapsed_ms: float = 0.0
    error: str | None = None


@dataclass
class SiteConfig:
    """Configuration for a specific site to scrape."""

    name: str
    base_url: str
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    timeout_seconds: float = 30.0
    rate_limit_delay: float = 1.0  # Minimum delay between requests
    retryable_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)
    headers: dict[str, str] | None = None


class ResilientWebScraper:
    """
    A resilient web scraper with automatic retry, rate limiting, and metrics.

    Features:
    - Per-site retry configuration
    - Rate limiting per site
    - Automatic retry on transient HTTP errors (5xx, 429)
    - Request/response logging
    - Latency metrics
    - Support for both sync and async operations
    """

    def __init__(self):
        self.sites: dict[str, SiteConfig] = {}
        self.metrics: dict[str, dict[str, Any]] = {}
        self._last_request_time: dict[str, float] = {}
        self._client: httpx.AsyncClient | None = None

    def register_site(self, config: SiteConfig) -> None:
        """Register a site with its configuration."""
        self.sites[config.name] = config
        self.metrics[config.name] = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_retries": 0,
            "total_latency_ms": 0.0,
            "status_codes": {},
        }
        self._last_request_time[config.name] = 0.0
        logger.info(f"Registered site: {config.name} ({config.base_url})")

    def _get_retry_config(self, site_name: str) -> RetryConfig:
        """Get retry configuration for a site."""
        site = self.sites[site_name]
        return RetryConfig(
            max_attempts=site.max_attempts,
            base_delay=site.base_delay,
            max_delay=site.max_delay,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(
                httpx.RequestError,
                httpx.TimeoutException,
                ConnectionError,
                TimeoutError,
            ),
        )

    async def _rate_limit(self, site_name: str) -> None:
        """Enforce rate limiting for a site."""
        site = self.sites[site_name]
        elapsed = time.time() - self._last_request_time[site_name]
        if elapsed < site.rate_limit_delay:
            await asyncio.sleep(site.rate_limit_delay - elapsed)
        self._last_request_time[site_name] = time.time()

    def _record_metrics(
        self, site_name: str, success: bool, latency_ms: float, status_code: int, retries: int = 0
    ) -> None:
        """Record metrics for a site."""
        m = self.metrics[site_name]
        m["total_requests"] += 1
        m["total_latency_ms"] += latency_ms
        m["total_retries"] += retries
        m["status_codes"][status_code] = m["status_codes"].get(status_code, 0) + 1
        if success:
            m["successful_requests"] += 1
        else:
            m["failed_requests"] += 1

    def get_metrics(self, site_name: str | None = None) -> dict[str, Any]:
        """Get metrics for a site or all sites."""
        if site_name:
            m = self.metrics[site_name].copy()
            if m["total_requests"] > 0:
                m["avg_latency_ms"] = m["total_latency_ms"] / m["total_requests"]
                m["success_rate"] = m["successful_requests"] / m["total_requests"]
            return m
        return {name: self.get_metrics(name) for name in self.metrics}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0),
                follow_redirects=True,
            )
        return self._client

    @retryable(
        max_attempts=3,
        base_delay=1.0,
        retryable_exceptions=(
            httpx.RequestError,
            httpx.TimeoutException,
            ConnectionError,
            TimeoutError,
        ),
    )
    async def fetch_async(self, site_name: str, path: str = "") -> ScrapedContent:
        """
        Fetch content from a site with automatic retry (decorator approach).

        Uses the @retryable decorator for simple retry logic.
        """
        site = self.sites[site_name]
        url = f"{site.base_url.rstrip('/')}/{path.lstrip('/')}"
        start_time = time.time()

        await self._rate_limit(site_name)

        client = await self._get_client()
        headers = site.headers or {}
        headers.setdefault("User-Agent", "ResilientWebScraper/1.0")

        try:
            response = await client.get(url, headers=headers, timeout=site.timeout_seconds)
            elapsed_ms = (time.time() - start_time) * 1000

            # Check for retryable status codes
            if response.status_code in site.retryable_status_codes:
                raise httpx.HTTPStatusError(
                    f"Retryable status code: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            content = response.text
            self._record_metrics(site_name, True, elapsed_ms, response.status_code)

            return ScrapedContent(
                success=True,
                url=url,
                content=content,
                status_code=response.status_code,
                attempts=1,  # The decorator handles retries internally
                elapsed_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            status_code = getattr(e, "response", None)
            status_code = status_code.status_code if status_code else 0
            self._record_metrics(site_name, False, elapsed_ms, status_code)
            raise

    async def fetch_with_explicit_retry(self, site_name: str, path: str = "") -> ScrapedContent:
        """
        Fetch content with explicit retry control (retry_async approach).

        Uses retry_async for more granular control over the retry logic.
        """
        site = self.sites[site_name]
        url = f"{site.base_url.rstrip('/')}/{path.lstrip('/')}"
        retry_config = self._get_retry_config(site_name)
        start_time = time.time()

        await self._rate_limit(site_name)

        client = await self._get_client()
        headers = site.headers or {}
        headers.setdefault("User-Agent", "ResilientWebScraper/1.0")

        attempt_count = {"count": 0}

        async def _do_fetch() -> ScrapedContent:
            attempt_count["count"] += 1
            response = await client.get(url, headers=headers, timeout=site.timeout_seconds)

            # Check for retryable status codes
            if response.status_code in site.retryable_status_codes:
                raise httpx.HTTPStatusError(
                    f"Retryable status code: {response.status_code}",
                    request=response.request,
                    response=response,
                )

            content = response.text
            elapsed_ms = (time.time() - start_time) * 1000
            self._record_metrics(
                site_name, True, elapsed_ms, response.status_code, attempt_count["count"] - 1
            )

            return ScrapedContent(
                success=True,
                url=url,
                content=content,
                status_code=response.status_code,
                attempts=attempt_count["count"],
                elapsed_ms=elapsed_ms,
            )

        try:
            result = await retry_async(_do_fetch, config=retry_config)
            return result
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            status_code = getattr(e, "response", None)
            status_code = status_code.status_code if status_code else 0
            self._record_metrics(site_name, False, elapsed_ms, status_code, attempt_count["count"])
            raise

    async def fetch_multiple(
        self, site_name: str, paths: list[str], max_concurrent: int = 3
    ) -> list[ScrapedContent]:
        """
        Fetch multiple URLs concurrently with semaphore for concurrency control.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _fetch_one(path: str) -> ScrapedContent:
            async with semaphore:
                return await self.fetch_with_explicit_retry(site_name, path)

        tasks = [_fetch_one(path) for path in paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed ScrapedContent
        final_results: list[ScrapedContent] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    ScrapedContent(
                        success=False,
                        url=f"{self.sites[site_name].base_url}/{paths[i]}",
                        error=str(result),
                        attempts=self.sites[site_name].max_attempts,
                    )
                )
            else:
                final_results.append(result)  # type: ignore[arg-type]  # result is ScrapedContent here

        return final_results

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def sync_fetch(self, site_name: str, path: str = "") -> ScrapedContent:
        """
        Synchronous fetch with retry (for environments without async support).

        Note: This uses a sync client internally.
        """
        import httpx as sync_httpx

        site = self.sites[site_name]
        url = f"{site.base_url.rstrip('/')}/{path.lstrip('/')}"
        start_time = time.time()

        # Simple sync rate limiting
        elapsed = time.time() - self._last_request_time[site_name]
        if elapsed < site.rate_limit_delay:
            time.sleep(site.rate_limit_delay - elapsed)
        self._last_request_time[site_name] = time.time()

        config = RetryConfig(
            max_attempts=site.max_attempts,
            base_delay=site.base_delay,
            max_delay=site.max_delay,
            exponential_base=2.0,
            jitter=True,
            retryable_exceptions=(
                sync_httpx.RequestError,
                sync_httpx.TimeoutException,
                ConnectionError,
                TimeoutError,
            ),
        )

        headers = site.headers or {}
        headers.setdefault("User-Agent", "ResilientWebScraper/1.0")

        attempt_count = {"count": 0}

        def _do_fetch() -> ScrapedContent:
            attempt_count["count"] += 1
            with sync_httpx.Client(timeout=site.timeout_seconds, follow_redirects=True) as client:
                response = client.get(url, headers=headers)

                # Check for retryable status codes
                if response.status_code in site.retryable_status_codes:
                    raise sync_httpx.HTTPStatusError(
                        f"Retryable status code: {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                content = response.text
                elapsed_ms = (time.time() - start_time) * 1000
                self._record_metrics(
                    site_name, True, elapsed_ms, response.status_code, attempt_count["count"] - 1
                )

                return ScrapedContent(
                    success=True,
                    url=url,
                    content=content,
                    status_code=response.status_code,
                    attempts=attempt_count["count"],
                    elapsed_ms=elapsed_ms,
                )

        try:
            from friday.tools.retry import retry_sync

            result = retry_sync(_do_fetch, config=config)
            return result
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            status_code = getattr(e, "response", None)
            status_code = status_code.status_code if status_code else 0
            self._record_metrics(site_name, False, elapsed_ms, status_code, attempt_count["count"])
            raise


async def main() -> None:
    """Run the resilient web scraper demo."""
    print("=" * 70)
    print("RESILIENT WEB SCRAPER — Feature Demo with Retry & Rate Limiting")
    print("=" * 70)

    scraper = ResilientWebScraper()

    # Register sites with different configurations
    scraper.register_site(
        SiteConfig(
            name="httpbin",
            base_url="https://httpbin.org",
            max_attempts=3,
            base_delay=0.5,
            max_delay=10.0,
            rate_limit_delay=0.5,
        )
    )

    scraper.register_site(
        SiteConfig(
            name="jsonplaceholder",
            base_url="https://jsonplaceholder.typicode.com",
            max_attempts=3,
            base_delay=0.5,
            max_delay=10.0,
            rate_limit_delay=0.3,
        )
    )

    # Demo 1: Simple async fetch with @retryable decorator
    print("\n--- Demo 1: Async fetch with @retryable decorator ---")
    try:
        result = await scraper.fetch_async("httpbin", "/get")
        print(f"  URL: {result.url}")
        print(f"  Status: {result.status_code}")
        print(f"  Latency: {result.elapsed_ms:.1f}ms")
        print(f"  Content length: {len(result.content)} chars")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 2: Explicit retry with retry_async
    print("\n--- Demo 2: Explicit retry with retry_async ---")
    try:
        result = await scraper.fetch_with_explicit_retry("jsonplaceholder", "/posts/1")
        print(f"  URL: {result.url}")
        print(f"  Status: {result.status_code}")
        print(f"  Attempts: {result.attempts}")
        print(f"  Latency: {result.elapsed_ms:.1f}ms")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 3: Concurrent fetches with rate limiting
    print("\n--- Demo 3: Concurrent fetches (max 2 concurrent) ---")
    paths = [f"/posts/{i}" for i in range(1, 6)]
    results = await scraper.fetch_multiple("jsonplaceholder", paths, max_concurrent=2)
    for result in results:
        status = "✓" if result.success else "✗"
        print(
            f"  {status} {result.url} - Status: {result.status_code}, Attempts: {result.attempts}"
        )

    # Demo 4: Sync fetch
    print("\n--- Demo 4: Synchronous fetch ---")
    try:
        result = scraper.sync_fetch("httpbin", "/headers")
        print(f"  URL: {result.url}")
        print(f"  Status: {result.status_code}")
        print(f"  Attempts: {result.attempts}")
        print(f"  Latency: {result.elapsed_ms:.1f}ms")
    except Exception as e:
        print(f"  Failed: {e}")

    # Demo 5: Show metrics
    print("\n--- Demo 5: Metrics ---")
    metrics = scraper.get_metrics()
    for site, m in metrics.items():
        print(f"  {site}:")
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
        print(f"    Status codes: {m['status_codes']}")

    await scraper.close()

    print("\n" + "=" * 70)
    print("RESILIENT WEB SCRAPER DEMO COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
