"""RFC 822 bytes -> the four things the pipeline needs. No network, no AI.

A real message is messier than a bundle email: the body may be HTML, the
subject may be MIME-encoded, and a signature image arrives as an attachment
with no filename. All of that is flattened here so everything downstream
sees exactly the shape load_emails() yields.
"""
import re
from email import message_from_bytes, policy
from email.utils import parseaddr
from html import unescape

_DROP = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_BREAK = re.compile(r"(?i)<br\s*/?>|</(p|div|tr|li|h[1-6])>")
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


def parse_message(raw: bytes) -> dict:
    msg = message_from_bytes(raw, policy=policy.default)
    sender = parseaddr(str(msg.get("From", "")))[1] or str(msg.get("From", ""))
    return {
        "from": sender,
        "subject": str(msg.get("Subject", "") or ""),
        "body": _body(msg),
        "attachments": _attachments(msg),
    }


def _text(part) -> str:
    try:
        return part.get_content()
    except Exception:
        return (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")


def _body(msg) -> str:
    """The plain-text part if the sender wrote one, else the HTML flattened.

    Outlook and Gmail both send multipart/alternative; the plain part is the
    same words without the markup, so it is always the better input.
    """
    part = msg.get_body(preferencelist=("plain", "html")) if msg.is_multipart() else msg
    if part is None:
        return ""
    text = _text(part)
    if part.get_content_type() == "text/html":
        text = strip_html(text)
    return text.strip()


def strip_html(html: str) -> str:
    text = _DROP.sub("", html)
    text = _BREAK.sub("\n", text)
    text = _TAG.sub("", text)
    text = unescape(text).replace(" ", " ")
    lines = [line.strip() for line in text.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def _attachments(msg) -> list[tuple[str, bytes]]:
    out = []
    if not msg.is_multipart():
        return out
    for part in msg.iter_attachments():
        name = part.get_filename()
        if not name:
            continue        # inline signature images and the like
        out.append((str(name), part.get_payload(decode=True) or b""))
    return out
