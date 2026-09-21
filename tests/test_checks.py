import io
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sdoc.inbox import load_emails
from sdoc.web import app as web
from sdoc.web import checks

GOOD = {"category": "BL_COMPARISON", "status": "OK", "review_reason": None,
        "has_defect": False, "defect_fields": []}


@pytest.fixture(autouse=True)
def fresh_state():
    """Module-level state survives between tests; each one starts idle."""
    with checks._lock:
        checks._state.clear()
        checks._state["state"] = "idle"
    yield
    for t in threading.enumerate():
        if t.name == "sdoc-checks":
            t.join(timeout=10)


def settle():
    for t in threading.enumerate():
        if t.name == "sdoc-checks":
            t.join(timeout=10)


# --- reading pytest's own summary ----------------------------------------

@pytest.mark.parametrize("line,passed,failed,errors,duration", [
    ("302 passed in 17.74s", 302, 0, 0, 17.74),
    ("1 failed, 301 passed in 17.12s", 301, 1, 0, 17.12),
    ("2 errors in 1.20s", 0, 0, 2, 1.20),
    ("300 passed, 2 skipped in 16.00s", 300, 0, 0, 16.0),
])
def test_the_summary_line_is_read_correctly(line, passed, failed, errors, duration):
    s = checks.parse_summary(line)
    assert (s["passed"], s["failed"], s["errors"], s["duration"]) == (passed, failed, errors, duration)


# --- following the run test by test --------------------------------------

FAILING_RUN = (
    "SDOC-TOTAL 5\n"
    "..F.s                                                          [100%]\n"
    "=================================== FAILURES ===================================\n"
    "..\\sdoc\\core\\compare.py:12: in compare\n"
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_x.py::test_y - assert 1 == 2\n"
    "1 failed, 3 passed, 1 skipped in 0.52s\n"
)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_each_result_is_reported_in_order_and_nothing_else_counts(newline):
    """The traceback line starts with ".." and the summary with "FAILED" -
    neither is a test result."""
    updates = []
    out = checks.read_results(io.BytesIO(FAILING_RUN.replace("\n", newline).encode()),
                              lambda **kw: updates.append(kw))
    assert out["total"] == 5 and updates[0] == {"total": 5}     # known before any result
    seqs = [u["seq"] for u in updates if "seq" in u]
    assert seqs == [".", "..", "..F", "..F.", "..F.s"]          # one update per test
    assert out["counts"] == {"passed": 3, "failed": 1, "errors": 0, "skipped": 1}
    assert out["summary"] == "1 failed, 3 passed, 1 skipped in 0.52s"


def test_results_across_several_lines_are_all_counted():
    run = "SDOC-TOTAL 150\n" + "." * 72 + " [ 48%]\n" + "." * 72 + " [ 96%]\n" + "......  [100%]\n" + \
          "150 passed in 3.10s\n"
    updates = []
    out = checks.read_results(io.BytesIO(run.encode()), lambda **kw: updates.append(kw))
    assert updates[-1]["done"] == 150 and updates[-1]["progress"] == 100
    assert out["counts"]["passed"] == 150


# --- isolation from the live system --------------------------------------

