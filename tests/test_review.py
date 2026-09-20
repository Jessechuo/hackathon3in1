"""Human review: a person's decision becomes the final word in the app.

The brief: 'Let a person confirm or correct it, then update the report.'
Before this, Mark Verified / Flag Mismatch were saved but nothing read them.
submission.json deliberately stays the system's own answers.
"""
import json

import pytest
from fastapi.testclient import TestClient

from sdoc import review
from sdoc.web import app as web

MISMATCH = {"category": "BL_COMPARISON", "status": "MISMATCH", "review_reason": None,
            "has_defect": True, "defect_fields": ["container_count"], "fields": [], "note": None}
UNREADABLE = {"category": "BL_COMPARISON", "status": "NEEDS_REVIEW", "review_reason": "unreadable",
              "has_defect": False, "defect_fields": [], "fields": [], "note": "scan"}
INVOICE = {"category": "INVOICE_QUERY", "status": "OK", "defect_fields": []}


# ── the rule itself ─────────────────────────────────────────────────────

def test_no_decision_means_the_system_answer_stands():
    e = review.effective(MISMATCH, None)
    assert (e["status"], e["defect_fields"], e["reviewed"]) == ("MISMATCH", ["container_count"], False)


def test_verified_overrules_a_false_alarm():
    e = review.effective(MISMATCH, {"decision": "verified", "at": "t"})
    assert (e["status"], e["defect_fields"], e["has_defect"]) == ("OK", [], False)
    assert e["reviewed"] and e["reviewer_changed"]
    assert e["system_status"] == "MISMATCH"


def test_flagging_resolves_a_review_case_with_the_reviewers_fields():
    e = review.effective(UNREADABLE, {"decision": "mismatch", "fields": ["shipper"], "at": "t"})
    assert (e["status"], e["defect_fields"], e["review_reason"]) == ("MISMATCH", ["shipper"], None)
    assert e["system_status"] == "NEEDS_REVIEW"


def test_confirming_the_system_is_reviewed_but_not_changed():
    e = review.effective(MISMATCH, {"decision": "mismatch", "fields": ["container_count"], "at": "t"})
    assert e["reviewed"] and not e["reviewer_changed"]


def test_decisions_on_non_document_emails_are_ignored():
    e = review.effective(INVOICE, {"decision": "verified", "at": "t"})
    assert not e["reviewed"] and e["status"] == "OK"


# ── the app ─────────────────────────────────────────────────────────────

@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUT_DIR", tmp_path)
    results = {"email_043": MISMATCH, "email_512": UNREADABLE, "email_002": INVOICE}
    (tmp_path / "results.json").write_text(json.dumps(results), encoding="utf-8")
    return TestClient(web.app), tmp_path


def post(client, eid, payload):
    return client.post(f"/review/{eid}", json=payload)


def test_verified_moves_an_email_out_of_mismatches(site):
    client, _ = site
    assert post(client, "email_043", {"decision": "verified"}).status_code == 200
    assert 'data-id="email_043"' not in client.get("/?status=MISMATCH").text
    assert 'data-id="email_043"' in client.get("/?status=OK").text


def test_a_decided_case_leaves_the_review_queue_and_shows_as_reviewed(site):
    client, _ = site
    assert 'data-id="email_512"' in client.get("/?status=NEEDS_REVIEW").text
    post(client, "email_512", {"decision": "mismatch", "fields": ["consignee"]})
    assert 'data-id="email_512"' not in client.get("/?status=NEEDS_REVIEW").text
    assert 'data-id="email_512"' in client.get("/?reviewed=1").text


def test_mismatch_needs_at_least_one_real_field(site):
    client, _ = site
    assert post(client, "email_043", {"decision": "mismatch", "fields": []}).status_code == 400
    assert post(client, "email_043", {"decision": "mismatch", "fields": ["colour"]}).status_code == 400


def test_non_document_emails_cannot_be_reviewed(site):
    client, _ = site
    assert post(client, "email_002", {"decision": "verified"}).status_code == 400


def test_clearing_restores_the_system_answer(site):
    client, tmp = site
    post(client, "email_043", {"decision": "verified"})
    post(client, "email_043", {"decision": None})
    assert json.loads((tmp / "review.json").read_text(encoding="utf-8")) == {}
    assert 'data-id="email_043"' in client.get("/?status=MISMATCH").text


def test_review_buttons_only_on_document_emails(site):
    client, _ = site
    assert "Mark Verified" not in client.get("/email/email_002").text
    page = client.get("/email/email_043").text
    assert "Mark Verified" in page
    # the tick list starts with the system's findings ticked
    assert 'value="container_count" checked' in page


def test_submission_is_never_touched_by_reviews(site):
    client, tmp = site
    post(client, "email_043", {"decision": "verified"})
    assert not (tmp / "submission.json").exists()
