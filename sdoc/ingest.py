"""A received email, taken from arrival to a decision.

The same two steps the batch runners do - classify, then compare - but for
one email at a time. Both steps are the untouched functions the graded run
uses, so a received email is judged by exactly the same rules.

Results go to mail_results.json, not results.json: a full `run_pipeline`
rewrites results.json from the 520 bundle ids and would drop anything else.
"""
import json
import logging
import traceback
from pathlib import Path

from sdoc.ai.classify import classify
from sdoc.config import OUT_DIR
from sdoc.pipeline import base_result, process

log = logging.getLogger(__name__)

MAIL_RESULTS = "mail_results.json"


def _dir(out_dir: Path | None) -> Path:
    return Path(out_dir) if out_dir is not None else Path(OUT_DIR)


def load_mail_results(out_dir: Path | None = None) -> dict:
    path = _dir(out_dir) / MAIL_RESULTS
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_mail_results(state: dict, out_dir: Path | None = None) -> None:
    base = _dir(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    (base / MAIL_RESULTS).write_text(json.dumps(state, indent=2), encoding="utf-8")


def ingest(email: dict, out_dir: Path | None = None) -> dict:
    """Classify, compare if it is a document check, save, return the result.

    Never raises. A watcher runs unattended, so one bad email records its own
    failure and the next one still gets processed - the same bargain
    run_classify and run_pipeline already make.
    """
    try:
        c = classify(email)
        cls = {"category": c.category,
               "documents_meant_to_be_attached": c.documents_meant_to_be_attached,
               "reason": c.reason, "error": None}
    except Exception:
        log.warning("classification failed for %s", email["email_id"])
        cls = {"category": "GENERAL", "documents_meant_to_be_attached": None,
               "reason": "classification failed", "error": traceback.format_exc()}

    try:
        result = process(email, cls)
    except Exception:
        log.warning("processing failed for %s", email["email_id"])
        result = base_result(cls)
        result.update(status="NEEDS_REVIEW", review_reason="unreadable", failed=True,
                      note="Processing failed before a decision was reached - see the error.",
                      error=traceback.format_exc())

    state = load_mail_results(out_dir)
    state[email["email_id"]] = result
    save_mail_results(state, out_dir)
    return result
