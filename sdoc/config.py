"""All paths and model names. The only place either is written."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BUNDLE_DIR = Path(os.environ.get("SDOC_BUNDLE", ROOT / "sdoc-hackathon-bundle"))
OUT_DIR = Path(os.environ.get("SDOC_OUT", ROOT / "out"))
CACHE_DIR = Path(os.environ.get("SDOC_CACHE", ROOT / ".cache"))

# One model for everything on day 1. Change here to experiment; nothing
# else in the codebase names a model.
CLASSIFY_MODEL = "claude-opus-5"
EXTRACT_MODEL = "claude-opus-5"
VISION_MODEL = "claude-opus-5"
