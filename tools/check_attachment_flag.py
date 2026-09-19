"""Developer check: is documents_meant_to_be_attached right on the emails where
it matters — BL_COMPARISON emails with no attachments? Also confirms the
email_504 fix. Reads ground truth, so it lives in tools/, never in sdoc/."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdoc.config import OUT_DIR  # noqa: E402
from sdoc.inbox import load_emails  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GT = ROOT / "sdoc-hackathon-docker" / "data_v2" / "ground_truth.json"

cats = json.loads((Path(OUT_DIR) / "categories.json").read_text(encoding="utf-8"))
gt = json.loads(GT.read_text(encoding="utf-8"))

targets = [e["email_id"] for e in load_emails()
           if not e["attachments"] and gt[e["email_id"]]["category"] == "BL_COMPARISON"]
wrong = [eid for eid in targets
         if cats[eid].get("documents_meant_to_be_attached") != (gt[eid]["status"] == "NEEDS_REVIEW")]

print(f"BL_COMPARISON emails with no attachments: {len(targets)}")
print(f"documents_meant_to_be_attached wrong on: {wrong or 'none'}")
print(f"email_504 category: {cats['email_504']['category']}  (should be BL_COMPARISON)")
