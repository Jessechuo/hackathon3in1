from sdoc.ai import classify
from sdoc.config import CLASSIFY_MODEL


def test_prompt_contains_all_five_categories():
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "email_001"}
    prompt = classify.build_prompt(email)
    for category in ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]:
        assert category in prompt


def test_prompt_contains_the_email_content():
    email = {
        "from": "shipper@example.com",
        "subject": "TO CONFIRM DOCS",
        "body": "Attached are the SI and draft BL",
        "email_id": "email_001",
    }
    prompt = classify.build_prompt(email)
    assert "shipper@example.com" in prompt
    assert "TO CONFIRM DOCS" in prompt
    assert "Attached are the SI and draft BL" in prompt


def test_prompt_warns_that_subjects_mislead():
    """125 of 125 SI_REQUEST bodies contain the phrase 'draft BL'. The
    prompt must steer on intent, not vocabulary."""
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "email_001"}
    prompt = classify.build_prompt(email).lower()
    assert "subject" in prompt
    assert "intent" in prompt or "asking" in prompt


def test_classify_delegates_to_the_client(monkeypatch):
    captured = {}

    def fake_call(prompt, schema, model):
        captured["prompt"] = prompt
        captured["model"] = model
        return schema(category="SPAM", reason="prize scam")

    monkeypatch.setattr(classify, "call_structured", fake_call)

    email = {"from": "x@y.z", "subject": "You WON", "body": "claim now", "email_id": "email_003"}
    result = classify.classify(email)

    assert result.category == "SPAM"
    assert result.reason == "prize scam"
    assert captured["model"] == CLASSIFY_MODEL
    assert "You WON" in captured["prompt"]
