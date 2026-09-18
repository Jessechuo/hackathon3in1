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
