import json

import pytest

from sdoc import ingest as ing
from sdoc.ai.classify import Classification

EMAIL = {"email_id": "mail_0001", "from": "a@b.com", "subject": "Check this BL",
         "body": "Please compare the attached.", "attachments": []}


def fake_classification(category="BL_COMPARISON", attached=False):
    return Classification(category=category, documents_meant_to_be_attached=attached,
                          reason="test")


def test_a_received_email_is_classified_and_compared(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("SPAM"))
    result = ing.ingest(EMAIL, out_dir=tmp_path)
    assert result["category"] == "SPAM"
    assert result["status"] == "OK"


def test_the_result_is_written_where_the_app_can_find_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("GENERAL"))
    ing.ingest(EMAIL, out_dir=tmp_path)
    saved = json.loads((tmp_path / "mail_results.json").read_text(encoding="utf-8"))
    assert saved["mail_0001"]["category"] == "GENERAL"


def test_ingesting_a_second_email_keeps_the_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("GENERAL"))
    ing.ingest(EMAIL, out_dir=tmp_path)
    ing.ingest({**EMAIL, "email_id": "mail_0002"}, out_dir=tmp_path)
    assert sorted(ing.load_mail_results(tmp_path)) == ["mail_0001", "mail_0002"]


def test_a_document_check_with_no_attachments_escalates(tmp_path, monkeypatch):
    """The promise of attachments with none present is the missing_attachment gate."""
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("BL_COMPARISON", True))
    result = ing.ingest(EMAIL, out_dir=tmp_path)
    assert result["status"] == "NEEDS_REVIEW"
    assert result["review_reason"] == "missing_attachment"


def test_a_classification_failure_does_not_take_the_watcher_down(tmp_path, monkeypatch):
    def boom(email):
        raise RuntimeError("api is down")
    monkeypatch.setattr(ing, "classify", boom)
    result = ing.ingest(EMAIL, out_dir=tmp_path)
    assert result["category"] == "GENERAL"
    assert "api is down" in result["error"]


def test_a_processing_failure_is_recorded_as_needing_review(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("BL_COMPARISON"))

    def boom(email, cls):
        raise RuntimeError("pdf exploded")
    monkeypatch.setattr(ing, "process", boom)
    result = ing.ingest(EMAIL, out_dir=tmp_path)
    assert result["status"] == "NEEDS_REVIEW"
    assert result["failed"] is True
    assert "pdf exploded" in result["error"]


def test_no_results_file_yet_is_not_an_error(tmp_path):
    assert ing.load_mail_results(tmp_path) == {}
