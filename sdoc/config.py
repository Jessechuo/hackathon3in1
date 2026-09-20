"""All paths and model names. The only place either is written."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Local secrets, loaded before anything reads the environment: the API key and
# the mail credentials. Both names are gitignored. load_dotenv does not
# override variables that are already set, so a real environment variable - a
# deploy's own secret, or an export in the current shell - always wins.
for _secrets in (ROOT / ".env", ROOT / ".env.txt"):
    load_dotenv(_secrets)

BUNDLE_DIR = Path(os.environ.get("SDOC_BUNDLE", ROOT / "sdoc-hackathon-bundle"))
OUT_DIR = Path(os.environ.get("SDOC_OUT", ROOT / "out"))
CACHE_DIR = Path(os.environ.get("SDOC_CACHE", ROOT / ".cache"))

# Mail that arrives after the bundle - typed into the compose form or fetched
# from a mailbox. Kept apart from BUNDLE_DIR on purpose: the bundle is the
# graded dataset and its 520 ids are exactly what submission.json must hold.
MAIL_DIR = Path(os.environ.get("SDOC_MAIL", ROOT / "mail"))

# Nothing else in the codebase names a model; change them here.
# Classification is the easy, high-volume step, so it runs on Haiku: ~$0.70
# per full 520-email run (estimated) vs ~$3.53 on Opus (measured). Document
# extraction is the hard step that decides the exact-field score, so it
# stays on Opus.
CLASSIFY_MODEL = "claude-haiku-4-5"
EXTRACT_MODEL = "claude-opus-5"
VISION_MODEL = "claude-opus-5"

# USD per 1M tokens (input, output). Used only to print a cost line after
# each run so spend is visible; Anthropic bills from its own records.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
