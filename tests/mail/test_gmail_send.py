import base64
import email
import sys
import urllib.parse
from email import policy
from pathlib import Path

import pytest

from sdoc.mail import gmail_send as gm
from sdoc.mail import send as snd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import gmail_auth  # noqa: E402


class Response:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


class FakeGoogle:
    """Answers the token endpoint and the send endpoint, and remembers calls."""

    def __init__(self, token_status=200, send_status=200, token_text=""):
        self.calls = []
        self.token_status, self.send_status, self.token_text = (
            token_status, send_status, token_text)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url == gm.TOKEN_URL:
            return Response(self.token_status,
                            {"access_token": "ya29.fresh", "expires_in": 3599},
                            text=self.token_text)
        return Response(self.send_status, {"id": "18f0abc"}, text="refused")

    def urls(self):
        return [u for u, _ in self.calls]


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("SDOC_GMAIL_CLIENT_ID", "id.apps.googleusercontent.com")
    monkeypatch.setenv("SDOC_GMAIL_CLIENT_SECRET", "GOCSPX-secret")
    monkeypatch.setenv("SDOC_GMAIL_REFRESH_TOKEN", "1//refresh")
    monkeypatch.setenv("SDOC_MAIL_USER", "hackathon3in1@gmail.com")
    monkeypatch.setenv("SDOC_MAIL_PASSWORD", "unused")
    gm.forget_token()
    yield
    gm.forget_token()


def message(to="ops@shipper.com", files=()):
    return snd.build_message("hackathon3in1@gmail.com", to, "Draft BL", "Please confirm.",
                             list(files))


# --- configuration -------------------------------------------------------

def test_all_three_values_are_needed(monkeypatch):
    assert gm.configured() is True
    monkeypatch.delenv("SDOC_GMAIL_REFRESH_TOKEN")
    assert gm.configured() is False


# --- tokens --------------------------------------------------------------

def test_the_refresh_token_is_exchanged_for_an_access_token():
    google = FakeGoogle()
    assert gm.access_token(google) == "ya29.fresh"
    url, kwargs = google.calls[0]
    assert url == gm.TOKEN_URL
    assert kwargs["data"]["grant_type"] == "refresh_token"
    assert kwargs["data"]["refresh_token"] == "1//refresh"


def test_the_access_token_is_reused_until_it_nearly_expires():
    """An access token lasts an hour; fetching one per send doubles the
    round trips for nothing."""
    google = FakeGoogle()
    gm.access_token(google)
    gm.access_token(google)
    assert google.urls().count(gm.TOKEN_URL) == 1


def test_an_expired_refresh_token_says_how_to_fix_it():
    """invalid_grant is the commonest failure: tokens from an app left in
    Testing stop working after seven days."""
    google = FakeGoogle(token_status=400,
                        token_text='{"error": "invalid_grant", "error_description": "expired"}')
    with pytest.raises(RuntimeError) as e:
        gm.access_token(google)
    assert "tools/gmail_auth.py" in str(e.value)
    assert "seven days" in str(e.value)


def test_the_secret_never_appears_in_an_error():
    google = FakeGoogle(token_status=401, token_text="unauthorized_client")
    with pytest.raises(RuntimeError) as e:
        gm.access_token(google)
    assert "GOCSPX-secret" not in str(e.value)
    assert "1//refresh" not in str(e.value)


# --- sending -------------------------------------------------------------

def test_the_message_goes_as_base64url_with_the_bearer_token():
    google = FakeGoogle()
    assert gm.send_message(message(), client=google) == "18f0abc"

    url, kwargs = google.calls[-1]
    assert url == gm.SEND_URL
    assert kwargs["headers"]["Authorization"] == "Bearer ya29.fresh"
    raw = base64.urlsafe_b64decode(kwargs["json"]["raw"])
    sent = email.message_from_bytes(raw, policy=policy.default)
    assert sent["To"] == "ops@shipper.com"
    assert sent["From"].addresses[0].addr_spec == "hackathon3in1@gmail.com"
    assert sent["Subject"] == "Draft BL"


