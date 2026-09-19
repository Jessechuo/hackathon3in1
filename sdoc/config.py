"""All paths and model names. The only place either is written."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BUNDLE_DIR = Path(os.environ.get("SDOC_BUNDLE", ROOT / "sdoc-hackathon-bundle"))
OUT_DIR = Path(os.environ.get("SDOC_OUT", ROOT / "out"))
CACHE_DIR = Path(os.environ.get("SDOC_CACHE", ROOT / ".cache"))

# Nothing else in the codebase names a model; change them here.
# Classification is the easy, high-volume step, so it runs on Haiku: ~$0.70
# per full 520-email run (estimated) vs ~$3.53 on Opus (measured). Document
# extraction is the hard step that decides the exact-field score, so it
# stays on Opus.
CLASSIFY_MODEL = "claude-haiku-4-5"
EXTRACT_MODEL = "claude-opus-5"
VISION_MODEL = "claude-opus-5"