def test_the_run_cannot_reach_live_data_or_credentials(tmp_path, monkeypatch):
    """On a deploy the output folder is the production volume, and the app's
    startup writes into it. The run gets throwaway folders and no secrets."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    monkeypatch.setenv("SDOC_GMAIL_REFRESH_TOKEN", "1//real")
    monkeypatch.setenv("SDOC_OUT", "/data/out")
    env = checks.isolated_env(tmp_path)
    assert env["SDOC_OUT"] == str(tmp_path / "out")
    assert env["SDOC_MAIL"] == str(tmp_path / "mail")
    assert env["SDOC_CACHE"] == str(tmp_path / "cache")
    for key in checks.SECRETS:
        assert env[key] == "", key                    # blanked, so .env.txt cannot refill it


# --- the submission check ------------------------------------------------

def test_a_complete_valid_submission_passes():
    result = checks.check_submission({"email_001": GOOD, "email_002": GOOD},
                                     {"email_001", "email_002"})
    assert result["ok"] and result["total"] == 2 and result["invalid"] == 0


def test_a_missing_graded_email_fails():
    result = checks.check_submission({"email_001": GOOD}, {"email_001", "email_002"})
    assert not result["ok"] and result["missing"] == 1


def test_live_mail_mixed_into_the_submission_is_caught():
    """A stray id makes the whole submission invalid for the organizers."""
    result = checks.check_submission({"email_001": GOOD, "mail_0007": GOOD}, {"email_001"})
    assert not result["ok"] and result["extra"] == 1 and result["live_mail_leaked"] == 1


@pytest.mark.parametrize("entry,problem", [
    ({**GOOD, "category": "MAYBE"}, "unknown category"),
    ({**GOOD, "status": "MISMATCH", "has_defect": True, "defect_fields": []}, "MISMATCH with no defect fields"),
    ({**GOOD, "status": "NEEDS_REVIEW"}, "NEEDS_REVIEW with no reason"),
    ({**GOOD, "defect_fields": ["colour"]}, "unknown defect field"),
])
def test_invalid_entries_are_named(entry, problem):
    result = checks.check_submission({"email_001": entry}, {"email_001"})
    assert not result["ok"]
    assert result["first_problem"] == ["email_001", problem] or \
        result["first_problem"] == ("email_001", problem)


# --- is the saved score about this submission? ---------------------------

SCORE = {"n_emails": 3, "final_score": 1.0,
         "stage1": {"accuracy": 1.0,
                    "confusion": {"BL_COMPARISON": {"BL_COMPARISON": 2}, "SPAM": {"SPAM": 1}}},
         "reliability": {"pred_review": 1}}
SUB = {"email_001": {**GOOD, "status": "NEEDS_REVIEW", "review_reason": "unreadable"},
       "email_002": GOOD,
       "email_003": {**GOOD, "category": "SPAM"}}


def test_a_score_from_this_submission_matches():
    result = checks.check_score_matches(SUB, SCORE)
    assert result["ok"] and all(result["checks"].values())


def test_a_score_from_a_different_submission_is_caught():
    changed = dict(SUB, email_003={**GOOD, "category": "GENERAL"})
    result = checks.check_score_matches(changed, SCORE)
    assert not result["ok"] and result["checks"]["categories"] is False


def test_a_different_escalation_count_is_caught():
    changed = dict(SUB, email_001=GOOD)
    result = checks.check_score_matches(changed, SCORE)
    assert not result["ok"] and result["checks"]["escalations"] is False


# --- against the real files ----------------------------------------------

def test_the_real_submission_is_complete_and_valid():
    sub = json.loads((Path(web.ROOT) / "out" / "submission.json").read_text(encoding="utf-8"))
    result = checks.check_submission(sub, {e["email_id"] for e in load_emails()})
    assert result["ok"], result
    assert result["total"] == 520


def test_the_real_saved_score_belongs_to_the_real_submission():
    sub = json.loads((Path(web.ROOT) / "out" / "submission.json").read_text(encoding="utf-8"))
    result = checks.check_score_matches(sub, web.load_score())
    assert result["ok"], result["checks"]


# --- running, one at a time ----------------------------------------------

def fake_tests(update):
    update(progress=50)
    return {"ok": True, "passed": 302, "failed": 0, "errors": 0, "skipped": 0,
            "duration": 17.7, "summary": "302 passed in 17.70s", "tail": []}


def test_a_run_reports_all_three_checks():
    started, _ = checks.start(web.load_score, runner=fake_tests)
    assert started
    settle()
    s = checks.status()
    assert s["state"] == "passed"
    assert s["tests"]["passed"] == 302
    assert s["submission"]["total"] == 520 and s["submission"]["ok"]
    assert s["score"]["ok"] and s["score"]["accuracy"] == 1.0


def test_a_failing_test_run_marks_the_whole_run_failed():
    failing = lambda update: {**fake_tests(update), "ok": False, "failed": 1, "passed": 301}
    checks.start(web.load_score, runner=failing)
    settle()
    assert checks.status()["state"] == "failed"


def test_only_one_run_at_a_time():
    release = threading.Event()

    def slow(update):
        release.wait(timeout=10)
        return fake_tests(update)

    assert checks.start(web.load_score, runner=slow)[0]
    started, reason = checks.start(web.load_score, runner=slow)
    assert not started and reason == "already running"
    release.set()


def test_a_short_cooldown_between_runs():
    """It is a public page; nobody gets to run the suite in a tight loop."""
    checks.start(web.load_score, runner=fake_tests)
    settle()
    started, reason = checks.start(web.load_score, runner=fake_tests)
    assert not started and reason.startswith("wait")


def test_a_broken_check_is_reported_rather_than_hanging():
    def boom(update):
        raise RuntimeError("pytest could not start")
    checks.start(web.load_score, runner=boom)
    settle()
    s = checks.status()
    assert s["state"] == "error" and "pytest could not start" in s["error"]


# --- the endpoints -------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(checks, "_run_tests", fake_tests)   # never spawn pytest inside pytest
    return TestClient(web.app)


def test_run_starts_in_the_background_and_status_reports_it(client):
    r = client.post("/tests/run")
    assert r.status_code == 202 and r.json()["started"] is True
    settle()
    s = client.get("/tests/status").json()
    assert s["state"] == "passed" and s["tests"]["passed"] == 302


def test_a_second_run_during_the_cooldown_is_refused(client):
    client.post("/tests/run")
    settle()
    r = client.post("/tests/run")
    assert r.status_code == 429 and r.json()["reason"].startswith("wait")


def test_the_page_has_the_button_and_the_two_figures(client):
    html = client.get("/tests").text
    assert 'id="run-checks"' in html
    for figure in ("accuracy", "emails checked"):
        assert figure in html


def test_the_test_suite_runs_but_its_count_is_not_shown(client):
    """The count of automated tests read as a count of emails next to the
    520, so the page no longer shows it: no figure, no square per test, no
    time taken. The suite still runs with every check."""
    html = client.get("/tests").text
    for gone in ("tests passed", 'id="wall"', "square", "test suite took", 'id="f-tests"'):
        assert gone not in html, gone
    # The row stays in the page, hidden, for the one case it must speak: a failure.
    assert '<li class="step" data-step="tests" data-n="3" hidden' in html
    client.post("/tests/run")
    settle()
    assert client.get("/tests/status").json()["tests"]["passed"] == 302


def test_nothing_is_shown_until_a_run_finishes(client):
    """Even with a finished run in memory, the page opens on the button: the
    results appear when the visitor's own run completes."""
    client.post("/tests/run")
    settle()
    html = client.get("/tests").text
    assert '<div class="results" id="results" hidden>' in html
    assert '<div class="figs" id="figs" hidden>' in html
