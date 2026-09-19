"""Run the comparison checks over the inbox.

Reads out/categories.json (run `python -m sdoc.run_classify` first) and
writes out/results.json for the UI and out/submission.json for the scorer.
"""
import argparse
import json
import logging
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sdoc.ai.client import usage_summary
from sdoc.config import OUT_DIR
from sdoc.inbox import load_emails
from sdoc.pipeline import base_result, process, to_submission

log = logging.getLogger(__name__)


def run_one(email: dict, cls: dict) -> tuple[str, dict]:
    eid = email["email_id"]
    try:
        return eid, process(email, cls)
    except Exception:
        log.warning("processing failed for %s", eid)
        r = base_result(cls)
        r.update(status="NEEDS_REVIEW", review_reason="unreadable", failed=True,
                 note="Processing failed before a decision was reached - see the error.",
                 error=traceback.format_exc())
        return eid, r


def run(emails: list[dict], categories: dict, previous: dict, workers: int = 4) -> dict:
    results = dict(previous)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for eid, r in pool.map(lambda e: run_one(e, categories.get(e["email_id"], {})), emails):
            results[eid] = r
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="comma-separated email ids, e.g. email_004,email_013")
    ap.add_argument("--limit", type=int, help="only the first N emails")
    ap.add_argument("--workers", type=int, default=4, help="parallel requests (default 4)")
    args = ap.parse_args()

    out = Path(OUT_DIR)
    cats_path = out / "categories.json"
    if not cats_path.exists():
        raise SystemExit(f"{cats_path} not found. Run `python -m sdoc.run_classify` first.")
    categories = json.loads(cats_path.read_text(encoding="utf-8"))

    emails = load_emails()
    all_ids = [e["email_id"] for e in emails]
    todo = emails
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        todo = [e for e in emails if e["email_id"] in wanted]
    elif args.limit:
        todo = emails[: args.limit]

    # Partial runs update the previous results rather than wiping them.
    results_path = out / "results.json"
    previous = {}
    if (args.only or args.limit) and results_path.exists():
        previous = json.loads(results_path.read_text(encoding="utf-8"))

    log.info("processing %d emails with %d workers", len(todo), args.workers)
    results = run(todo, categories, previous, args.workers)
    for eid in all_ids:
        if eid not in results:
            results[eid] = {**base_result(categories.get(eid, {})), "note": "Not processed yet."}

    ordered = {eid: results[eid] for eid in all_ids}
    out.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
    (out / "submission.json").write_text(json.dumps(to_submission(ordered, all_ids), indent=2),
                                         encoding="utf-8")

    bl = [r for r in ordered.values() if r["category"] == "BL_COMPARISON"]
    log.info("wrote %s and submission.json (%d ids)", results_path, len(ordered))
    log.info("BL_COMPARISON status: %s", dict(Counter(r["status"] for r in bl)))
    log.info("review reasons: %s", dict(Counter(r["review_reason"] for r in bl if r["review_reason"])))
    failed = sum(1 for r in ordered.values() if r.get("failed"))
    if failed:
        log.warning("%d emails failed during processing - see 'error' in results.json", failed)
    log.info(usage_summary())


if __name__ == "__main__":
    main()
