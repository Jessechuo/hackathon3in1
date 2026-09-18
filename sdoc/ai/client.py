"""The only file that imports `anthropic`.

Every call is cached on disk, so re-running the pipeline after changing
downstream logic costs nothing and returns instantly.
"""
import logging
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from sdoc.ai.cache import cache_get, cache_key, cache_put

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# max_retries covers 429s, 5xx and connection errors with backoff. Raised
# above the default of 2 because this is a long unattended batch job.
_client = anthropic.Anthropic(max_retries=4)


def _parse(**kwargs):
    """Seam for tests to replace. Production path calls the real API."""
    return _client.messages.parse(**kwargs)


def call_structured(prompt: str, schema: type[T], model: str) -> T:
    key = cache_key(model, prompt, schema)

    hit = cache_get(key)
    if hit is not None:
        return schema(**hit)

    try:
        response = _parse(
            model=model,
            max_tokens=2048,
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

    result = response.parsed_output
    cache_put(key, result.model_dump())
    return result
