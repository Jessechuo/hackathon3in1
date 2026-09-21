import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.ingest import load_mail_results
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

    sent, sent_kwargs = [], []

    # The real send talks to Gmail.
    def fake_send(to, subject, body, attachments, **kwargs):
        sent.append((to, subject, body, attachments))
        sent_kwargs.append(kwargs)

    monkeypatch.setattr(web, "send_mail", fake_send)
    client = TestClient(web.app)
    client.post("/login", data={"email": EMAIL, "password": PASSWORD},
                follow_redirects=False)
    client.sent_kwargs = sent_kwargs       # what the send was told about its sender
    return client, mail, out, sent


def post(client, **over):
    files = over.pop("files", None)
    data = {"to": "ops@shipper.com", "subject": "Draft BL for confirmation",
            "body": "Please confirm."}
    data.update(over)
    return client.post("/compose", data=data, follow_redirects=False, files=files)


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


# --- sending: straight out, nothing kept ----------------------------------

def test_sending_sends_straight_away_with_its_attachments(site):
    client, _, _, sent = site
    r = client.post("/compose", data={
        "to": "ops@shipper.com", "subject": "Draft BL", "body": "Attached."},
        files=[("files", ("SI.txt", b"SHIPPER: ACME", "text/plain")),
               ("files", ("BL.txt", b"SHIPPER: ACME CORP", "text/plain"))],
        follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/compose"
    assert sent == [("ops@shipper.com", "Draft BL", "Attached.",
                     [("SI.txt", b"SHIPPER: ACME"), ("BL.txt", b"SHIPPER: ACME CORP")])]


def test_sent_mail_is_not_stored_or_checked(site):
    """The Triage Queue is for mail that arrives. Mail sent from here is
    neither saved nor run through the AI."""
    client, mail, out, _ = site
    post(client, files=[("files", ("SI.txt", b"x", "text/plain"))])
    assert inbox.load_received() == []
    assert not (mail / "attachments").exists()
    assert load_mail_results(out) == {}
    assert "ops@shipper.com" not in client.get("/").text


def test_the_send_page_confirms_it_went(site):
    client, _, _, _ = site
    assert post(client).status_code == 303
    assert "Sent to <b>ops@shipper.com</b>." in client.get("/compose").text
    assert "Sent to" not in client.get("/compose").text        # said once, not on every visit


def test_a_failed_send_shows_the_error_and_keeps_what_was_typed(site, monkeypatch):
    client, mail, _, _ = site

    def refuse(to, subject, body, attachments, **kwargs):
        raise OSError("Gmail refused the message")

    monkeypatch.setattr(web, "send_mail", refuse)
    r = post(client, subject="Draft BL - PO 7788", body="Please check.")
    assert r.status_code == 502
    flat = " ".join(r.text.split())
    assert "Gmail refused the message" in flat
    assert 'value="ops@shipper.com"' in r.text and 'value="Draft BL - PO 7788"' in r.text
    assert ">Please check.</textarea>" in r.text
    assert inbox.load_received() == []                            # still nothing kept


def test_the_send_is_named_for_the_person_and_replies_go_to_them(site):
    client, _, _, _ = site
    post(client)
    assert client.sent_kwargs[-1] == {"reply_to": EMAIL, "sender_name": "Test Clerk"}


def test_the_form_no_longer_promises_a_check(site):
    client, _, _, _ = site
    flat = " ".join(client.get("/compose").text.split())
    assert "Check and send" not in flat and "costs about 2 cents" not in flat
    assert ">Send<" in flat.replace(" <", "<").replace("> ", ">")


# --- who may send ---------------------------------------------------------

def test_a_signed_out_visitor_cannot_send(site):
    """An unlocked send form on a public URL is an open relay."""
    client, _, _, sent = site
    client.post("/logout", follow_redirects=False)
    r = post(client)
    assert r.status_code == 401
    assert sent == []


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


# --- what is refused before anything is sent ------------------------------

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
    assert r.status_code == 400 and "at most" in r.json()["detail"].lower()
    assert sent == []


def test_an_oversized_attachment_is_refused(site):
    client, _, _, sent = site
    big = b"x" * (web.MAX_ATTACHMENT_BYTES + 1)
    r = client.post("/compose", data={"to": "a@b.com", "subject": "s", "body": "b"},
                    files=[("files", ("big.txt", big, "text/plain"))],
                    follow_redirects=False)
    assert r.status_code == 400 and "too large" in r.json()["detail"]
    assert sent == []


# --- the page around the form ---------------------------------------------

def test_the_rail_links_to_the_form(site):
    client, _, _, _ = site
    assert 'href="/compose"' in client.get("/").text


def test_the_header_stays_uncluttered(site):
    """The mailbox address in the header crowded the busiest row on the page;
    it is shown where it matters instead, on the page that sends from it."""
    client, _, _, _ = site
    assert 'class="acct"' not in client.get("/").text
    assert "hackathon3in1@gmail.com" in client.get("/compose").text


def test_the_header_carries_no_counts(site):
    """The totals live on the pages that are about them - the inbox's queue
    size, the dashboard's tiles. Repeated in the header they were noise."""
    client, _, _, _ = site
    for path in ("/", "/dashboard", "/compose"):
        header = client.get(path).text.split("<header", 1)[1].split("</header>", 1)[0]
        assert "chip-count" not in header, path
        assert " received<" not in header, path


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


def test_the_address_in_the_menu_is_named_not_a_bare_span(site):
    """It sits next to the avatar, and a bare `span` selector styled both."""
    client, _, _, _ = site
    html = client.get("/").text
    assert 'class="addr"' in html
    assert 'class="avatar lg"' in html


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


def test_the_limits_shown_match_the_ones_enforced(site):
    client, _, _, _ = site
    html = client.get("/compose").text
    assert f"MAX_FILES = {web.MAX_ATTACHMENTS}" in html
    assert f"{web.MAX_ATTACHMENT_BYTES // 1024 // 1024} * 1024 * 1024" in html


# --- when the host will not let mail out ---------------------------------

def test_the_form_says_so_when_the_host_blocks_outbound_mail(site, monkeypatch):
    """Most cloud hosts block SMTP. A judge pressing Send and getting a socket
    error reads as broken; saying so up front reads as understood."""
    from sdoc.mail import send as snd
    client, _, _, _ = site
    monkeypatch.setattr(snd, "_REACHABLE", False)

    html = client.get("/compose").text
    # The template wraps its prose, so compare against collapsed whitespace
    # rather than shaping the sentences around the test.
    flat = " ".join(html.split())
    assert "Sending is unavailable on this host" in flat
    assert "blocks outbound SMTP" in flat
    assert "Receiving is unaffected" in flat     # the part that still works
    assert html.count("disabled") >= 4           # and nothing invites a try


def test_the_form_is_offered_normally_when_mail_can_leave(site, monkeypatch):
    from sdoc.mail import send as snd
    client, _, _, _ = site
    monkeypatch.setattr(snd, "_REACHABLE", True)
    html = client.get("/compose").text
    assert "Sending is unavailable" not in html
    assert 'class="send" type="submit"' in html and "disabled" not in html.split('class="send"', 1)[1][:80]


def test_a_network_failure_turns_the_form_off_by_itself(site, monkeypatch):
    """The probe runs at startup, but a route can also fail later."""
    from sdoc.mail import send as snd
    client, _, _, _ = site
    monkeypatch.setattr(snd, "_REACHABLE", True)

    def unreachable(to, subject, body, attachments, **kwargs):
        raise RuntimeError("could not reach smtp.gmail.com ... Network is unreachable")

    monkeypatch.setattr(web, "send_mail", unreachable)
    post(client)
    assert snd.reachable() is False
    assert "Sending is unavailable on this host" in client.get("/compose").text
