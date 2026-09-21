"""submission.json as a CSV file, downloaded from the Test results page."""
import csv
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from sdoc import pipeline
from sdoc.web import app as web

REAL = json.loads((Path(web.ROOT) / "out" / "submission.json").read_text(encoding="utf-8"))
SUB = {
    "email_002": {"category": "INVOICE_QUERY", "status": "OK", "review_reason": None,
                  "has_defect": False, "defect_fields": []},
    "email_001": {"category": "BL_COMPARISON", "status": "MISMATCH", "review_reason": None,
                  "has_defect": True, "defect_fields": ["port_of_discharge", "consignee"]},
    "email_003": {"category": "BL_COMPARISON", "status": "NEEDS_REVIEW", "review_reason": "unreadable",
                  "has_defect": False, "defect_fields": []},
}


def read_back(text: str) -> dict:
    """The CSV parsed back into submission.json's shape."""
    rows = csv.DictReader(io.StringIO(text))
    return {r["email_id"]: {
        "category": r["category"],
        "status": r["status"],
        "review_reason": r["review_reason"] or None,
        "has_defect": r["has_defect"] == "true",
        "defect_fields": r["defect_fields"].split(";") if r["defect_fields"] else [],
    } for r in rows}


def test_one_row_per_email_with_the_same_five_fields():
    text = pipeline.submission_csv(SUB)
    lines = text.splitlines()
    assert lines[0] == "email_id,category,status,review_reason,has_defect,defect_fields"
    assert lines[1:] == [                     # in email_id order
        "email_001,BL_COMPARISON,MISMATCH,,true,port_of_discharge;consignee",
        "email_002,INVOICE_QUERY,OK,,false,",
        "email_003,BL_COMPARISON,NEEDS_REVIEW,unreadable,false,",
    ]


def test_the_csv_reads_back_as_exactly_the_submission():
    assert read_back(pipeline.submission_csv(SUB)) == SUB
    assert read_back(pipeline.submission_csv(REAL)) == REAL


def test_the_real_export_has_all_520_graded_emails_and_no_live_mail():
    ids = list(read_back(pipeline.submission_csv(REAL)))
    assert len(ids) == 520 and not any(i.startswith("mail_") for i in ids)


def test_the_page_offers_the_download_beside_run_live_checks():
    html = TestClient(web.app).get("/tests").text
    actions = html.split('<div class="stage-act">', 1)[1].split("</div>", 1)[0]
    assert 'id="run-checks"' in actions
    assert 'href="/tests/export.csv"' in actions and "Export CSV" in actions


def test_the_download_is_the_graded_submission_as_a_csv_file():
    r = TestClient(web.app).get("/tests/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="mailops_submission.csv"' in r.headers["content-disposition"]
    assert read_back(r.text) == REAL


def test_the_download_needs_a_sign_in_like_the_rest_of_the_site(monkeypatch):
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "1")
    r = TestClient(web.app).get("/tests/export.csv", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_without_a_submission_the_download_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ROOT", tmp_path / "nothing")
    monkeypatch.setattr(web, "OUT_DIR", tmp_path / "nothing-either")
    r = TestClient(web.app).get("/tests/export.csv")
    assert r.status_code == 404
