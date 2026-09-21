"""Writing a received email to disk. No AI, no network, no shipping knowledge.

Everything here lands under MAIL_DIR, never in the bundle: the bundle is the
graded dataset and must not grow an email the organizers did not send.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sdoc.config import MAIL_DIR

# Anything outside this set is replaced. Filenames come from email and are
# not trusted: directory parts are dropped before this runs.
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else Path(MAIL_DIR)


def next_id(root: Path | None = None) -> str:
    inbox_dir = _root(root) / "inbox"
    used = []
    if inbox_dir.exists():
        for p in inbox_dir.glob("mail_*.json"):
            try:
                used.append(int(p.stem.split("_")[1]))
            except (IndexError, ValueError):
                continue
    return f"mail_{max(used, default=0) + 1:04d}"


def safe_name(email_id: str, filename: str) -> str:
    """`SI.txt` -> `mail_0001__SI.txt`.

    The double underscore is not decoration. pipeline._assign decides which
    file is the SI and which is the BL by looking for `_SI.` / `_BL.` in the
    name, so prefixing makes a sender's plain `SI.txt` recognisable.
    """
    base = Path(filename.replace("\\", "/")).name
    cleaned = UNSAFE.sub("_", base).lstrip(".")
    return f"{email_id}__{cleaned or 'file'}"


def save_email(sender: str, subject: str, body: str,
               attachments: list[tuple[str, bytes]],
               root: Path | None = None, email_id: str | None = None) -> dict:
    """Write one received email and its files. Returns the email dict, in
    exactly the shape load_emails() yields for a bundle email, plus when it
    arrived. Mail sent from the app is not stored: the Triage Queue is for
    mail that arrives.
    """
    base = _root(root)
    eid = email_id or next_id(base)
    (base / "inbox").mkdir(parents=True, exist_ok=True)
    (base / "attachments").mkdir(parents=True, exist_ok=True)

    rels = []
    for filename, data in attachments:
        name = safe_name(eid, filename)
        (base / "attachments" / name).write_bytes(data)
        rels.append(f"mail/attachments/{name}")

    email = {
        "email_id": eid,
        "from": sender,
        "subject": subject,
        "body": body,
        "attachments": rels,
        # The bundle has no dates; this orders the Triage Queue's Latest first.
        "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (base / "inbox" / f"{eid}.json").write_text(json.dumps(email, indent=2), encoding="utf-8")
    return email


def delete_sent(root: Path | None = None) -> list[str]:
    """Delete mail the app used to store when it sent something - the
    records marked direction "sent", and their attachments. Received mail is
    untouched. Returns the ids deleted; none once they are gone."""
    base = _root(root)
    gone = []
    for path in sorted((base / "inbox").glob("mail_*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("direction") != "sent":
            continue
        for rel in record.get("attachments") or []:
            (base / "attachments" / Path(rel).name).unlink(missing_ok=True)
        path.unlink()
        gone.append(record.get("email_id") or path.stem)
    return gone
