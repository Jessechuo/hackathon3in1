"""categories.json -> submission.json.

Day 1 only fills in the category. status/defect fields are defaulted, so
stage 3 and end-to-end will score zero. That is expected — the comparison
engine fills them in next.
"""
import json
import sys
from pathlib import Path

# Works whether invoked as `python tools/make_submission.py` or
# `python -m tools.make_submission`; the former does not put the repo
# root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdoc.config import OUT_DIR  # noqa: E402
from sdoc.inbox import load_emails  # noqa: E402


def build(categories: dict, all_ids: list[str]) -> dict:
    submission = {}
    for eid in all_ids:
        entry = categories.get(eid, {})
        submission[eid] = {
            "category": entry.get("category", "GENERAL"),
            "status": "OK",
            "review_reason": None,
            "has_defect": False,
            "defect_fields": [],
        }
    return submission


def main() -> None:
    out = Path(OUT_DIR)
    source = out / "categories.json"
    if not source.exists():
        raise SystemExit(
            f"{source} not found. Run `python -m sdoc.run_classify` first."
        )

    categories = json.loads(source.read_text(encoding="utf-8"))
    all_ids = [e["email_id"] for e in load_emails()]

    submission = build(categories, all_ids)
    path = out / "submission.json"
    path.write_text(json.dumps(submission, indent=2), encoding="utf-8")
    print(f"wrote {path} with {len(submission)} entries")


if __name__ == "__main__":
    main()
