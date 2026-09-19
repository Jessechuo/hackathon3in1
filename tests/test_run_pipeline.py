import subprocess
import sys

from sdoc import run_pipeline


def test_cli_starts_and_lists_its_options():
    out = subprocess.run([sys.executable, "-m", "sdoc.run_pipeline", "--help"],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0
    for flag in ("--only", "--limit", "--workers"):
        assert flag in out.stdout


def test_a_crash_becomes_a_review_case_not_a_missing_email(monkeypatch):
    def boom(email, cls):
        raise RuntimeError("api down")

    monkeypatch.setattr(run_pipeline, "process", boom)
    eid, r = run_pipeline.run_one({"email_id": "email_009"},
                                  {"category": "BL_COMPARISON", "reason": "x"})
    assert eid == "email_009"
    assert (r["status"], r["review_reason"], r["failed"]) == ("NEEDS_REVIEW", "unreadable", True)
    assert "api down" in r["error"]


def test_run_keeps_earlier_results_for_emails_not_in_this_run(monkeypatch):
    monkeypatch.setattr(run_pipeline, "process",
                        lambda e, c: {"category": c["category"], "status": "OK"})
    previous = {"email_001": {"category": "BL_COMPARISON", "status": "MISMATCH"}}
    out = run_pipeline.run([{"email_id": "email_002"}], {"email_002": {"category": "SPAM"}},
                           previous, workers=1)
    assert out["email_001"]["status"] == "MISMATCH"
    assert out["email_002"]["category"] == "SPAM"
