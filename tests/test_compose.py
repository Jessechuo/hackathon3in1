import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.web import app as web


@pytest.fixture
def site(tmp_path, monkeypatch):
    out, mail = tmp_path / "out", tmp_path / "mail"
    out.mkdir()
    monkeypatch.setattr(web, "OUT_DIR", out)
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)

    seen = []
    # The real ingest calls Claude. Record the email instead.
    monkeypatch.setattr(web, "ingest", lambda email, out_dir=None: seen.append(email))
    return TestClient(web.app), mail, seen


def test_the_form_asks_for_what_an_email_needs(site):
    client, _, _ = site
    html = client.get("/compose").text
    for field in ('name="sender"', 'name="subject"', 'name="body"', 'name="files"'):
        assert field in html


def test_sending_stores_the_email_and_opens_its_page(site):
    client, mail, seen = site
    r = client.post("/compose", data={
        "sender": "ops@shipper.com", "subject": "Check BL vs SI", "body": "Attached."},
        files=[("files", ("SI.txt", b"SHIPPER: ACME", "text/plain")),
               ("files", ("BL.txt", b"SHIPPER: ACME CORP", "text/plain"))],
        follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/email/mail_0001"
    assert (mail / "attachments" / "mail_0001__SI.txt").read_bytes() == b"SHIPPER: ACME"
    assert [e["email_id"] for e in inbox.load_received()] == ["mail_0001"]


def test_the_new_email_goes_straight_through_the_pipeline(site):
    client, _, seen = site
    client.post("/compose", data={"sender": "a@b.com", "subject": "s", "body": "b"},
                follow_redirects=False)
    assert [e["subject"] for e in seen] == ["s"]


def test_sending_with_no_attachments_is_allowed(site):
    client, _, _ = site
    r = client.post("/compose", data={"sender": "a@b.com", "subject": "s", "body": "b"},
                    follow_redirects=False)
    assert r.status_code == 303


def test_a_blank_sender_or_subject_is_refused(site):
    client, _, _ = site
    for data in ({"sender": "  ", "subject": "s", "body": "b"},
                 {"sender": "a@b.com", "subject": "", "body": "b"}):
        assert client.post("/compose", data=data, follow_redirects=False).status_code == 400


def test_too_many_attachments_are_refused(site):
    client, _, _ = site
    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(6)]
    r = client.post("/compose", data={"sender": "a@b.com", "subject": "s", "body": "b"},
                    files=files, follow_redirects=False)
    assert r.status_code == 400
    assert "at most" in r.json()["detail"]


def test_an_oversized_attachment_is_refused(site):
    client, _, _ = site
    big = b"x" * (web.MAX_ATTACHMENT_BYTES + 1)
    r = client.post("/compose", data={"sender": "a@b.com", "subject": "s", "body": "b"},
                    files=[("files", ("big.txt", big, "text/plain"))], follow_redirects=False)
    assert r.status_code == 400
    assert "too large" in r.json()["detail"]


def test_the_rail_links_to_the_form(site):
    client, _, _ = site
    assert 'href="/compose"' in client.get("/").text
