"""The only file that imports `anthropic`.

Every call is cached on disk, so re-running the pipeline after changing
downstream logic costs nothing and returns instantly. Every call that does
reach the API is counted, so each run can print what it cost.
"""
import logging
import threading
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from sdoc.ai.cache import cache_get, cache_key, cache_put
from sdoc.config import PRICES

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# max_retries covers 429s, 5xx and connection errors with backoff. Raised
# above the default of 2 because this is a long unattended batch job.
_client = anthropic.Anthropic(max_retries=4)

_usage_lock = threading.Lock()
_usage: dict[str, list[int]] = {}      # model -> [calls, input_tokens, output_tokens]


def _parse(**kwargs):
    """Seam for tests to replace. Production path calls the real API."""
    return _client.messages.parse(**kwargs)


def _record(model: str, usage) -> None:
    if usage is None:
        return
    with _usage_lock:
        row = _usage.setdefault(model, [0, 0, 0])
        row[0] += 1
        row[1] += usage.input_tokens
        row[2] += usage.output_tokens


def reset_usage() -> None:
    with _usage_lock:
        _usage.clear()


def usage_summary() -> str:
    """One line describing the API calls made so far in this process."""
    with _usage_lock:
        rows = sorted(_usage.items())
    if not rows:
        return "API usage: 0 calls (everything came from the cache) - $0.00"
    parts, total = [], 0.0
    for model, (calls, tin, tout) in rows:
        pin, pout = PRICES.get(model, (0.0, 0.0))
        cost = tin / 1e6 * pin + tout / 1e6 * pout
        total += cost
        parts.append(f"{model}: {calls} calls, {tin:,} in / {tout:,} out tokens, ~${cost:.2f}")
    return "API usage: " + "; ".join(parts) + f" - total ~${total:.2f}"


def call_structured(prompt: str, schema: type[T], model: str, max_tokens: int = 2048) -> T:
    key = cache_key(model, prompt, schema)

    hit = cache_get(key)
    if hit is not None:
        return schema(**hit)

    try:
        response = _parse(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
    except anthropic.NotFoundError:
        log.error("Unknown model %r - check sdoc/config.py", model)
        raise
    except anthropic.RateLimitError:
        log.error("Rate limited after retries; lower --workers or wait")
        raise
    except anthropic.APIStatusError as e:
        log.error("API returned %s: %s", e.status_code, e)
        raise
    except anthropic.APIConnectionError:
        log.error("Could not reach the API - check your connection")
        raise

    _record(model, getattr(response, "usage", None))

    result = response.parsed_output
    if result is None:
        # Refusal or truncation. Never cache it: a retry might succeed.
        raise RuntimeError(
            f"{model} returned no structured output "
            f"(stop_reason={getattr(response, 'stop_reason', None)!r})"
        )
    cache_put(key, result.model_dump())
    return result
