"""Reads the participant bundle, plus any mail received since. Knows nothing
about AI or comparison."""
import json
from pathlib import Path

from sdoc.config import BUNDLE_DIR, MAIL_DIR

# Received attachments carry this prefix so one look at the path says which
# folder it lives in. The bundle's own paths start "attachments/".
MAIL_PREFIX = "mail/"


def load_emails() -> list[dict]:
    """The organizers' 520. Stays bundle-only: run_pipeline builds
    submission.json from these ids, and a stray id there is invalid."""
    inbox_dir = Path(BUNDLE_DIR) / "inbox"
    paths = sorted(inbox_dir.glob("email_*.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def load_received() -> list[dict]:
    """Mail that arrived after the bundle, oldest first."""
    inbox_dir = Path(MAIL_DIR) / "inbox"
    if not inbox_dir.exists():
        return []
    paths = sorted(inbox_dir.glob("mail_*.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def load_all_emails() -> list[dict]:
    """Everything the app shows: the bundle first, then what arrived."""
    return load_emails() + load_received()


def attachment_path(rel_path: str) -> Path:
    if rel_path.startswith(MAIL_PREFIX):
        return Path(MAIL_DIR) / rel_path[len(MAIL_PREFIX):]
    return Path(BUNDLE_DIR) / rel_path


def read_attachment_bytes(rel_path: str) -> bytes:
    return attachment_path(rel_path).read_bytes()


def read_attachment_text(rel_path: str) -> str:
    # errors="replace" because several attachments are deliberately corrupt.
    # Detecting that is the pipeline's job; reading must never raise here.
    return read_attachment_bytes(rel_path).decode("utf-8", errors="replace")
