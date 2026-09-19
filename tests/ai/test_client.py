import pytest
from pydantic import BaseModel

from sdoc.ai import cache, client


class Answer(BaseModel):
    label: str


class FakeParsed:
    def __init__(self, obj):
        self.parsed_output = obj


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


@pytest.fixture
def recorder(monkeypatch):
    """Replaces the real API call with a fake, recording every call."""
    calls = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        return FakeParsed(Answer(label="SPAM"))

    monkeypatch.setattr(client, "_parse", fake_parse)
    return calls


def test_calls_api_on_miss_and_returns_parsed(recorder):
    result = client.call_structured("is this spam?", Answer, "claude-opus-5")

    assert result.label == "SPAM"
    assert len(recorder) == 1
    assert recorder[0]["model"] == "claude-opus-5"
    assert recorder[0]["output_format"] is Answer


def test_second_identical_call_hits_cache(recorder):
    client.call_structured("is this spam?", Answer, "claude-opus-5")
    result = client.call_structured("is this spam?", Answer, "claude-opus-5")

    assert result.label == "SPAM"
    assert len(recorder) == 1, "second call must come from cache, not the API"


def test_different_prompt_calls_api_again(recorder):
    client.call_structured("prompt A", Answer, "claude-opus-5")
    client.call_structured("prompt B", Answer, "claude-opus-5")

    assert len(recorder) == 2


class FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def test_usage_is_counted_only_for_real_api_calls(monkeypatch):
    client.reset_usage()

    def fake_parse(**kwargs):
        r = FakeParsed(Answer(label="SPAM"))
        r.usage = FakeUsage(1000, 50)
        return r

    monkeypatch.setattr(client, "_parse", fake_parse)
    client.call_structured("p", Answer, "claude-haiku-4-5")
    client.call_structured("p", Answer, "claude-haiku-4-5")   # cache hit: not counted

    s = client.usage_summary()
    assert "1 calls" in s
    assert "1,000 in / 50 out" in s


def test_usage_summary_when_nothing_was_called():
    client.reset_usage()
    assert "0 calls" in client.usage_summary()


def test_empty_structured_output_raises_and_is_not_cached(monkeypatch):
    class Empty:
        parsed_output = None
        stop_reason = "refusal"
        usage = None

    monkeypatch.setattr(client, "_parse", lambda **kw: Empty())
    with pytest.raises(RuntimeError, match="refusal"):
        client.call_structured("q", Answer, "claude-opus-5")
    assert cache.cache_get(cache.cache_key("claude-opus-5", "q", Answer)) is None


def test_max_tokens_is_passed_through(recorder):
    client.call_structured("x", Answer, "claude-opus-5", max_tokens=8000)
    assert recorder[0]["max_tokens"] == 8000
