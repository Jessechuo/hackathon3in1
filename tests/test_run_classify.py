from sdoc import run_classify
from sdoc.ai.classify import Classification


def test_classifies_every_email(monkeypatch):
    monkeypatch.setattr(
        run_classify, "classify",
        lambda e: Classification(category="SPAM", documents_meant_to_be_attached=False, reason="test"),
    )
    emails = [{"email_id": f"email_{i:03d}"} for i in range(1, 6)]

    result = run_classify.classify_all(emails, workers=2)

    assert len(result) == 5
    assert result["email_001"]["category"] == "SPAM"
    assert result["email_001"]["error"] is None
    assert result["email_001"]["documents_meant_to_be_attached"] is False


def test_one_failure_does_not_kill_the_batch(monkeypatch):
    """The submission must contain all 520 keys. A crash on one email
    must not drop the other 519."""
    def flaky(email):
        if email["email_id"] == "email_003":
            raise RuntimeError("boom")
        return Classification(category="GENERAL", documents_meant_to_be_attached=False, reason="ok")

    monkeypatch.setattr(run_classify, "classify", flaky)
    emails = [{"email_id": f"email_{i:03d}"} for i in range(1, 6)]

    result = run_classify.classify_all(emails, workers=2)

    assert len(result) == 5, "every email must appear, even the failed one"
    assert result["email_003"]["error"] is not None
    assert "boom" in result["email_003"]["error"]
    assert result["email_003"]["category"] == "GENERAL", "failed emails fall back"
    assert result["email_004"]["category"] == "GENERAL"


def test_select_by_ids_or_limit():
    emails = [{"email_id": f"email_{i:03d}"} for i in range(1, 6)]
    assert [e["email_id"] for e in run_classify.select(emails, only="email_004, email_002")] \
        == ["email_002", "email_004"]
    assert len(run_classify.select(emails, limit=2)) == 2
    assert len(run_classify.select(emails)) == 5


def test_partial_runs_update_instead_of_wiping(tmp_path, monkeypatch):
    """--only / --limit must merge into categories.json, not replace it."""
    monkeypatch.setattr(run_classify, "OUT_DIR", tmp_path)
    (tmp_path / "categories.json").write_text(
        '{"email_001": {"category": "SPAM"}, "email_002": {"category": "GENERAL"}}',
        encoding="utf-8")
    merged = run_classify.merge_with_previous({"email_002": {"category": "BL_COMPARISON"}}, partial=True)
    assert merged == {"email_001": {"category": "SPAM"}, "email_002": {"category": "BL_COMPARISON"}}
    assert run_classify.merge_with_previous({"email_002": {"category": "X"}}, partial=False) \
        == {"email_002": {"category": "X"}}
