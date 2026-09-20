import json
from pathlib import Path

import pytest

from sdoc import inbox
from sdoc.mail import store
from sdoc.pipeline import _assign


def test_ids_start_at_one_and_count_up(tmp_path):
    assert store.next_id(tmp_path) == "mail_0001"
    store.save_email("a@b.com", "s", "b", [], root=tmp_path)
    assert store.next_id(tmp_path) == "mail_0002"


def test_saved_email_has_the_same_shape_as_a_bundle_email(tmp_path):
    email = store.save_email("docs@shipper.sg", "Check this BL", "Hi,\nPlease check.",
                             [("SI.txt", b"SHIPPER: ACME")], root=tmp_path)
    assert email["email_id"] == "mail_0001"
    assert email["from"] == "docs@shipper.sg"
    assert email["subject"] == "Check this BL"
    assert email["attachments"] == ["mail/attachments/mail_0001__SI.txt"]
    on_disk = json.loads((tmp_path / "inbox" / "mail_0001.json").read_text(encoding="utf-8"))
    assert on_disk == email


def test_attachment_bytes_are_written_unchanged(tmp_path):
    store.save_email("a@b.com", "s", "b", [("BL.txt", b"BILL OF LADING")], root=tmp_path)
    assert (tmp_path / "attachments" / "mail_0001__BL.txt").read_bytes() == b"BILL OF LADING"


def test_a_senders_filename_cannot_escape_the_attachments_folder(tmp_path):
    email = store.save_email("a@b.com", "s", "b",
                             [("../../../etc/passwd", b"x"),
                              ("C:\\Windows\\System32\\evil.txt", b"y")], root=tmp_path)
    assert email["attachments"] == ["mail/attachments/mail_0001__passwd",
                                    "mail/attachments/mail_0001__evil.txt"]
    assert sorted(p.name for p in (tmp_path / "attachments").iterdir()) == [
        "mail_0001__evil.txt", "mail_0001__passwd"]


def test_odd_characters_in_a_filename_are_replaced(tmp_path):
    email = store.save_email("a@b.com", "s", "b", [("my SI (final).txt", b"x")], root=tmp_path)
    assert email["attachments"] == ["mail/attachments/mail_0001__my_SI_final_.txt"]


def test_the_prefix_keeps_si_and_bl_recognisable_to_the_pipeline(tmp_path):
    """pipeline._assign looks for `_SI.` / `_BL.`; the `__` prefix supplies it."""
    email = store.save_email("a@b.com", "s", "b",
                             [("SI.txt", b"x"), ("BL.txt", b"y")], root=tmp_path)
    si, bl = _assign(email["attachments"])
    assert si == "mail/attachments/mail_0001__SI.txt"
    assert bl == "mail/attachments/mail_0001__BL.txt"


@pytest.fixture
def mail_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "MAIL_DIR", tmp_path)
    return tmp_path


def test_load_received_is_empty_before_anything_arrives(mail_dir):
    assert inbox.load_received() == []


def test_load_received_returns_saved_mail_in_order(mail_dir):
    store.save_email("a@b.com", "first", "b", [], root=mail_dir)
    store.save_email("c@d.com", "second", "b", [], root=mail_dir)
    assert [e["subject"] for e in inbox.load_received()] == ["first", "second"]


def test_load_all_emails_is_the_bundle_plus_what_arrived(mail_dir):
    bundle = inbox.load_emails()
    store.save_email("a@b.com", "new", "b", [], root=mail_dir)
    everything = inbox.load_all_emails()
    assert len(everything) == len(bundle) + 1
    assert everything[-1]["email_id"] == "mail_0001"
    # load_emails stays bundle-only: submission.json depends on it
    assert len(inbox.load_emails()) == len(bundle)


def test_mail_attachments_resolve_to_the_mail_folder(mail_dir):
    store.save_email("a@b.com", "s", "b", [("SI.txt", b"hello")], root=mail_dir)
    assert inbox.read_attachment_bytes("mail/attachments/mail_0001__SI.txt") == b"hello"


def test_bundle_attachments_still_resolve_to_the_bundle(mail_dir):
    assert inbox.attachment_path("attachments/email_004_SI.txt") == (
        Path(inbox.BUNDLE_DIR) / "attachments" / "email_004_SI.txt")
