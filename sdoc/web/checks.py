"""Live checks for the Test results page: things that can be proved on the spot.

1. The automated test suite, actually run.
2. The submission file: every graded email present, every field valid, and
   nothing from the live mailbox mixed in.
3. That the saved score belongs to this exact submission, so the page cannot
   show a number left over from an older one.

Accuracy itself cannot be re-run here. The scorer needs the answer key, and
the answer key is deliberately not on the server.

The test run is isolated from the live system. Tests redirect their own
files, but the app's startup copies results into its output folder, and on
a deploy that folder is the production volume - so the run gets throwaway
folders and no credentials. Found necessary, not assumed: a run left files
behind in exactly the folders this redirects.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sdoc.ai.classify import CATEGORIES
from sdoc.config import OUT_DIR, ROOT
from sdoc.core.fields import FIELDS
from sdoc.inbox import load_emails

TIMEOUT = 240          # seconds; ~18 locally, a shared server can be slower
COOLDOWN = 30          # seconds between runs - it is a public page

STATUSES = {"OK", "MISMATCH", "NEEDS_REVIEW"}
REASONS = {"missing_attachment", "unreadable", "wrong_doc_type", "missing_value"}

# Anything a test could reach that belongs to the live system. Blanked rather
# than unset: python-dotenv will not override a variable that is already set,
# so an empty value is what stops a local .env.txt putting them back.
SECRETS = ("ANTHROPIC_API_KEY", "SDOC_MAIL_USER", "SDOC_MAIL_PASSWORD",
           "SDOC_GMAIL_CLIENT_ID", "SDOC_GMAIL_CLIENT_SECRET", "SDOC_GMAIL_REFRESH_TOKEN",
           "SDOC_SENDGRID_KEY", "SDOC_BREVO_KEY", "SDOC_SECRET_KEY", "SDOC_SIGNUP_CODE")

PROGRESS = re.compile(r"\[\s*(\d+)%\]")
COUNTS = re.compile(r"(\d+) (passed|failed|errors?|skipped)")
DURATION = re.compile(r" in ([\d.]+)s")

_lock = threading.Lock()
_state: dict = {"state": "idle"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def isolated_env(scratch: Path) -> dict:
    env = dict(os.environ)
    env.update(SDOC_OUT=str(scratch / "out"), SDOC_MAIL=str(scratch / "mail"),
               SDOC_CACHE=str(scratch / "cache"), PYTHONIOENCODING="utf-8")
    for key in SECRETS:
        env[key] = ""
    return env


def parse_summary(line: str) -> dict:
    """"1 failed, 301 passed in 17.12s" -> counts and duration."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for n, kind in COUNTS.findall(line):
        counts["errors" if kind.startswith("error") else kind] = int(n)
    d = DURATION.search(line)
    counts["duration"] = float(d.group(1)) if d else None
    return counts


# --- the two instant checks ----------------------------------------------

def _graded_file(name: str) -> Path | None:
    """The copy that ships with the code first - see load_score in app.py."""
    for base in (Path(ROOT) / "out", Path(OUT_DIR)):
        if (base / name).exists():
            return base / name
    return None


def _entry_problem(v) -> str | None:
    if not isinstance(v, dict):
        return "not an object"
    if v.get("category") not in CATEGORIES:
        return "unknown category"
    if v.get("status") not in STATUSES:
        return "unknown status"
    if v.get("review_reason") not in REASONS | {None}:
        return "unknown review reason"
    if not isinstance(v.get("has_defect"), bool):
        return "has_defect is not true/false"
    fields = v.get("defect_fields")
    if not isinstance(fields, list) or any(f not in FIELDS for f in fields):
        return "unknown defect field"
    if v["status"] == "MISMATCH" and not (v["has_defect"] and fields):
        return "MISMATCH with no defect fields"
    if v["status"] == "NEEDS_REVIEW" and not v["review_reason"]:
        return "NEEDS_REVIEW with no reason"
    return None


