import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.web import app as web
from sdoc.web import auth

PASSWORD = "a-good-long-password"
EMAIL = "clerk@shipper.com"


@pytest.fixture
def site(tmp_path, monkeypatch):
    out, mail = tmp_path / "out", tmp_path / "mail"
    out.mkdir()
    monkeypatch.setattr(web, "OUT_DIR", out)
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)
    monkeypatch.setattr(auth, "OUT_DIR", out)
    monkeypatch.setenv("SDOC_MAIL_USER", "hackathon3in1@gmail.com")
    auth.create_user(EMAIL, PASSWORD, out_dir=out)

    checked, sent = [], []
    # The real ingest calls Claude and the real send opens an SMTP socket.
    monkeypatch.setattr(web, "ingest", lambda email, out_dir=None: checked.append(email))
    monkeypatch.setattr(web, "send_mail",
                        lambda to, subject, body, attachments: sent.append(
                            (to, subject, body, attachments)))
    client = TestClient(web.app)
    client.post("/login", data={"email": EMAIL, "password": PASSWORD},
                follow_redirects=False)
    return client, mail, checked, sent


def post(client, **over):
    data = {"to": "ops@shipper.com", "subject": "Draft BL for confirmation",
            "body": "Please confirm."}
    data.update(over)
    return client.post("/compose", data=data, follow_redirects=False,
                       files=over.pop("files", None))


def test_the_form_asks_who_it_is_going_to(site):
    client, _, _, _ = site
    html = client.get("/compose").text
    for field in ('name="to"', 'name="subject"', 'name="body"', 'name="files"'):
        assert field in html
    assert 'name="sender"' not in html      # it sends now; it does not pretend
    assert 'name="token"' not in html       # a session replaced the passphrase


def test_the_page_says_which_account_it_sends_from(site):
    client, _, _, _ = site
    assert "hackathon3in1@gmail.com" in client.get("/compose").text


def test_sending_checks_the_documents_then_sends_and_opens_the_result(site):
    client, mail, checked, sent = site
    r = client.post("/compose", data={
        "to": "ops@shipper.com", "subject": "Draft BL", "body": "Attached."},
        files=[("files", ("SI.txt", b"SHIPPER: ACME", "text/plain")),
               ("files", ("BL.txt", b"SHIPPER: ACME CORP", "text/plain"))],
        follow_redirects=False)

    assert r.status_code == 303
    assert r.headers["location"] == "/email/mail_0001"
    # checked before it left
    assert [e["email_id"] for e in checked] == ["mail_0001"]
    assert [s[0] for s in sent] == ["ops@shipper.com"]
    assert (mail / "attachments" / "mail_0001__SI.txt").read_bytes() == b"SHIPPER: ACME"


def test_a_sent_email_records_its_recipient_and_direction(site):
    client, _, _, _ = site
    post(client)
    stored = inbox.load_received()[0]
    assert stored["to"] == "ops@shipper.com"
    assert stored["direction"] == "sent"
    assert stored["from"] == "hackathon3in1@gmail.com"


def test_the_inbox_shows_who_a_sent_email_went_to(site):
    client, _, _, _ = site
    post(client)
    html = client.get("/").text
    assert "ops@shipper.com" in html
    assert ">TO<" in html


def test_a_signed_out_visitor_cannot_send(site):
    """An unlocked send form on a public URL is an open relay."""
    client, _, checked, sent = site
    client.post("/logout", follow_redirects=False)
    r = post(client)
    assert r.status_code == 401
    assert sent == [] and checked == []
    assert inbox.load_received() == []       # and nothing is stored either


def test_a_signed_out_visitor_is_invited_to_sign_in(site):
    client, _, _, _ = site
    client.post("/logout", follow_redirects=False)
    html = client.get("/compose").text
    assert "/login?next=/compose" in html
    assert "disabled" in html


def test_a_signed_out_visitor_can_still_read_everything(site):
    """A judge given the link must never meet a wall."""
    client, _, _, _ = site
    client.post("/logout", follow_redirects=False)
    for path in ("/", "/dashboard", "/email/email_043", "/?status=MISMATCH"):
        assert client.get(path).status_code == 200, path


def test_a_bad_recipient_address_is_refused(site):
    client, _, _, sent = site
    for bad in ("", "   ", "ops", "ops@", "@shipper.com"):
        r = post(client, to=bad)
        assert r.status_code == 400, bad
    assert sent == []


def test_a_blank_subject_is_refused(site):
    client, _, _, sent = site
    assert post(client, subject="  ").status_code == 400
    assert sent == []


def test_too_many_attachments_are_refused(site):
    client, _, _, sent = site
    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(6)]
    r = client.post("/compose", data={"to": "a@b.com", "subject": "s", "body": "b"},
                    files=files, follow_redirects=False)
    assert r.status_code == 400 and "at most" in r.json()["detail"]
    assert sent == []


def test_an_oversized_attachment_is_refused(site):
    client, _, _, sent = site
    big = b"x" * (web.MAX_ATTACHMENT_BYTES + 1)
    r = client.post("/compose", data={"to": "a@b.com", "subject": "s", "body": "b"},
                    files=[("files", ("big.txt", big, "text/plain"))],
                    follow_redirects=False)
    assert r.status_code == 400 and "too large" in r.json()["detail"]
    assert sent == []


def test_the_rail_links_to_the_form(site):
    client, _, _, _ = site
    assert 'href="/compose"' in client.get("/").text


def test_the_header_names_the_account_the_queue_is_fed_from(site):
    client, _, _, _ = site
    assert 'class="acct"' in client.get("/").text
