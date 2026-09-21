"""Clicking an attachment opens it in a window over the email page: the SI
and BL side by side, the compared values marked in each, and a button for
the original file. It used to open a bare page of text."""
import json

import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.mail import store
from sdoc.web import app as web

SI_TEXT = (b"SHIPPER: ACME LOGISTICS PTE LTD\nCONSIGNEE: NORDIC IMPORTS AB\n"
           b"POL: SINGAPORE\nPOD: HAMBURG\n")

RESULTS = {
    "email_004": {"category": "BL_COMPARISON", "status": "MISMATCH", "has_defect": True,
                  "defect_fields": ["container_count"], "note": None, "fields": [
                      {"name": "shipper", "si": "ACME", "bl": "ACME", "match": True},
                      {"name": "notify_party", "si": None, "bl": "SAME AS CONSIGNEE", "match": None},
                      {"name": "container_count", "si": "3 x 20'GP", "bl": "5 x 20'GP", "match": False}]},
    "email_002": {"category": "INVOICE_QUERY", "reason": "About an invoice"},
}


@pytest.fixture
def site(tmp_path, monkeypatch):
    out, mail = tmp_path / "out", tmp_path / "mail"
    out.mkdir()
    (out / "results.json").write_text(json.dumps(RESULTS), encoding="utf-8")
    monkeypatch.setattr(web, "OUT_DIR", out)
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)
    return TestClient(web.app), mail


# --- what the window reads -------------------------------------------------

def test_the_window_gets_the_text_the_system_read(site):
    client, mail = site
    store.save_email("a@b.com", "s", "b", [("SI.txt", SI_TEXT)], root=mail)
    r = client.get("/attachment/mail/attachments/mail_0001__SI.txt?view=json")
    assert r.status_code == 200
    assert r.json() == {"name": "mail_0001__SI.txt", "text": SI_TEXT.decode(),
                        "readable": True, "problem": None}


def test_a_file_that_cannot_be_read_says_why_in_the_page_language(site):
    client, mail = site
    store.save_email("a@b.com", "s", "b", [("BL.txt", b"   ")], root=mail)
    path = "/attachment/mail/attachments/mail_0001__BL.txt?view=json"
    assert client.get(path).json()["problem"] == "file is empty"
    client.cookies.set("mailops-lang", "zh")
    body = client.get(path).json()
    assert body["readable"] is False and body["problem"] not in (None, "file is empty")


@pytest.mark.parametrize("problem,pattern", [
    ("unsupported file type .rtf", "unsupported file type {suffix}"),
    ("file is corrupt or cannot be opened (BadZipFile)", "file is corrupt or cannot be opened ({error})"),
    ("no text layer - looks like a scanned image", "no text layer - looks like a scanned image"),
])
def test_every_reason_a_file_is_unreadable_is_translated(problem, pattern):
    from sdoc.web import i18n
    token = i18n.use("ms")
    try:
        said = web.say_problem(problem)
    finally:
        i18n.reset(token)
    assert said != problem and said
    for detail in (".rtf", "BadZipFile"):               # the detail is kept, whatever the language
        if detail in problem:
            assert detail in said
    assert pattern in i18n.TABLE


def test_the_list_of_reasons_matches_the_reader_word_for_word():
    """A reason reworded in sdoc.extract would quietly lose its translation."""
    import re
    from pathlib import Path
    import sdoc.extract
    source = Path(sdoc.extract.__file__).read_text(encoding="utf-8")
    plain = set(re.findall(r'False,\s*"([^"]+)"\)', source))
    assert plain == set(web.UNREADABLE)


# --- the original file -----------------------------------------------------

def test_open_original_shows_a_pdf_in_the_browser():
    r = TestClient(web.app).get("/attachment/attachments/email_059_SI.pdf?view=original")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.content.startswith(b"%PDF")


def test_open_original_shows_a_text_file_as_text(site):
    client, mail = site
    store.save_email("a@b.com", "s", "b", [("SI.txt", SI_TEXT)], root=mail)
    r = client.get("/attachment/mail/attachments/mail_0001__SI.txt?view=original")
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.content == SI_TEXT


def test_any_other_kind_of_file_is_downloaded_never_shown(site):
    """Received attachments come from anyone who emails the inbox. An .html
    one shown by the browser would run as part of this site."""
    client, mail = site
    store.save_email("a@b.com", "s", "b", [("BL.html", b"<script>alert(1)</script>")], root=mail)
    r = client.get("/attachment/mail/attachments/mail_0001__BL.html?view=original")
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("view", ["json", "original", ""])
def test_the_folder_guard_covers_every_view(site, view):
    client, _ = site
    for bad in ("mail/../secrets.txt", "out/ground_truth.json", "mail/inbox/mail_0001.json"):
        assert client.get(f"/attachment/{bad}?view={view}").status_code == 400, bad
    assert client.get(f"/attachment/mail/attachments/nope.txt?view={view}").status_code == 404


# --- the window on the email page ------------------------------------------

def test_the_email_page_has_the_window_and_says_which_file_is_which(site):
    client, _ = site
    html = client.get("/email/email_004").text
    assert '<dialog class="viewer" id="viewer"' in html
    assert 'data-role="SI" href="/attachment/attachments/email_004_SI.txt"' in html
    assert 'data-role="BL" href="/attachment/attachments/email_004_BL.txt"' in html


def test_the_window_knows_which_values_to_mark_and_how(site):
    client, _ = site
    html = client.get("/email/email_004").text
    marks = json.loads(html.split("var MARKS = ", 1)[1].split(";\n", 1)[0])
    assert marks == [
        {"name": "shipper", "si": "ACME", "bl": "ACME", "state": "ok"},
        {"name": "notify_party", "si": None, "bl": "SAME AS CONSIGNEE", "state": "miss"},
        {"name": "container_count", "si": "3 x 20'GP", "bl": "5 x 20'GP", "state": "bad"},
    ]


def test_a_reviewers_decision_colours_the_marks_too(site, tmp_path):
    client, _ = site
    (tmp_path / "out" / "review.json").write_text(json.dumps({"email_004": {
        "decision": "mismatch", "fields": ["shipper"], "at": "2026-09-21T10:00:00+00:00"}}))
    html = client.get("/email/email_004").text
    marks = json.loads(html.split("var MARKS = ", 1)[1].split(";\n", 1)[0])
    assert {m["name"]: m["state"] for m in marks}["shipper"] == "bad"


def test_an_email_that_is_not_compared_has_nothing_to_mark(site):
    client, _ = site
    html = client.get("/email/email_002").text
    assert "var MARKS = [];" in html


def test_escape_closes_the_window_before_it_leaves_the_email(site):
    """The page's own Esc goes back to the inbox. With the window open, Esc
    belongs to the window."""
    client, _ = site
    # The last keydown listener is the email page's; base.html has its own.
    script = client.get("/email/email_004").text.rsplit('document.addEventListener("keydown"', 1)[1]
    first_line = script.split("{", 1)[1].lstrip()
    assert first_line.startswith("if (viewer.open) return;")
