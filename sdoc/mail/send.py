"""Sending mail out through Gmail. The counterpart to gmail.py.

Same account and the same App Password that the watcher reads with; Gmail
allows both over one credential.

Sending is OFF unless SDOC_SEND_TOKEN is set. The app is on a public URL,
and a send form with no lock on it is an open relay - strangers would be
mailing the world from this account until Google suspended it.
"""
import logging
import mimetypes
import os
import re
import secrets
import smtplib
import socket
from email.message import EmailMessage

import sdoc.config  # noqa: F401  - importing loads .env / .env.txt
from sdoc.mail.api_send import provider as api_provider
from sdoc.mail.api_send import send_via_api

log = logging.getLogger(__name__)

HOST = os.environ.get("SDOC_SMTP_HOST", "smtp.gmail.com")

# Gmail listens on both. Tried in order because some hosts block one and not
# the other, and many cloud providers block outbound SMTP entirely to stop
# being used for spam - Railway answers [Errno 101] Network is unreachable.
PORTS = (465, 587)

# Without this smtplib waits forever on a blocked route, which reads as the
# app hanging rather than as a send that cannot work.
TIMEOUT = float(os.environ.get("SDOC_SMTP_TIMEOUT", "15"))

# Deliberately loose. Real address validity is decided by the mail server
# rejecting it, not by a regex; this only catches obvious typing mistakes.
ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# Whether this machine can reach the mail server at all. None until probed.
# Not a setting: it is a fact about where the app happens to be running, and
# asking beats making someone remember an environment variable per host.
_REACHABLE: bool | None = None


def reachable() -> bool | None:
    """Can mail leave this machine? An HTTP provider always can - port 443
    is not blocked anywhere, or nothing would work."""
    if api_provider():
        return True
    return _REACHABLE


def probe(timeout: float = 5.0) -> bool:
    """Can a TCP connection to the mail server be opened from here?

    Cloud hosts commonly block outbound SMTP so their addresses do not end
    up on spam blacklists; Railway answers [Errno 101]. Knowing before
    anyone presses Send is the difference between an explanation and a
    mystery.
    """
    global _REACHABLE
    if api_provider():
        _REACHABLE = True
        return True
    for port in PORTS:
        try:
            with socket.create_connection((HOST, port), timeout=timeout):
                _REACHABLE = True
                return True
        except OSError as e:
            log.info("smtp %s:%s unreachable - %s", HOST, port, e)
    _REACHABLE = False
    return False


def note_unreachable() -> None:
    """Called when a real send fails on the network, so the page stops
    offering something that cannot work."""
    global _REACHABLE
    _REACHABLE = False


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
    # An HTTP provider goes over 443, which is what makes sending work on a
    # host that blocks SMTP. SMTP stays the default for running locally.
    if api_provider():
        send_via_api(user, to, subject, body, attachments)
    else:
        deliver(msg, user, password)
    return msg


def deliver(msg, user: str, password: str) -> int:
    """Hand the message to Gmail. Returns the port that worked.

    Raises the last error if no port does, naming every one tried - a host
    that blocks outbound SMTP is the likeliest cause and worth saying so.
    """
    last = None
    for port in PORTS:
        try:
            if port == 465:
                server = smtplib.SMTP_SSL(HOST, port, timeout=TIMEOUT)
            else:
                server = smtplib.SMTP(HOST, port, timeout=TIMEOUT)
                server.starttls()
            with server:
                server.login(user, password)
                server.send_message(msg)
            return port
        except (OSError, smtplib.SMTPException) as e:
            log.warning("smtp %s:%s failed - %s", HOST, port, e)
            last = e
    raise RuntimeError(
        f"could not reach {HOST} on any of {', '.join(map(str, PORTS))} "
        f"({type(last).__name__}: {last}). Many hosts block outbound SMTP."
    ) from last
