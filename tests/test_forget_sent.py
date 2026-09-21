"""Mail sent from the app used to be stored and shown in the Triage Queue as
TO rows. Sending no longer stores anything, and the old sent records are
deleted - files, attachments, results and review decisions - at startup,
which is how the deploy gets rid of the ones already on its volume."""
import json

import pytest
from fastapi.testclient import TestClient

from sdoc import ingest
from sdoc.mail import store
from sdoc.web import app as web


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    mail, out = tmp_path / "mail", tmp_path / "out"
    out.mkdir()
    received = store.save_email("a@x.com", "Received", "body", [("SI.txt", b"x")], root=mail)
    # An old sent record, written the way the app used to write them.
    (mail / "attachments" / "mail_0002__BL.txt").write_bytes(b"y")
    (mail / "inbox" / "mail_0002.json").write_text(json.dumps({
        "email_id": "mail_0002", "from": "hackathon3in1@gmail.com", "subject": "Out", "body": "",
        "attachments": ["mail/attachments/mail_0002__BL.txt"], "to": "ops@x.com",
        "direction": "sent", "received_at": "2026-09-21T10:00:00+00:00"}), encoding="utf-8")
    ingest.save_mail_results({"mail_0001": {"category": "SPAM"},
                              "mail_0002": {"category": "BL_COMPARISON", "sent": True}}, out)
    (out / "review.json").write_text(json.dumps({"mail_0002": {"decision": "verified"}}))
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(web, "OUT_DIR", out)
    return mail, out, received


def test_old_sent_mail_is_deleted_for_good_and_received_mail_is_kept(mailbox):
    mail, out, received = mailbox
    assert web.forget_sent_mail() == ["mail_0002"]
    assert not (mail / "inbox" / "mail_0002.json").exists()
    assert not (mail / "attachments" / "mail_0002__BL.txt").exists()
    assert (mail / "inbox" / "mail_0001.json").exists()
    assert (mail / "attachments" / "mail_0001__SI.txt").exists()
    assert list(ingest.load_mail_results(out)) == ["mail_0001"]
    assert json.loads((out / "review.json").read_text()) == {}
    assert web.forget_sent_mail() == []        # it runs at every start; nothing the second time


def test_the_deploy_deletes_them_when_it_starts(mailbox):
    mail, _, _ = mailbox
    with TestClient(web.app):                  # startup runs here
        pass
    assert not (mail / "inbox" / "mail_0002.json").exists()
    assert (mail / "inbox" / "mail_0001.json").exists()


def test_a_received_email_is_stored_without_the_old_sending_fields():
    """Only received mail is stored now, so nothing records a direction."""
    import tempfile
    from pathlib import Path
    email = store.save_email("a@x.com", "Hi", "b", [], root=Path(tempfile.mkdtemp()))
    assert set(email) == {"email_id", "from", "subject", "body", "attachments", "received_at"}