def test_attachments_travel_inside_the_message():
    google = FakeGoogle()
    gm.send_message(message(files=[("SI.txt", b"SHIPPER: ACME"),
                                   ("BL.txt", b"SHIPPER: ACME CORP")]), client=google)
    raw = base64.urlsafe_b64decode(google.calls[-1][1]["json"]["raw"])
    sent = email.message_from_bytes(raw, policy=policy.default)
    assert [(p.get_filename(), p.get_payload(decode=True)) for p in sent.iter_attachments()] == [
        ("SI.txt", b"SHIPPER: ACME"), ("BL.txt", b"SHIPPER: ACME CORP")]


def test_a_refused_send_is_reported():
    with pytest.raises(RuntimeError) as e:
        gm.send_message(message(), client=FakeGoogle(send_status=403))
    assert "HTTP 403" in str(e.value)


def test_a_revoked_access_token_is_forgotten_so_the_next_send_recovers():
    google = FakeGoogle(send_status=401)
    with pytest.raises(RuntimeError):
        gm.send_message(message(), client=google)
    google.send_status = 200
    gm.send_message(message(), client=google)
    assert google.urls().count(gm.TOKEN_URL) == 2       # fetched a fresh one


# --- the app prefers it --------------------------------------------------

def test_the_app_sends_through_gmail_ahead_of_any_relay(monkeypatch):
    """Gmail authenticates as the account; a relay cannot prove it owns a
    Gmail address and is likelier to be filed as Spam."""
    monkeypatch.setenv("SDOC_SENDGRID_KEY", "SG.also-set")
    used = []
    monkeypatch.setattr(gm, "send_message", lambda msg, client=None: used.append("gmail"))
    monkeypatch.setattr(snd, "send_via_api", lambda *a: used.append("sendgrid"))
    monkeypatch.setattr(snd, "deliver", lambda *a: used.append("smtp"))
    snd.send("ops@shipper.com", "Draft BL", "body", [])
    assert used == ["gmail"]


def test_gmail_being_configured_means_mail_can_leave(monkeypatch):
    monkeypatch.setattr(snd, "_REACHABLE", False)       # SMTP was found blocked
    assert snd.reachable() is True


# --- the one-time authorisation script -----------------------------------

def test_the_consent_url_asks_for_a_refresh_token_and_nothing_more():
    url = gmail_auth.build_auth_url("id", "http://127.0.0.1:5555", "st8", "chal",
                                    login_hint="hackathon3in1@gmail.com")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["scope"] == [gm.SCOPE]                     # send only - cannot read mail
    assert q["access_type"] == ["offline"]              # without it, no refresh token
    assert q["prompt"] == ["consent"]                   # without it, none on a re-run
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["st8"]
    assert q["login_hint"] == ["hackathon3in1@gmail.com"]


def test_pkce_challenge_is_the_hash_of_the_verifier():
    import hashlib
    verifier, challenge = gmail_auth.pkce_pair()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected
    assert verifier != gmail_auth.pkce_pair()[0]        # fresh each time


def test_the_code_is_redeemed_with_the_verifier():
    class Token:
        def post(self, url, data=None):
            self.data = data
            return Response(200, {"refresh_token": "1//new", "access_token": "x"})

    t = Token()
    assert gmail_auth.exchange_code("code123", "verif", "http://127.0.0.1:5555",
                                    client=t)["refresh_token"] == "1//new"
    assert t.data["code_verifier"] == "verif"
    assert t.data["grant_type"] == "authorization_code"


def test_no_refresh_token_back_says_what_to_do():
    class Token:
        def post(self, url, data=None):
            return Response(200, {"access_token": "x"})

    with pytest.raises(RuntimeError) as e:
        gmail_auth.exchange_code("c", "v", "http://127.0.0.1:1", client=Token())
    assert "myaccount.google.com/permissions" in str(e.value)
