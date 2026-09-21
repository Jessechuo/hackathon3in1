import base64
import json

import pytest

from sdoc.mail import api_send as api


class FakeResponse:
    def __init__(self, status_code=201, text=""):
        self.status_code = status_code
        self.text = text


class FakeClient:
    """Records the call instead of making it."""

    def __init__(self, status_code=201, text=""):
        self.calls = []
        self._response = FakeResponse(status_code, text)

    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._response


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    monkeypatch.delenv("SDOC_BREVO_KEY", raising=False)
    monkeypatch.delenv("SDOC_SENDGRID_KEY", raising=False)


def test_no_key_means_no_http_provider():
    assert api.provider() is None


def test_either_key_selects_its_provider(monkeypatch):
    monkeypatch.setenv("SDOC_SENDGRID_KEY", "SG.x")
    assert api.provider() == "sendgrid"
    monkeypatch.setenv("SDOC_BREVO_KEY", "xkeysib-x")
    assert api.provider() == "brevo"      # first one wins when both are set


def test_sending_without_a_key_says_which_to_set():
    with pytest.raises(RuntimeError) as e:
        api.send_via_api("a@b.com", "c@d.com", "s", "b", [], client=FakeClient())
    assert "SDOC_BREVO_KEY" in str(e.value)


def test_brevo_gets_the_shape_it_expects(monkeypatch):
    monkeypatch.setenv("SDOC_BREVO_KEY", "xkeysib-secret")
    client = FakeClient()
    assert api.send_via_api("ops@line.com", "ops@shipper.com", "Draft BL",
                            "Please confirm.", [], client=client) == "brevo"

    call = client.calls[0]
    assert call["url"] == api.BREVO_URL
    assert call["headers"]["api-key"] == "xkeysib-secret"
    assert call["json"]["sender"]["email"] == "ops@line.com"
    assert call["json"]["to"] == [{"email": "ops@shipper.com"}]
    assert call["json"]["subject"] == "Draft BL"
    assert call["json"]["textContent"] == "Please confirm."


def test_sendgrid_gets_the_shape_it_expects(monkeypatch):
    monkeypatch.setenv("SDOC_SENDGRID_KEY", "SG.secret")
    client = FakeClient(status_code=202)
    assert api.send_via_api("ops@line.com", "ops@shipper.com", "Draft BL",
                            "Please confirm.", [], client=client) == "sendgrid"

    call = client.calls[0]
    assert call["url"] == api.SENDGRID_URL
    assert call["headers"]["Authorization"] == "Bearer SG.secret"
    assert call["json"]["personalizations"] == [{"to": [{"email": "ops@shipper.com"}]}]
    assert call["json"]["from"]["email"] == "ops@line.com"
    assert call["json"]["content"][0]["value"] == "Please confirm."


@pytest.mark.parametrize("key,env", [("SDOC_BREVO_KEY", "brevo"),
                                     ("SDOC_SENDGRID_KEY", "sendgrid")])
def test_attachments_are_base64_with_their_names(monkeypatch, key, env):
    monkeypatch.setenv(key, "secret")
    client = FakeClient()
    api.send_via_api("a@b.com", "c@d.com", "s", "b",
                     [("SI.txt", b"SHIPPER: ACME"), ("BL.pdf", b"%PDF-1.4")],
                     client=client)
    payload = client.calls[0]["json"]
    files = payload["attachment"] if env == "brevo" else payload["attachments"]

    names = [f.get("name") or f.get("filename") for f in files]
    assert names == ["SI.txt", "BL.pdf"]
    assert base64.b64decode(files[0]["content"]) == b"SHIPPER: ACME"
    assert base64.b64decode(files[1]["content"]) == b"%PDF-1.4"


def test_an_empty_body_is_replaced(monkeypatch):
    """Both APIs reject a message with no content at all."""
    monkeypatch.setenv("SDOC_BREVO_KEY", "secret")
    client = FakeClient()
    api.send_via_api("a@b.com", "c@d.com", "s", "", [], client=client)
    assert client.calls[0]["json"]["textContent"].strip() == ""
    assert client.calls[0]["json"]["textContent"] != ""


def test_a_refusal_is_reported_with_what_the_provider_said(monkeypatch):
    """It is almost always the sender address not being verified, and the
    provider says so in the body."""
    monkeypatch.setenv("SDOC_BREVO_KEY", "secret")
    client = FakeClient(status_code=400, text=json.dumps(
        {"code": "invalid_parameter", "message": "sender email is not valid"}))
    with pytest.raises(RuntimeError) as e:
        api.send_via_api("a@b.com", "c@d.com", "s", "b", [], client=client)
    assert "brevo refused" in str(e.value)
    assert "HTTP 400" in str(e.value)
    assert "sender email is not valid" in str(e.value)


def test_the_key_is_never_put_in_the_error(monkeypatch):
    monkeypatch.setenv("SDOC_BREVO_KEY", "xkeysib-verysecret")
    client = FakeClient(status_code=401, text="unauthorised")
    with pytest.raises(RuntimeError) as e:
        api.send_via_api("a@b.com", "c@d.com", "s", "b", [], client=client)
    assert "xkeysib-verysecret" not in str(e.value)


@pytest.mark.parametrize("key,provider", [("SDOC_BREVO_KEY", "brevo"),
                                          ("SDOC_SENDGRID_KEY", "sendgrid")])
def test_the_relays_carry_the_name_and_reply_to_as_well(monkeypatch, key, provider):
    """Otherwise who-sent-it would depend on which provider happened to send."""
    monkeypatch.setenv(key, "secret")
    client = FakeClient()
    api.send_via_api("desk@line.com", "ops@shipper.com", "s", "b", [], client=client,
                     reply_to="clerk@line.com", name="Chuo Jesse via MailOps")
    payload = client.calls[0]["json"]
    if provider == "brevo":
        assert payload["sender"]["name"] == "Chuo Jesse via MailOps"
        assert payload["replyTo"] == {"email": "clerk@line.com"}
    else:
        assert payload["from"]["name"] == "Chuo Jesse via MailOps"
        assert payload["reply_to"] == {"email": "clerk@line.com"}
