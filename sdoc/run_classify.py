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
            "documents_meant_to_be_attached": result.documents_meant_to_be_attached,
            "reason": result.reason,
            "error": None,
        }
    except Exception:
        log.warning("classification failed for %s", eid)
        return eid, {
            "category": FALLBACK_CATEGORY,
            "documents_meant_to_be_attached": None,
            "reason": "classification failed",
            "error": traceback.format_exc(),
        }


def classify_all(emails: list[dict], workers: int = 8) -> dict[str, dict]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(_one, emails))


def select(emails: list[dict], only: str | None = None, limit: int | None = None) -> list[dict]:
    """--only takes comma-separated ids; --limit takes the first N."""
    if only:
        wanted = {s.strip() for s in only.split(",") if s.strip()}
        return [e for e in emails if e["email_id"] in wanted]
    return emails[:limit] if limit else emails


def merge_with_previous(new: dict, partial: bool) -> dict:
    """A partial run (--only / --limit) updates categories.json instead of
    replacing it, so testing a few emails never throws away the other 500."""
    path = Path(OUT_DIR) / "categories.json"
    if not partial or not path.exists():
        return dict(new)
    merged = json.loads(path.read_text(encoding="utf-8"))
    merged.update(new)
    return merged


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpx2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="comma-separated email ids, e.g. email_119,email_506")
    ap.add_argument("--limit", type=int, help="only process the first N emails")
    ap.add_argument("--workers", type=int, default=8, help="parallel requests (default 8)")
    args = ap.parse_args()

    emails = select(load_emails(), args.only, args.limit)

    log.info("classifying %d emails with %d workers", len(emails), args.workers)
    new = classify_all(emails, workers=args.workers)
    results = merge_with_previous(new, partial=bool(args.only or args.limit))

    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    out = Path(OUT_DIR) / "categories.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    counts: dict[str, int] = {}
    for r in results.values():
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    failures = sum(1 for r in new.values() if r["error"])

    log.info("wrote %s (%d emails)", out, len(results))
    log.info("category mix: %s", counts)
    if failures:
        log.warning("%d emails failed and fell back to %s", failures, FALLBACK_CATEGORY)
    log.info(usage_summary())


if __name__ == "__main__":
    main()
