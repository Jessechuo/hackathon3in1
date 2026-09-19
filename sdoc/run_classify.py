"""Fan classification across the whole inbox into out/categories.json."""
import argparse
import json
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sdoc.ai.classify import classify
from sdoc.ai.client import usage_summary
from sdoc.config import OUT_DIR
from sdoc.inbox import load_emails

log = logging.getLogger(__name__)

# When classification fails we still need a category. GENERAL is the
# lowest-harm guess: it is the scorer's own default for a missing entry.
FALLBACK_CATEGORY = "GENERAL"


def _one(email: dict) -> tuple[str, dict]:
    eid = email["email_id"]
    try:
        result = classify(email)
        return eid, {
            "category": result.category,
            "says_documents_are_attached": result.says_documents_are_attached,
            "reason": result.reason,
            "error": None,
        }
    except Exception:
        log.warning("classification failed for %s", eid)
        return eid, {
            "category": FALLBACK_CATEGORY,
            "says_documents_are_attached": None,
            "reason": "classification failed",
            "error": traceback.format_exc(),
        }


def classify_all(emails: list[dict], workers: int = 8) -> dict[str, dict]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(_one, emails))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, help="only process the first N emails")
    ap.add_argument("--workers", type=int, default=8, help="parallel requests (default 8)")
    args = ap.parse_args()

    emails = load_emails()
    if args.limit:
        emails = emails[: args.limit]

    log.info("classifying %d emails with %d workers", len(emails), args.workers)
    results = classify_all(emails, workers=args.workers)

    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    out = Path(OUT_DIR) / "categories.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for r in results.values():
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    failures = sum(1 for r in results.values() if r["error"])

    log.info("wrote %s", out)
    log.info("category mix: %s", counts)
    if failures:
        log.warning("%d emails failed and fell back to %s", failures, FALLBACK_CATEGORY)
    log.info(usage_summary())


if __name__ == "__main__":
    main()
