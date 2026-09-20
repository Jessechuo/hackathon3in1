import threading

import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.web import app as web
from sdoc.web import auth

PASSWORD = "Operator-2026!x"
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
    auth.create_user(EMAIL, PASSWORD, out_dir=out, name="Test Clerk")

    checked, sent = [], []

    # The real ingest calls Claude and the real send opens an SMTP socket.
    # The stand-in still writes a finished result, because that is what
    # clears the pending flag the page is waiting on.
    def fake_ingest(email, out_dir=None):
        checked.append(email)
        from sdoc.ingest import update_result
        return update_result(email["email_id"], out_dir, pending=False,
                             category="BL_COMPARISON", status="OK", fields=[],
                             defect_fields=[], has_defect=False, note=None)

    monkeypatch.setattr(web, "ingest", fake_ingest)
    monkeypatch.setattr(web, "send_mail",
                        lambda to, subject, body, attachments: sent.append(
                            (to, subject, body, attachments)))
    client = TestClient(web.app)
    client.post("/login", data={"email": EMAIL, "password": PASSWORD},
                follow_redirects=False)
    return client, mail, checked, sent


def settle(timeout=5):
    """Wait for the background check-and-send thread to finish."""
    for thread in threading.enumerate():
        if thread.name.startswith("send-"):
            thread.join(timeout=timeout)


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
    settle()
    # checked before it left
    assert [e["email_id"] for e in checked] == ["mail_0001"]
    assert [s[0] for s in sent] == ["ops@shipper.com"]
    assert (mail / "attachments" / "mail_0001__SI.txt").read_bytes() == b"SHIPPER: ACME"


def test_a_sent_email_records_its_recipient_and_direction(site):
    client, _, _, _ = site
    post(client)
    settle()
    stored = inbox.load_received()[0]
    assert stored["to"] == "ops@shipper.com"
    assert stored["direction"] == "sent"
    assert stored["from"] == "hackathon3in1@gmail.com"


def test_the_inbox_shows_who_a_sent_email_went_to(site):
    client, _, _, _ = site
    post(client)
    settle()
    html = client.get("/").text
    assert "ops@shipper.com" in html
    assert ">TO<" in html


def test_a_signed_out_visitor_cannot_send(site):
    """An unlocked send form on a public URL is an open relay."""
    client, _, checked, sent = site
    client.post("/logout", follow_redirects=False)
    r = post(client)
    settle()
    assert r.status_code == 401
    assert sent == [] and checked == []
    assert inbox.load_received() == []       # and nothing is stored either


def test_a_signed_out_visitor_is_invited_to_sign_in(site):
    client, _, _, _ = site
    client.post("/logout", follow_redirects=False)
    html = client.get("/compose").text
    assert "/login?next=/compose" in html
    assert "disabled" in html


def test_reading_can_be_opened_up_for_a_deployment_that_wants_that(site, monkeypatch):
    """SDOC_REQUIRE_LOGIN=0 hands out a link instead of credentials."""
    client, _, _, _ = site
    client.post("/logout", follow_redirects=False)
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "0")
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


# --- the slow half runs off the request ----------------------------------

def test_the_page_comes_back_before_the_work_is_done(site, monkeypatch):
    """Reading two documents and opening SMTP together take ~30s. Doing that
    before responding left a person watching a spinner."""
    client, _, _, _ = site
    started, release = threading.Event(), threading.Event()

    def slow_ingest(email, out_dir=None):
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(web, "ingest", slow_ingest)
    r = post(client)                       # returns while slow_ingest is blocked
    assert r.status_code == 303
    assert started.wait(timeout=5), "the background work never started"
    release.set()
    settle()


def test_the_email_has_a_page_to_open_while_the_work_runs(site, monkeypatch):
    client, out, _, _ = site
    release = threading.Event()
    monkeypatch.setattr(web, "ingest",
                        lambda email, out_dir=None: release.wait(timeout=5))
    post(client)

    page = client.get("/email/mail_0001").text
    assert "Checking the documents" in page
    assert "location.reload" in page        # it comes back for the result
    release.set()
    settle()


def test_a_successful_send_is_recorded(site):
    client, _, _, _ = site
    post(client)
    settle()
    from sdoc.ingest import load_mail_results
    result = load_mail_results(web.OUT_DIR)["mail_0001"]
    assert result["sent"] is True
    assert result["pending"] is False
    assert result["sent_at"]
    assert "Checked and sent" in client.get("/email/mail_0001").text


def test_a_failed_send_is_reported_and_the_check_is_kept(site, monkeypatch):
    client, _, checked, _ = site

    def refuse(to, subject, body, attachments):
        raise OSError("smtp is unreachable")

    monkeypatch.setattr(web, "send_mail", refuse)
    post(client)
    settle()

    from sdoc.ingest import load_mail_results
    result = load_mail_results(web.OUT_DIR)["mail_0001"]
    assert result["sent"] is False
    assert "smtp is unreachable" in result["send_error"]
    assert [e["email_id"] for e in checked] == ["mail_0001"]   # the check still ran
    assert "could not be sent" in client.get("/email/mail_0001").text


# --- the header carries an initial, not an address -----------------------

def test_the_header_shows_an_initial_rather_than_the_whole_address(site):
    client, _, _, _ = site
    html = client.get("/").text
    assert 'class="avatar"' in html
    assert ">T<" in html                    # "Test Clerk"
    assert 'id="acct-pop"' in html          # the menu behind it
    assert "Sign out" in html               # inside the menu


def test_the_menu_carries_the_name_and_address_it_replaced(site):
    client, _, _, _ = site
    html = client.get("/").text
    assert "Test Clerk" in html and EMAIL in html


# --- attaching more than one file ----------------------------------------

def test_the_file_input_accepts_several_files(site):
    client, _, _, _ = site
    html = client.get("/compose").text
    assert 'id="files"' in html and "multiple" in html


def test_files_accumulate_across_picks_rather_than_replacing(site):
    """A plain file input replaces its whole selection every time it is used,
    which reads as 'I can only attach one file'."""
    client, _, _, _ = site
    html = client.get("/compose").text
    assert "DataTransfer" in html          # the basket that makes them add up
    assert 'id="file-list"' in html        # and it is shown back to the person


def test_two_attachments_both_reach_the_pipeline(site):
    client, mail, checked, _ = site
    client.post("/compose",
                data={"to": "ops@shipper.com", "subject": "Draft BL", "body": "b"},
                files=[("files", ("SI.txt", b"SHIPPER: ACME", "text/plain")),
                       ("files", ("BL.txt", b"SHIPPER: ACME CORP", "text/plain"))],
                follow_redirects=False)
    settle()
    assert checked[0]["attachments"] == ["mail/attachments/mail_0001__SI.txt",
                                         "mail/attachments/mail_0001__BL.txt"]
    assert (mail / "attachments" / "mail_0001__BL.txt").exists()


def test_the_limits_shown_match_the_ones_enforced(site):
    client, _, _, _ = site
    html = client.get("/compose").text
    assert f"MAX_FILES = {web.MAX_ATTACHMENTS}" in html
    assert f"{web.MAX_ATTACHMENT_BYTES // 1024 // 1024} * 1024 * 1024" in html
