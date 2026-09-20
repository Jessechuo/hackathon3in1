"""Sending mail out through Gmail. The counterpart to gmail.py.

Same account and the same App Password that the watcher reads with; Gmail
allows both over one credential.

Sending is OFF unless SDOC_SEND_TOKEN is set. The app is on a public URL,
and a send form with no lock on it is an open relay - strangers would be
mailing the world from this account until Google suspended it.
"""
import mimetypes
import os
import re
import secrets
import smtplib
from email.message import EmailMessage

import sdoc.config  # noqa: F401  - importing loads .env / .env.txt

HOST = "smtp.gmail.com"
PORT = 465

# Deliberately loose. Real address validity is decided by the mail server
# rejecting it, not by a regex; this only catches obvious typing mistakes.
ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def send_token() -> str | None:
    return os.environ.get("SDOC_SEND_TOKEN") or None


def sending_enabled() -> bool:
    return bool(send_token())


def token_ok(supplied: str) -> bool:
    """compare_digest so a wrong guess takes the same time as a right one."""
    expected = send_token()
    if not expected:
        return False
    return secrets.compare_digest(supplied or "", expected)


def valid_address(address: str) -> bool:
    return bool(ADDRESS.match((address or "").strip()))


def build_message(sender: str, to: str, subject: str, body: str,
                  attachments: list[tuple[str, bytes]]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body or "")
    for name, data in attachments:
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, _, subtype = ctype.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg


def send(to: str, subject: str, body: str, attachments: list[tuple[str, bytes]],
         user: str | None = None, password: str | None = None,
         transport=None) -> EmailMessage:
    """Deliver one message. `transport` is the seam the tests use: given one,
    nothing touches the network."""
    user = user or os.environ.get("SDOC_MAIL_USER")
    password = password or os.environ.get("SDOC_MAIL_PASSWORD")
    if not user or not password:
        raise RuntimeError("set SDOC_MAIL_USER and SDOC_MAIL_PASSWORD to send mail")

    msg = build_message(user, to, subject, body, attachments)
    if transport is not None:
        transport(msg)
        return msg
    with smtplib.SMTP_SSL(HOST, PORT) as server:
        server.login(user, password)
        server.send_message(msg)
    return msg
