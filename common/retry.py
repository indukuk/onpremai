"""Async retry decorator with exponential backoff.

Usage:
    from common.retry import retry

    @retry(max_attempts=3, base_delay=1.0, exceptions=(httpx.ConnectError,))
    async def call_external_service():
        ...

The decorator only applies to async functions. It retries only on the
specified exception types. Exponential backoff with optional jitter
prevents thundering herd.
"""

from __future__ import annotations

import asyncio
import functools
import random
from collections.abc import Awaitable, Callable
import sys
from typing import Any, TypeVar

if sys.version_info >= (3, 10):
    from typing import ParamSpec
else:
    from typing_extensions import ParamSpec

P = ParamSpec("P")
T = TypeVar("T")


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    jitter: bool = True,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Async retry decorator with exponential backoff and optional jitter.

    Args:
        max_attempts: Maximum number of attempts (including the first call).
            Must be >= 1.
        base_delay: Initial delay in seconds between retries.
        max_delay: Maximum delay cap in seconds.
        exceptions: Tuple of exception types to retry on. Other exceptions
            propagate immediately.
        jitter: If True, adds random jitter (0.5x to 1.5x) to the delay
            to prevent thundering herd.

    Returns:
        Decorator that wraps an async function with retry logic.

    Raises:
        The last exception encountered if all attempts fail.

    Example:
        @retry(max_attempts=3, base_delay=0.5, exceptions=(httpx.ConnectError,))
        async def fetch_data():
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://service/data")
                resp.raise_for_status()
                return resp.json()
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exception: BaseException | None = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc
                    if attempt == max_attempts - 1:
                        raise
                    delay = min(base_delay * (2**attempt), max_delay)
                    if jitter:
                        delay *= 0.5 + random.random()
                    await asyncio.sleep(delay)
            # This line should never be reached due to the raise above,
            # but satisfies type checker
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator
