import pytest
from pydantic import BaseModel

from sdoc.ai import cache


class Schema(BaseModel):
    value: str


class OtherSchema(BaseModel):
    value: int


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def test_key_is_deterministic():
    a = cache.cache_key("claude-opus-5", "hello", Schema)
    b = cache.cache_key("claude-opus-5", "hello", Schema)
    assert a == b


def test_key_changes_with_prompt():
    a = cache.cache_key("claude-opus-5", "hello", Schema)
    b = cache.cache_key("claude-opus-5", "goodbye", Schema)
    assert a != b


def test_key_changes_with_model():
    a = cache.cache_key("claude-opus-5", "hello", Schema)
    b = cache.cache_key("claude-haiku-4-5", "hello", Schema)
    assert a != b


def test_key_changes_with_schema():
    """A changed output schema must invalidate — stale entries no longer parse."""
    a = cache.cache_key("claude-opus-5", "hello", Schema)
    b = cache.cache_key("claude-opus-5", "hello", OtherSchema)
    assert a != b


def test_miss_returns_none():
    assert cache.cache_get("nonexistent") is None


def test_roundtrip():
    cache.cache_put("abc123", {"value": "stored"})
    assert cache.cache_get("abc123") == {"value": "stored"}
