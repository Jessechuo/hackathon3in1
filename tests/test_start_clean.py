"""Before recording the demo, the deploy is cleared of everything typed in
while testing - received mail, what the AI made of it, reviewer decisions -
so the site shows the organizers' 520 emails and nothing else. It runs once
per tag, when the deploy starts."""
import json

import pytest
from fastapi.testclient import TestClient

from sdoc import inbox, ingest
from sdoc.mail import store
from sdoc.web import app as web
from sdoc.web import auth


@pytest.fixture
def volume(tmp_path, monkeypatch):
    """A deploy's volume, apart from the repo's own out/ and mail/."""
    out, mail = tmp_path / "data" / "out", tmp_path / "data" / "mail"
    out.mkdir(parents=True)
    for name in ("results.json", "categories.json", "submission.json"):
        (out / name).write_text("{}", encoding="utf-8")
    auth.create_user("check@sdoc.test", "Verify-2026!check", out_dir=out, name="Check")
    store.save_email("me@x.com", "Test", "body", [("SI.txt", b"x")], root=mail)
    ingest.save_mail_results({"mail_0001": {"category": "SPAM"}}, out)
    (out / "review.json").write_text(json.dumps({"email_004": {"decision": "verified"}}))
    monkeypatch.setattr(web, "ROOT", tmp_path / "repo")
    monkeypatch.setattr(web, "OUT_DIR", out)
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)
    return out, mail


def test_it_clears_the_test_mail_and_the_decisions(volume):
    out, mail = volume
    assert web.start_clean("take-1") is True
    assert not (mail / "inbox").exists() and not (mail / "attachments").exists()
    assert not (out / "mail_results.json").exists()
    assert not (out / "review.json").exists()
    assert inbox.load_received() == []


def test_it_keeps_the_520_results_and_the_accounts(volume):
    out, _ = volume
    web.start_clean("take-1")
    for name in ("results.json", "categories.json", "submission.json"):
        assert (out / name).exists(), name
    assert auth.authenticate("check@sdoc.test", "Verify-2026!check", out_dir=out)


def test_it_runs_once_so_mail_received_afterwards_stays(volume):
    _, mail = volume
    web.start_clean("take-1")
    store.save_email("judge@x.com", "Recorded", "body", [], root=mail)
    assert web.start_clean("take-1") is False                   # a restart
    assert [e["subject"] for e in inbox.load_received()] == ["Recorded"]


def test_a_new_tag_clears_again(volume):
    _, mail = volume
    web.start_clean("take-1")
    store.save_email("judge@x.com", "Rehearsal", "body", [], root=mail)
    assert web.start_clean("take-2") is True
    assert inbox.load_received() == []


def test_the_repos_own_folders_are_never_cleared(tmp_path, monkeypatch):
    """Locally OUT_DIR and MAIL_DIR are the repo's out/ and mail/."""
    repo = tmp_path / "repo"
    store.save_email("me@x.com", "Local", "body", [], root=repo / "mail")
    (repo / "out").mkdir()
    (repo / "out" / "review.json").write_text("{}")
    monkeypatch.setattr(web, "ROOT", repo)
    monkeypatch.setattr(web, "OUT_DIR", repo / "out")
    monkeypatch.setattr(web, "MAIL_DIR", repo / "mail")
    assert web.start_clean("take-1") is False
    assert (repo / "mail" / "inbox" / "mail_0001.json").exists()
    assert (repo / "out" / "review.json").exists()
    assert not list((repo / "out").glob(".reset-*"))


def test_the_deploy_clears_when_it_starts(volume, monkeypatch):
    _, mail = volume
    monkeypatch.setattr(web, "RESET", "take-1")
    with TestClient(web.app):                  # startup runs here
        pass
    assert not (mail / "inbox").exists()