def check_submission(sub: dict, expected_ids: set[str]) -> dict:
    ids = set(sub)
    problems = {eid: p for eid, v in sub.items() if (p := _entry_problem(v))}
    missing, extra = expected_ids - ids, ids - expected_ids
    return {
        "total": len(sub), "expected": len(expected_ids),
        "missing": len(missing), "extra": len(extra), "invalid": len(problems),
        "first_problem": next(iter(problems.items()), None),
        "live_mail_leaked": sum(1 for eid in extra if eid.startswith("mail_")),
        "ok": not (missing or extra or problems),
    }


def check_score_matches(sub: dict, score: dict) -> dict:
    """Is the saved score about THIS submission?

    Without the answer key the score cannot be recomputed, but its predicted
    side can be: how many emails the scorer saw in each category, and how many
    it saw escalated, must equal what this file contains.
    """
    predicted = Counter(v.get("category") for v in sub.values())
    seen = Counter()
    for row in score.get("stage1", {}).get("confusion", {}).values():   # actual -> predicted -> n
        for pred, n in row.items():
            seen[pred] += n
    escalated = sum(1 for v in sub.values() if v.get("status") == "NEEDS_REVIEW")
    checks = {
        "emails": score.get("n_emails") == len(sub),
        "categories": +predicted == +seen,
        "escalations": score.get("reliability", {}).get("pred_review") == escalated,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "final": score.get("final_score"), "accuracy": score.get("stage1", {}).get("accuracy")}


# --- the test run --------------------------------------------------------

def _run_tests(update) -> dict:
    with tempfile.TemporaryDirectory(prefix="sdoc-checks-") as scratch:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=str(ROOT), env=isolated_env(Path(scratch)),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1)
        killer = threading.Timer(TIMEOUT, proc.kill)
        killer.start()
        summary, tail = "", []
        try:
            for line in proc.stdout:
                m = PROGRESS.search(line)
                if m:
                    update(progress=int(m.group(1)))
                if COUNTS.search(line) and DURATION.search(line):
                    summary = line.strip().strip("= ").strip()
                tail = (tail + [line.rstrip()])[-12:]
            proc.wait()
        finally:
            killer.cancel()
    if not summary:
        return {"ok": False, "summary": "the test run did not finish", "tail": tail,
                "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "duration": None}
    result = parse_summary(summary)
    result.update(summary=summary, tail=tail if proc.returncode else [],
                  ok=proc.returncode == 0 and result["failed"] == 0 and result["errors"] == 0)
    return result


def status() -> dict:
    with _lock:
        return json.loads(json.dumps(_state))


def _update(**fields) -> None:
    with _lock:
        _state.update(fields)


def start(load_score, runner=None) -> tuple[bool, str]:
    """Begin a run in the background. Returns (started, reason if not)."""
    with _lock:
        if _state.get("state") == "running":
            return False, "already running"
        done = _state.get("finished_ts")
        if done and time.time() - done < COOLDOWN:
            return False, f"wait {int(COOLDOWN - (time.time() - done)) + 1}s before running again"
        _state.clear()
        _state.update(state="running", progress=0, started_at=_now())
    threading.Thread(target=_work, args=(load_score, runner or _run_tests),
                     daemon=True, name="sdoc-checks").start()
    return True, ""


def _work(load_score, runner) -> None:
    try:
        sub_path = _graded_file("submission.json")
        sub = json.loads(sub_path.read_text(encoding="utf-8")) if sub_path else {}
        expected = {e["email_id"] for e in load_emails()}
        _update(submission=check_submission(sub, expected))
        score = load_score()
        _update(score=check_score_matches(sub, score) if score else None)

        tests = runner(_update)
        _update(tests=tests, progress=100)
        everything = [tests.get("ok"), _state["submission"]["ok"],
                      (_state.get("score") or {}).get("ok", False)]
        _update(state="passed" if all(everything) else "failed",
                finished_at=_now(), finished_ts=time.time())
    except Exception as e:                                   # a broken check is a result
        _update(state="error", error=f"{type(e).__name__}: {e}",
                finished_at=_now(), finished_ts=time.time())
