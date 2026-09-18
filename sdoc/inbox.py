"""Reads the participant bundle. Knows nothing about AI or comparison."""
import json
from pathlib import Path

from sdoc.config import BUNDLE_DIR


def load_emails() -> list[dict]:
    inbox_dir = Path(BUNDLE_DIR) / "inbox"
    paths = sorted(inbox_dir.glob("email_*.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def read_attachment_bytes(rel_path: str) -> bytes:
    return (Path(BUNDLE_DIR) / rel_path).read_bytes()


def read_attachment_text(rel_path: str) -> str:
    # errors="replace" because several attachments are deliberately corrupt.
    # Detecting that is Day 2's job; reading must never raise here.
    return read_attachment_bytes(rel_path).decode("utf-8", errors="replace")
