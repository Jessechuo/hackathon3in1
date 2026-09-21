"""Sending over HTTPS instead of SMTP.

Cloud hosts block outbound SMTP so their addresses are not used for spam -
Railway answers [Errno 101] Network is unreachable on every port. Port 443
is not blocked, because blocking it would block everything, so a provider
with an HTTP API can send from a host where smtplib cannot.

Two are supported because a new account at either can sit in review for a
day, which is no use to anyone on a deadline. Whichever key is present is
the one used.

    SDOC_BREVO_KEY=xkeysib-...        # brevo.com,     300/day free
    SDOC_SENDGRID_KEY=SG....          # sendgrid.com,  100/day free

Both need the From address verified first - they will not let you send as
an address you have not proved you own. Both accept a plain Gmail address
for that and confirm it by emailing you a link.
"""
import base64
import logging
import mimetypes
import os

import httpx

# Loads .env / .env.txt. Without it, configured() depends on some other
# module having imported config first - true inside the app, false in a
# script or a shell that imports this directly, and silently so.
import sdoc.config  # noqa: F401

log = logging.getLogger(__name__)

TIMEOUT = float(os.environ.get("SDOC_MAIL_API_TIMEOUT", "20"))

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


def provider() -> str | None:
    """Which HTTP sender is configured, if any. Brevo wins when both are."""
    if os.environ.get("SDOC_BREVO_KEY"):
        return "brevo"
    if os.environ.get("SDOC_SENDGRID_KEY"):
        return "sendgrid"
    return None


def _encode(attachments: list[tuple[str, bytes]]) -> list[tuple[str, str, str]]:
    out = []
    for name, data in attachments:
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        out.append((name, base64.b64encode(data).decode("ascii"), ctype))
    return out


def _brevo_payload(sender, to, subject, body, attachments,
                   reply_to=None, name=None) -> dict:
    payload = {
        "sender": {"email": sender, "name": name or "SDOC Inbox"},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body or " ",     # it rejects an empty body
    }
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    files = _encode(attachments)
    if files:
        payload["attachment"] = [{"name": n, "content": c} for n, c, _ in files]
    return payload


def _sendgrid_payload(sender, to, subject, body, attachments,
                      reply_to=None, name=None) -> dict:
    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": sender, "name": name or "SDOC Inbox"},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body or " "}],
    }
    if reply_to:
        payload["reply_to"] = {"email": reply_to}
    files = _encode(attachments)
    if files:
        payload["attachments"] = [
            {"filename": n, "content": c, "type": t, "disposition": "attachment"}
            for n, c, t in files
        ]
    return payload


def send_via_api(sender: str, to: str, subject: str, body: str,
                 attachments: list[tuple[str, bytes]], client=None,
                 reply_to: str | None = None, name: str | None = None) -> str:
    """Deliver through whichever provider is configured. Returns its name.

    `client` is the seam the tests use, so nothing here touches the network.
    """
    which = provider()
    if which == "brevo":
        url = BREVO_URL
        headers = {"api-key": os.environ["SDOC_BREVO_KEY"],
                   "content-type": "application/json", "accept": "application/json"}
        payload = _brevo_payload(sender, to, subject, body, attachments, reply_to, name)
    elif which == "sendgrid":
        url = SENDGRID_URL
        headers = {"Authorization": "Bearer " + os.environ["SDOC_SENDGRID_KEY"],
                   "Content-Type": "application/json"}
        payload = _sendgrid_payload(sender, to, subject, body, attachments, reply_to, name)
    else:
        raise RuntimeError("no mail API key set (SDOC_BREVO_KEY or SDOC_SENDGRID_KEY)")

    post = client.post if client is not None else None
    if post is None:
        with httpx.Client(timeout=TIMEOUT) as c:
            response = c.post(url, json=payload, headers=headers)
    else:
        response = post(url, json=payload, headers=headers)

    if response.status_code >= 300:
        # The body is where these APIs say what is actually wrong, and it is
        # almost always the sender address not being verified.
        detail = (response.text or "")[:300]
        raise RuntimeError(
            f"{which} refused the message (HTTP {response.status_code}): {detail}"
        )
    log.info("sent via %s to %s", which, to)
    return which
