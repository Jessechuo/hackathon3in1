import json

import pytest
from fastapi.testclient import TestClient

from sdoc.web import app as web


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUT_DIR", tmp_path)

    def write(data):
        (tmp_path / "results.json").write_text(json.dumps(data), encoding="utf-8")

    return TestClient(web.app), write


def test_detail_page_shows_si_and_bl_side_by_side(site):
    client, write = site
    write({"email_043": {
        "category": "BL_COMPARISON", "reason": "x", "status": "MISMATCH", "review_reason": None,
        "has_defect": True, "defect_fields": ["container_count"], "note": None,
        "fields": [{"name": "container_count", "si": "3 x 20'GP", "bl": "5 x 20'GP", "match": False}],
    }})
    html = client.get("/email/email_043").text
    assert "3 x 20&#39;GP" in html and "5 x 20&#39;GP" in html
    assert "cmp-table" in html


def test_verification_status_only_shown_for_bl_emails(site):
    client, write = site
    write({"email_002": {"category": "INVOICE_QUERY", "reason": "x", "status": "OK"}})
    html = client.get("/").text
    row = html.split('data-id="email_002"')[1].split("</tr>")[0]
    assert 'class="status' not in row


def test_status_filter_shows_only_that_status(site):
    client, write = site
    write({"email_001": {"category": "BL_COMPARISON", "status": "OK"},
           "email_004": {"category": "BL_COMPARISON", "status": "MISMATCH"}})
    html = client.get("/?status=MISMATCH").text
    assert 'data-id="email_004"' in html and 'data-id="email_001"' not in html


def test_the_content_is_pushed_down_by_the_headers_real_height(site):
    """The filter pills wrap on a narrow window, so the header is taller than
    48px there. A constant offset hid whatever sat at the top of the page."""
    client, _ = site
    html = client.get("/").text
    assert "min-height:var(--head)" in html      # the header may grow
    assert 'setProperty("--head"' in html        # and the offset follows it
    assert "ResizeObserver" in html


def test_no_bare_element_selector_can_clobber_the_avatar(site):
    """`.acct-id span` also matched the avatar beside the address and beat
    .avatar on specificity, so the initial fell out of its circle."""
    client, _ = site
    html = client.get("/").text
    assert ".acct-id span" not in html          # the selector that did it
    assert ".acct-id .addr" in html             # named, so it hits one thing


def test_the_rail_offers_only_what_works(site):
    """Disabled 'not built yet' icons are a promise the app does not keep,
    sitting beside the links that do work."""
    client, _ = site
    html = client.get("/").text
    rail = html.split('<aside class="rail"', 1)[1].split("</aside>", 1)[0]
    assert "not built yet" not in rail
    assert rail.count("<a ") == 4            # overview, queue, send, test results
    for href in ('href="/dashboard"', 'href="/"', 'href="/compose"', 'href="/tests"'):
        assert href in rail


def test_the_rail_can_be_widened_to_show_labels(site):
    """<|> at the bottom of the rail widens it to show labels, and folds it
    back. Its state is restored before first paint, or an open panel would
    render closed and jump open on every page."""
    client, _ = site
    html = client.get("/").text
    rail = html.split('<aside class="rail"', 1)[1].split("</aside>", 1)[0]
    assert 'id="rail-toggle"' in rail
    assert 'href="#i-diff"' in rail                       # the <|> icon
    assert 'aria-expanded="false"' in rail
    for label in ("Overview", "Triage Queue", "Send an email"):
        assert f'<span class="rail-lbl">{label}</span>' in rail
    head = html.split("</head>", 1)[0]
    assert 'localStorage.getItem("sdoc-rail")' in head    # restored before paint
    assert 'html[data-rail="open"] { --rail:200px; }' in html
