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
