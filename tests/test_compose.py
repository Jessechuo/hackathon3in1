import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.web import app as web

TOKEN = "open sesame"


@pytest.fixture
def site(tmp_path, monkeypatch):
    out, mail = tmp_path / "out", tmp_path / "mail"
    out.mkdir()
    monkeypatch.setattr(web, "OUT_DIR", out)
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)
    monkeypatch.setenv("SDOC_SEND_TOKEN", TOKEN)
    monkeypatch.setenv("SDOC_MAIL_USER", "hackathon3in1@gmail.com")

    checked, sent = [], []
    # The real ingest calls Claude and the real send opens an SMTP socket.
    monkeypatch.setattr(web, "ingest", lambda email, out_dir=None: checked.append(email))
    monkeypatch.setattr(web, "send_mail",
                        lambda to, subject, body, attachments: sent.append(
                            (to, subject, body, attachments)))
    return TestClient(web.app), mail, checked, sent


def post(client, **over):
    data = {"to": "ops@shipper.com", "subject": "Draft BL for confirmation",
            "body": "Please confirm.", "token": TOKEN}
    data.update(over)
    return client.post("/compose", data=data, follow_redirects=False,
                       files=over.pop("files", None))


def test_the_form_asks_who_it_is_going_to(site):
    client, _, _, _ = site
    html = client.get("/compose").text
    for field in ('name="to"', 'name="subject"', 'name="body"',
                  'name="files"', 'name="token"'):
        assert field in html
    assert 'name="sender"' not in html      # it sends now; it does not pretend


def test_the_page_says_which_account_it_sends_from(site):
    client, _, _, _ = site
    assert "hackathon3in1@gmail.com" in client.get("/compose").text


def test_sending_checks_the_documents_then_sends_and_opens_the_result(site):
    client, mail, checked, sent = site
    r = client.post("/compose", data={
        "to": "ops@shipper.com", "subject": "Draft BL", "body": "Attached.",
        "token": TOKEN},
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


def test_nothing_is_sent_without_the_passphrase(site):
    client, _, checked, sent = site
    r = post(client, token="wrong")
    assert r.status_code == 403
    assert sent == [] and checked == []
    assert inbox.load_received() == []       # and nothing is stored either


def test_sending_is_refused_outright_when_no_passphrase_is_configured(site, monkeypatch):
    """An unlocked send form on a public URL is an open relay."""
    client, _, _, sent = site
    monkeypatch.delenv("SDOC_SEND_TOKEN", raising=False)
    r = post(client, token="")
    assert r.status_code == 503
    assert "SDOC_SEND_TOKEN" in r.json()["detail"]
    assert sent == []


def test_the_page_says_so_when_sending_is_off(site, monkeypatch):
    client, _, _, _ = site
    monkeypatch.delenv("SDOC_SEND_TOKEN", raising=False)
    html = client.get("/compose").text
    assert "Sending is turned off" in html
    assert "disabled" in html


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
    r = client.post("/compose", data={"to": "a@b.com", "subject": "s", "body": "b",
                                      "token": TOKEN},
                    files=files, follow_redirects=False)
    assert r.status_code == 400 and "at most" in r.json()["detail"]
    assert sent == []


def test_an_oversized_attachment_is_refused(site):
    client, _, _, sent = site
    big = b"x" * (web.MAX_ATTACHMENT_BYTES + 1)
    r = client.post("/compose", data={"to": "a@b.com", "subject": "s", "body": "b",
                                      "token": TOKEN},
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
