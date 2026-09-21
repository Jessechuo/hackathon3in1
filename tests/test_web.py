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


# --- combining the header filters ----------------------------------------

BL_MIX = {"email_001": {"category": "BL_COMPARISON", "status": "OK"},
          "email_004": {"category": "BL_COMPARISON", "status": "MISMATCH"},
          "email_002": {"category": "INVOICE_QUERY", "reason": "x"}}


def header(html):
    return html.split('<div class="filters">', 1)[1].split('<div class="head-right">', 1)[0]


@pytest.mark.parametrize("args,href", [
    ((), "/"),
    (("BL_COMPARISON",), "/?category=BL_COMPARISON"),
    (("BL_COMPARISON", "OK"), "/?category=BL_COMPARISON&status=OK"),
    ((None, "MISMATCH"), "/?status=MISMATCH"),
    (("BL_COMPARISON", None, True), "/?category=BL_COMPARISON&reviewed=1"),
    # A status belongs to document checks only - it never follows elsewhere.
    (("SPAM", "OK"), "/?category=SPAM"),
    (("GENERAL", None, True), "/?category=GENERAL"),
])
def test_filter_links_are_built_from_every_active_filter(args, href):
    assert web.filter_href(*args) == href


def test_on_bl_comparison_the_status_buttons_keep_the_category(site):
    client, write = site
    write(BL_MIX)
    bar = header(client.get("/?category=BL_COMPARISON").text)
    assert 'href="/?category=BL_COMPARISON&amp;status=OK"' in bar
    assert 'href="/?category=BL_COMPARISON&amp;status=MISMATCH"' in bar
    assert 'href="/?category=BL_COMPARISON&amp;reviewed=1"' in bar
    assert 'href="/?category=BL_COMPARISON" aria-pressed="true">Status: All' in bar


def test_with_a_status_chosen_the_category_buttons_keep_it(site):
    client, write = site
    write(BL_MIX)
    bar = header(client.get("/?category=BL_COMPARISON&status=MISMATCH").text)
    assert 'href="/?status=MISMATCH"' in bar                          # All keeps the status
    assert 'href="/?category=BL_COMPARISON&amp;status=MISMATCH"' in bar
    assert 'href="/?category=SPAM"' in bar                            # nothing to keep there


def test_both_filters_apply_together(site):
    client, write = site
    write(BL_MIX)
    html = client.get("/?category=BL_COMPARISON&status=OK").text
    assert 'data-id="email_001"' in html
    assert 'data-id="email_004"' not in html and 'data-id="email_002"' not in html


def test_on_another_category_the_status_buttons_say_why_they_are_off(site):
    client, write = site
    write(BL_MIX)
    bar = header(client.get("/?category=INVOICE_QUERY").text)
    assert "?status=" not in bar and "reviewed=1" not in bar
    assert bar.count('title="Only BL_COMPARISON emails have a status"') == 3


def test_the_content_is_pushed_down_by_the_headers_real_height(site):
    """The filter pills wrap on a narrow window, so the header is taller than
    48px there. A constant offset hid whatever sat at the top of the page."""
    client, _ = site
    html = client.get("/").text
    assert 'setProperty("--head"' in html        # the offset follows the header
    assert "ResizeObserver" in html


def test_the_header_height_cannot_feed_back_into_itself(site):
    """With min-height:var(--head) and --head set from the header's own height,
    each held the other up: once the header grew it could never shrink, and it
    was found stuck at 339px around 28px of content. The floor is a constant."""
    client, _ = site
    html = client.get("/").text
    import re
    header_rule = html.split("header.app {", 1)[1].split("}", 1)[0]
    header_rule = re.sub(r"/\*.*?\*/", "", header_rule, flags=re.S)   # rules, not comments
    assert "min-height:var(--head)" not in header_rule
    assert "min-height:48px" in header_rule


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


# --- on a phone ------------------------------------------------------------

def phone_rules(html):
    """The CSS that applies below 720px, in one string."""
    return " ".join(part.split("\n}\n", 1)[0] for part in html.split("@media (max-width:720px)")[1:])


def test_on_a_phone_the_panel_is_a_bottom_tab_bar_and_the_filters_one_row(site):
    """Wrapped, the eleven filter buttons stacked five rows deep and took a
    quarter of a phone screen; the side panel took width it does not have."""
    client, _ = site
    html = client.get("/").text
    assert "viewport-fit=cover" in html                       # room for the home bar
    phone = phone_rules(html)
    assert ':root, html[data-rail="open"] { --rail:0px; }' in phone
    assert "top:auto; bottom:0;" in phone                     # the rail, along the bottom
    assert "flex-wrap:nowrap; overflow-x:auto;" in phone      # filters swipe, never wrap
    assert "font-size:16px !important" in phone               # no iOS zoom into fields


def test_on_a_phone_categories_and_statuses_are_two_rows(site):
    """One row per kind of filter, each scrolling on its own. On a wider
    screen the groups are display:contents, so the buttons flow as before."""
    client, write = site
    write(BL_MIX)
    html = client.get("/").text
    groups = header(html).split('<div class="fgroup">')[1:]
    assert len(groups) == 2
    cats, statuses = groups
    assert "BL_COMPARISON" in cats and "SPAM" in cats and "Status: All" not in cats
    assert "Status: All" in statuses and "MISMATCH" in statuses and "Reviewed" in statuses
    assert ".fgroup { display:contents; }" in html
    phone = phone_rules(html)
    assert ".filters > .vr { display:none; }" in phone
    assert "flex-direction:column" in phone


def test_the_filter_row_shows_only_on_the_queue(site):
    client, _ = site
    assert '<header class="app" data-page="inbox">' in client.get("/").text
    assert '<header class="app" data-page="email">' in client.get("/email/email_001").text
    assert 'header.app:not([data-page="inbox"]) .filters { display:none; }' in client.get("/").text


def test_on_a_phone_each_email_is_a_card_not_a_940px_row(site):
    client, write = site
    write({"email_001": {"category": "BL_COMPARISON", "status": "OK"}})
    html = client.get("/").text
    row = html.split('data-id="email_001"', 1)[1].split("</tr>", 1)[0]
    for cell in ('class="id"', 'class="cat"', 'class="ver"', 'class="subject"', 'class="from"', 'class="att"'):
        assert cell in row, cell                              # every cell has a grid area
    phone = phone_rules(html)
    assert "min-width:0;" in phone and "thead { display:none; }" in phone


def test_on_a_phone_the_comparison_keeps_si_and_bl_side_by_side(site):
    """As four table columns the values broke mid-word: "PACIF / IC"."""
    client, write = site
    write({"email_043": {
        "category": "BL_COMPARISON", "reason": "x", "status": "MISMATCH", "review_reason": None,
        "has_defect": True, "defect_fields": ["container_count"], "note": None,
        "fields": [{"name": "container_count", "si": "3 x 20'GP", "bl": "5 x 20'GP", "match": False}],
    }})
    html = client.get("/email/email_043").text
    assert 'class="si" data-l="SI"' in html and 'class="bl" data-l="BL"' in html
    assert 'grid-template-areas:"fn fn mk" "si bl bl"' in phone_rules(html)
    # prev/next sit outside the review buttons, so a phone can put them by "Inbox"
    acts = html.split('<div class="acts">', 1)[1].split("</div>", 1)[0]
    assert 'class="pager"' not in acts
