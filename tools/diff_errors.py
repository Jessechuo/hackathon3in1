"""Developer tool: which emails did we get wrong?

Reads ground_truth.json. NOTHING under sdoc/ may do this — it is a
scoreboard, not a lookup table. Use it to find the emails to go read,
then fix the underlying prompt or rule, never the individual case.

    python tools/diff_errors.py
    python tools/diff_errors.py --ground-truth /path/to/ground_truth.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GT = ROOT / "sdoc-hackathon-docker" / "data_v2" / "ground_truth.json"
DEFAULT_SUB = ROOT / "out" / "submission.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ground-truth", type=Path, default=DEFAULT_GT)
    ap.add_argument("--submission", type=Path, default=DEFAULT_SUB)
    ap.add_argument("--limit", type=int, default=40, help="rows to print per section")
    args = ap.parse_args()

    if not args.ground_truth.exists():
        print(f"ground truth not found: {args.ground_truth}", file=sys.stderr)
        return 1
    if not args.submission.exists():
        print(f"submission not found: {args.submission}\n"
              "Run `python tools/make_submission.py` first.", file=sys.stderr)
        return 1

    gt = json.loads(args.ground_truth.read_text(encoding="utf-8"))
    sub = json.loads(args.submission.read_text(encoding="utf-8"))

    wrong_category = []
    wrong_fields = []

    for eid, truth in gt.items():
        mine = sub.get(eid, {})
        if mine.get("category") != truth["category"]:
            wrong_category.append((eid, mine.get("category"), truth["category"]))
        elif set(mine.get("defect_fields", [])) != set(truth["defect_fields"]):
            wrong_fields.append((eid, mine.get("defect_fields"), truth["defect_fields"]))

    print(f"CATEGORY WRONG: {len(wrong_category)} of {len(gt)}")
    for eid, got, want in wrong_category[: args.limit]:
        print(f"  {eid}  said {str(got):<14} actual {want}")
    if len(wrong_category) > args.limit:
        print(f"  ... and {len(wrong_category) - args.limit} more")

    print(f"\nDEFECT FIELDS WRONG: {len(wrong_fields)}")
    for eid, got, want in wrong_fields[: args.limit]:
        print(f"  {eid}  said {got} actual {want}")
    if len(wrong_fields) > args.limit:
        print(f"  ... and {len(wrong_fields) - args.limit} more")

    if not wrong_category and not wrong_fields:
        print("\nNothing wrong. Suspicious — check the submission is not empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
