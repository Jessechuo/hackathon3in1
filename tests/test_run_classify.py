from sdoc import run_classify
from sdoc.ai.classify import Classification


def test_classifies_every_email(monkeypatch):
    monkeypatch.setattr(
        run_classify, "classify",
        lambda e: Classification(category="SPAM", says_documents_are_attached=False, reason="test"),
    )
    emails = [{"email_id": f"email_{i:03d}"} for i in range(1, 6)]

    result = run_classify.classify_all(emails, workers=2)

    assert len(result) == 5
    assert result["email_001"]["category"] == "SPAM"
    assert result["email_001"]["error"] is None
    assert result["email_001"]["says_documents_are_attached"] is False


def test_one_failure_does_not_kill_the_batch(monkeypatch):
    """The submission must contain all 520 keys. A crash on one email
    must not drop the other 519."""
    def flaky(email):
        if email["email_id"] == "email_003":
            raise RuntimeError("boom")
        return Classification(category="GENERAL", says_documents_are_attached=False, reason="ok")

    monkeypatch.setattr(run_classify, "classify", flaky)
    emails = [{"email_id": f"email_{i:03d}"} for i in range(1, 6)]

    result = run_classify.classify_all(emails, workers=2)

    assert len(result) == 5, "every email must appear, even the failed one"
    assert result["email_003"]["error"] is not None
    assert "boom" in result["email_003"]["error"]
    assert result["email_003"]["category"] == "GENERAL", "failed emails fall back"
    assert result["email_004"]["category"] == "GENERAL"
