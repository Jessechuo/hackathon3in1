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


def test_prompt_keeps_check_requests_with_bad_attachments_as_comparison():
    """email_504 asked for a BL check but attached a packing list, and was
    classified SI_REQUEST, so it never reached the wrong-document check.
    A check request stays BL_COMPARISON whatever is (or isn't) attached."""
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "email_001"}
    prompt = classify.build_prompt(email).lower()
    assert "wrong type" in prompt
    assert "missing" in prompt


def flat(text: str) -> str:
    return " ".join(text.split()).lower()


def test_prompt_asks_about_intent_not_literal_attachment():
    """email_506/508/510 say the attachments 'appear to have been dropped'.
    Asked 'does it say documents are attached?', the model correctly said
    no. The question that matters is whether they were MEANT to be."""
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "email_001"}
    prompt = flat(classify.build_prompt(email))
    assert "documents_meant_to_be_attached" in prompt
    assert "even when they say the files are missing or were dropped" in prompt
    assert "says_documents_are_attached" not in prompt


def test_prompt_says_to_judge_the_newest_message_not_the_thread():
    """email_119 was read as a 'follow-up reminder' because of the quoted
    history at the bottom, not the check request at the top."""
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "email_001"}
    prompt = flat(classify.build_prompt(email))
    assert "newest message" in prompt and "quoted" in prompt


def test_prompt_lists_attachment_file_names():
    """30 emails say 'Pls assist to check the draft BL against the SI'. Haiku
    got 29 of 30 whatever the wording, but WHICH one it missed moved with
    each prompt change (email_119, then email_468). A person triaging would
    see the SI and BL attached; the model never did."""
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "email_468",
             "attachments": ["attachments/email_468_SI.txt", "attachments/email_468_BL.txt"]}
    prompt = classify.build_prompt(email)
    assert "Attachments: email_468_SI.txt, email_468_BL.txt" in prompt


def test_prompt_says_when_nothing_is_attached():
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "e", "attachments": []}
    assert "Attachments: none" in classify.build_prompt(email)


def test_classify_delegates_to_the_client(monkeypatch):
    captured = {}

    def fake_call(prompt, schema, model):
        captured["prompt"] = prompt
        captured["model"] = model
        return schema(category="SPAM", documents_meant_to_be_attached=False, reason="prize scam")

    monkeypatch.setattr(classify, "call_structured", fake_call)

    email = {"from": "x@y.z", "subject": "You WON", "body": "claim now", "email_id": "email_003"}
    result = classify.classify(email)

    assert result.category == "SPAM"
    assert result.reason == "prize scam"
    assert captured["model"] == CLASSIFY_MODEL
    assert "You WON" in captured["prompt"]
