from email.message import EmailMessage

import pytest

from sdoc import inbox
from sdoc import run_watch


def message(subject="Check BL", files=()):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "ops@shipper.com"
    msg.set_content("Please compare the attached.")
    for name, data in files:
        msg.add_attachment(data, maintype="text", subtype="plain", filename=name)
    return msg.as_bytes()


class StubMailbox:
    """Hands out one batch per call, like a mailbox that has been drained."""

    def __init__(self, *batches):
        self.batches = list(batches)
        self.calls = 0

    def fetch_unseen(self, limit=20):
        self.calls += 1
        return self.batches.pop(0) if self.batches else []


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    out, mail = tmp_path / "out", tmp_path / "mail"
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)
    monkeypatch.setattr(run_watch, "ingest",
                        lambda email, out_dir=None: {"category": "BL_COMPARISON",
                                                     "status": "OK",
                                                     "email_id": email["email_id"]})
    return out, mail


def test_nothing_waiting_means_nothing_happens(dirs):
    out, mail = dirs
    assert run_watch.poll_once(StubMailbox(), root=mail, out_dir=out) == []


def test_a_waiting_message_is_stored_and_ingested(dirs):
    out, mail = dirs
    box = StubMailbox([message(files=[("SI.txt", b"SHIPPER: ACME"),
                                      ("BL.txt", b"SHIPPER: ACME CORP")])])
    results = run_watch.poll_once(box, root=mail, out_dir=out)
    assert len(results) == 1
    saved = inbox.load_received()
    assert [e["subject"] for e in saved] == ["Check BL"]
    assert saved[0]["attachments"] == ["mail/attachments/mail_0001__SI.txt",
                                       "mail/attachments/mail_0001__BL.txt"]


def test_two_messages_in_one_batch_get_separate_ids(dirs):
    out, mail = dirs
    box = StubMailbox([message("first"), message("second")])
    run_watch.poll_once(box, root=mail, out_dir=out)
    assert [e["email_id"] for e in inbox.load_received()] == ["mail_0001", "mail_0002"]


def test_one_unparseable_message_does_not_stop_the_rest(dirs, monkeypatch):
    out, mail = dirs
    real = run_watch.parse_message

    def flaky(raw):
        if b"poison" in raw:
            raise ValueError("cannot parse")
        return real(raw)

    monkeypatch.setattr(run_watch, "parse_message", flaky)
    box = StubMailbox([b"poison", message("good")])
    results = run_watch.poll_once(box, root=mail, out_dir=out)
    assert len(results) == 1
    assert [e["subject"] for e in inbox.load_received()] == ["good"]


def test_a_mailbox_needs_a_user_and_a_password(monkeypatch):
    from sdoc.mail.gmail import Mailbox
    monkeypatch.delenv("SDOC_MAIL_USER", raising=False)
    monkeypatch.delenv("SDOC_MAIL_PASSWORD", raising=False)
    with pytest.raises(RuntimeError) as e:
        Mailbox()
    assert "SDOC_MAIL_USER" in str(e.value)
