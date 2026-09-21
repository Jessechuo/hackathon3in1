"""Sending through the Gmail API, as the account itself.

SMTP is blocked on Railway, and a relay like SendGrid sends *on behalf of* a
Gmail address it cannot prove it owns - so Gmail files the message as
suspicious, labels it "via sendgrid.net", and often puts it in Spam. The
Gmail API has neither problem: it is HTTPS on port 443, which is never
blocked, and Google is the one sending, so the message authenticates as
genuinely from the account and lands in the Inbox. It also appears in the
account's own Sent folder, like mail sent by hand.

Three values, all obtained once with `python tools/gmail_auth.py`:

    SDOC_GMAIL_CLIENT_ID=....apps.googleusercontent.com
    SDOC_GMAIL_CLIENT_SECRET=GOCSPX-...
    SDOC_GMAIL_REFRESH_TOKEN=1//...

The scope asked for is gmail.send and nothing else: the app can send mail as
the account, and cannot read, search or delete any of it.
"""
import base64
import logging
import os
import threading
import time

import httpx

# Loads .env / .env.txt. Without it, configured() depends on some other
# module having imported config first - true inside the app, false in a
# script or a shell that imports this directly, and silently so.
import sdoc.config  # noqa: F401

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPE = "https://www.googleapis.com/auth/gmail.send"
TIMEOUT = float(os.environ.get("SDOC_MAIL_API_TIMEOUT", "20"))

KEYS = ("SDOC_GMAIL_CLIENT_ID", "SDOC_GMAIL_CLIENT_SECRET", "SDOC_GMAIL_REFRESH_TOKEN")

# An access token lasts about an hour. Asking for a new one on every send
# would double the round trips for nothing.
_token = {"value": None, "expires": 0.0}
_lock = threading.Lock()


def configured() -> bool:
    return all(os.environ.get(k) for k in KEYS)


def _post(client, url, **kwargs):
    if client is not None:
        return client.post(url, **kwargs)
    with httpx.Client(timeout=TIMEOUT) as c:
        return c.post(url, **kwargs)


def forget_token() -> None:
    with _lock:
        _token.update(value=None, expires=0.0)


def access_token(client=None) -> str:
    """A current access token, from the cache or freshly exchanged."""
    with _lock:
        if _token["value"] and time.time() < _token["expires"] - 60:
            return _token["value"]

        response = _post(client, TOKEN_URL, data={
            "client_id": os.environ["SDOC_GMAIL_CLIENT_ID"],
            "client_secret": os.environ["SDOC_GMAIL_CLIENT_SECRET"],
            "refresh_token": os.environ["SDOC_GMAIL_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        })
        if response.status_code >= 300:
            text = (response.text or "")[:300]
            if "invalid_grant" in text:
                # By far the commonest failure. While the Google Cloud app is
                # in Testing, refresh tokens stop working after seven days.
                raise RuntimeError(
                    "Gmail refused the refresh token (invalid_grant) - it has "
                    "expired or been revoked. Run `python tools/gmail_auth.py` "
                    "again and replace SDOC_GMAIL_REFRESH_TOKEN. Tokens from an "
                    "app left in Testing expire after seven days.")
            raise RuntimeError(f"Gmail token exchange failed (HTTP {response.status_code}): {text}")

        body = response.json()
        _token.update(value=body["access_token"],
                      expires=time.time() + float(body.get("expires_in", 3600)))
        return _token["value"]


def send_message(msg, client=None) -> str:
    """Send a built EmailMessage. Returns Gmail's id for the sent message."""
    token = access_token(client)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    response = _post(client, SEND_URL, json={"raw": raw},
                     headers={"Authorization": f"Bearer {token}"})

    if response.status_code == 401:
        # The cached token was revoked early. Throw it away so the next send
        # asks for a fresh one rather than failing until the hour is up.
        forget_token()
    if response.status_code >= 300:
        raise RuntimeError(
            f"Gmail refused the message (HTTP {response.status_code}): "
            f"{(response.text or '')[:300]}")

    message_id = response.json().get("id", "")
    log.info("sent via gmail api to %s (id %s)", msg.get("To"), message_id)
    return message_id
