import pytest

from sdoc.mail import send as snd


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("SDOC_MAIL_USER", "hackathon3in1@gmail.com")
    monkeypatch.setenv("SDOC_MAIL_PASSWORD", "app-password")


def test_sending_is_off_until_a_token_is_configured(monkeypatch):
    """The app is on a public URL; an unlocked send form is an open relay."""
    monkeypatch.delenv("SDOC_SEND_TOKEN", raising=False)
    assert snd.sending_enabled() is False
    assert snd.token_ok("") is False
    assert snd.token_ok("anything") is False


def test_only_the_configured_token_is_accepted(monkeypatch):
    monkeypatch.setenv("SDOC_SEND_TOKEN", "open sesame")
    assert snd.token_ok("open sesame") is True
    assert snd.token_ok("Open Sesame") is False
    assert snd.token_ok("") is False


def test_obvious_address_mistakes_are_caught():
    assert snd.valid_address("ops@shipper.com")
    for bad in ("", "   ", "ops", "ops@", "@shipper.com", "ops shipper.com", "a@b"):
        assert not snd.valid_address(bad), bad


def test_the_message_is_addressed_from_the_watched_account():
    sent = []
    msg = snd.send("ops@shipper.com", "Draft BL", "Please see attached.", [],
                   transport=sent.append)
    assert msg["From"] == "hackathon3in1@gmail.com"
    assert msg["To"] == "ops@shipper.com"
    assert msg["Subject"] == "Draft BL"
    assert "Please see attached." in msg.get_content()
    assert sent == [msg]


def test_attachments_keep_their_names_and_bytes():
    msg = snd.send("a@b.com", "s", "b",
                   [("SI.txt", b"SHIPPER: ACME"), ("BL.pdf", b"%PDF-1.4")],
                   transport=lambda m: None)
    got = [(p.get_filename(), p.get_payload(decode=True)) for p in msg.iter_attachments()]
    assert got == [("SI.txt", b"SHIPPER: ACME"), ("BL.pdf", b"%PDF-1.4")]


def test_attachment_types_are_derived_from_the_filename():
    msg = snd.send("a@b.com", "s", "b", [("SI.txt", b"x"), ("BL.pdf", b"y")],
                   transport=lambda m: None)
    assert [p.get_content_type() for p in msg.iter_attachments()] == [
        "text/plain", "application/pdf"]


def test_missing_credentials_are_reported_not_swallowed(monkeypatch):
    monkeypatch.delenv("SDOC_MAIL_USER", raising=False)
    with pytest.raises(RuntimeError) as e:
        snd.send("a@b.com", "s", "b", [], transport=lambda m: None)
    assert "SDOC_MAIL_USER" in str(e.value)


# --- reaching the mail server --------------------------------------------

def test_both_gmail_ports_are_tried_before_giving_up(monkeypatch):
    """Some hosts block one port and not the other."""
    tried = []

    class Refuse:
        def __init__(self, host, port, timeout=None):
            tried.append(port)
            raise OSError(101, "Network is unreachable")

    monkeypatch.setattr(snd.smtplib, "SMTP_SSL", Refuse)
    monkeypatch.setattr(snd.smtplib, "SMTP", Refuse)
    with pytest.raises(RuntimeError) as e:
        snd.deliver(snd.build_message("a@b.com", "c@d.com", "s", "b", []),
                    "a@b.com", "pw")
    assert tried == [465, 587]
    assert "block outbound SMTP" in str(e.value)
    assert "Network is unreachable" in str(e.value)


def test_the_second_port_is_used_when_the_first_is_blocked(monkeypatch):
    used = []

    class Blocked:
        def __init__(self, host, port, timeout=None):
            raise OSError(101, "Network is unreachable")

    class Works:
        def __init__(self, host, port, timeout=None):
            used.append(port)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, u, p): pass
        def send_message(self, m): used.append("sent")

    monkeypatch.setattr(snd.smtplib, "SMTP_SSL", Blocked)
    monkeypatch.setattr(snd.smtplib, "SMTP", Works)
    assert snd.deliver(snd.build_message("a@b.com", "c@d.com", "s", "b", []),
                       "a@b.com", "pw") == 587
    assert used == [587, "sent"]


def test_a_blocked_route_fails_fast_rather_than_hanging():
    """No timeout means smtplib waits forever, which reads as the app hanging."""
    assert snd.TIMEOUT > 0


# --- HTTP provider takes over when one is configured ---------------------

def test_an_http_provider_is_used_instead_of_smtp(monkeypatch):
    """Port 443 is what makes sending work where SMTP is blocked."""
    monkeypatch.setenv("SDOC_BREVO_KEY", "secret")
    used = {}
    monkeypatch.setattr(snd, "send_via_api",
                        lambda s, to, subj, body, att: used.setdefault("api", to))
    monkeypatch.setattr(snd, "deliver",
                        lambda *a: used.setdefault("smtp", True))

    snd.send("ops@shipper.com", "Draft BL", "body", [])
    assert used == {"api": "ops@shipper.com"}      # smtp was never tried


def test_smtp_is_still_used_when_no_provider_is_configured(monkeypatch):
    monkeypatch.delenv("SDOC_BREVO_KEY", raising=False)
    monkeypatch.delenv("SDOC_SENDGRID_KEY", raising=False)
    used = {}
    monkeypatch.setattr(snd, "deliver", lambda *a: used.setdefault("smtp", True))
    snd.send("ops@shipper.com", "Draft BL", "body", [])
    assert used == {"smtp": True}


def test_a_configured_provider_means_mail_can_always_leave(monkeypatch):
    """No socket probe needed: 443 is open everywhere or nothing works."""
    monkeypatch.setenv("SDOC_BREVO_KEY", "secret")
    monkeypatch.setattr(snd, "_REACHABLE", False)   # SMTP was found blocked
    assert snd.reachable() is True
    assert snd.probe(timeout=0.01) is True
