import json

import pytest
from fastapi.testclient import TestClient

from sdoc.web import app as web

RESULTS = {
    "email_001": {"category": "BL_COMPARISON", "status": "MISMATCH",
                  "defect_fields": ["container_count", "gross_weight_kg"]},
    "email_002": {"category": "BL_COMPARISON", "status": "MISMATCH",
                  "defect_fields": ["container_count"]},
    "email_003": {"category": "BL_COMPARISON", "status": "NEEDS_REVIEW", "defect_fields": []},
    "email_004": {"category": "BL_COMPARISON", "status": "OK", "defect_fields": []},
    "email_005": {"category": "SPAM", "status": "OK", "defect_fields": []},
    "email_006": {"category": "SPAM", "status": "OK", "defect_fields": []},
}


def test_stats_count_the_things_that_need_attention():
    s = web.dashboard_stats(RESULTS, review={"email_001": {"decision": "verified"},
                                             "email_006": {"decision": "verified"}})
    assert s["total"] == 6
    # a reviewer cleared email_001, so only email_002 is still a mismatch
    assert s["mismatches"] == 1
    assert s["needs_review"] == 1
    # 'attention' is what the SYSTEM flagged: the denominator for human work
    assert s["attention"] == 3
    # email_006 is SPAM, so a decision on it is not a decision on flagged work
    assert s["decided"] == 1


def test_a_reviewers_fields_replace_the_systems_in_the_bar_list():
    s = web.dashboard_stats(RESULTS, review={"email_002": {"decision": "mismatch",
                                                           "fields": ["shipper"]}})
    assert [(r["label"], r["count"]) for r in s["by_field"]] == [
        ("container_count", 1), ("gross_weight_kg", 1), ("shipper", 1)]


def test_category_rows_are_ranked_and_scaled_to_the_largest():
    rows = web.dashboard_stats(RESULTS, review={})["by_category"]
    assert [(r["label"], r["count"]) for r in rows] == [("BL_COMPARISON", 4), ("SPAM", 2)]
    assert rows[0]["width"] == 100 and rows[1]["width"] == 50
    assert rows[0]["href"] == "/?category=BL_COMPARISON"


def test_field_rows_count_each_mismatched_field():
    rows = web.dashboard_stats(RESULTS, review={})["by_field"]
    assert [(r["label"], r["count"]) for r in rows] == [("container_count", 2), ("gross_weight_kg", 1)]


def test_stats_before_the_comparison_has_run():
    cats_only = {"email_001": {"category": "BL_COMPARISON"}, "email_002": {"category": "SPAM"}}
    s = web.dashboard_stats(cats_only, review={})
    assert s["has_comparison"] is False
    assert s["mismatches"] == 0 and s["by_field"] == []


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUT_DIR", tmp_path)
    return TestClient(web.app), tmp_path


def test_dashboard_page_links_every_card_into_the_inbox(site):
    client, tmp = site
    (tmp / "results.json").write_text(json.dumps(RESULTS), encoding="utf-8")
    html = client.get("/dashboard").text
    assert "stat-tile" in html
    for href in ('href="/"', 'href="/?status=MISMATCH"', 'href="/?status=NEEDS_REVIEW"'):
        assert href in html
    assert "Emails by category" in html and "Most common mismatches" in html


def test_dashboard_without_results_explains_what_to_run(site):
    client, _ = site
    html = client.get("/dashboard").text
    assert "python -m sdoc.run_pipeline" in html


def test_rail_links_to_the_dashboard(site):
    client, _ = site
    assert 'href="/dashboard"' in client.get("/").text


# --- the mismatch card and the field bars must reconcile -------------------

def test_the_field_bars_reconcile_with_the_mismatch_count():
    """The card counts emails, the bars count fields, and one email can be
    wrong in more than one field - 2 emails here, 3 wrong fields. The split
    by fields-per-email is what makes both numbers add up."""
    s = web.dashboard_stats(RESULTS, review={})
    assert s["mismatches"] == 2
    assert s["wrong_fields"] == sum(r["count"] for r in s["by_field"]) == 3
    assert [(w["fields"], w["emails"]) for w in s["by_width"]] == [(1, 1), (2, 1)]
    assert sum(w["emails"] for w in s["by_width"]) == s["mismatches"]
    assert sum(w["fields"] * w["emails"] for w in s["by_width"]) == s["wrong_fields"]


def test_the_dashboard_says_how_emails_and_fields_add_up(site):
    client, tmp = site
    (tmp / "results.json").write_text(json.dumps(RESULTS), encoding="utf-8")
    flat = " ".join(client.get("/dashboard").text.split())
    assert "<b>2</b> mismatch emails" in flat
    assert "<b>3</b> wrong fields" in flat
    assert "1 × 1 + 1 × 2" in flat
