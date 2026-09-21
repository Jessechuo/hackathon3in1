import json

import pytest
from fastapi.testclient import TestClient

from sdoc.web import app as web

# Deliberately imperfect. With every number 1.0, a precision computed as
# recall - or a matrix drawn transposed - would render identically.
SCORE = {
    "stage1": {
        "accuracy": 0.9, "macro_f1": 0.85, "rule_pct": None,
        "per": {
            "BL_COMPARISON": {"tp": 8, "fp": 2, "fn": 0},
            "SI_REQUEST":    {"tp": 3, "fp": 0, "fn": 1},
            "INVOICE_QUERY": {"tp": 5, "fp": 0, "fn": 0},
            "GENERAL":       {"tp": 4, "fp": 0, "fn": 1},
            "SPAM":          {"tp": 2, "fp": 0, "fn": 0},
        },
        # actual -> predicted -> n
        "confusion": {
            "BL_COMPARISON": {"BL_COMPARISON": 8},
            "SI_REQUEST":    {"SI_REQUEST": 3, "BL_COMPARISON": 1},
            "INVOICE_QUERY": {"INVOICE_QUERY": 5},
            "GENERAL":       {"GENERAL": 4, "BL_COMPARISON": 1},
            "SPAM":          {"SPAM": 2},
        },
    },
    "stage3": {"defect_precision": 0.75, "defect_recall": 1.0, "defect_f1": 0.857,
               "field_f1": 0.9, "exact_match_rate": 0.8, "doc_total": 12},
    "reliability": {"escalation_recall": 0.5, "escalation_precision": 1.0,
                    "escalation_f1": 0.667, "gold_review": 4, "pred_review": 2,
                    "per_reason": {"unreadable": {"total": 2, "caught": 1},
                                   "missing_value": {"total": 2, "caught": 1}}},
    "end_to_end": {"success": 3, "total": 4, "rate": 0.75},
    "weights": {"stage1": 0.3, "stage3": 0.2, "end_to_end": 0.5},
    "final_score": 0.8015,
    "n_emails": 25,
}


# --- shaping the scorer's output -----------------------------------------

def test_precision_and_recall_come_from_the_right_counts():
    cats = {c["name"]: c for c in web.score_view(SCORE)["categories"]}
    bl = cats["BL_COMPARISON"]
    assert bl["precision"] == pytest.approx(0.8)    # 8 / (8 + 2 false positives)
    assert bl["recall"] == pytest.approx(1.0)       # 8 / (8 + 0 missed)
    assert bl["f1"] == pytest.approx(2 * 0.8 * 1.0 / 1.8)
    si = cats["SI_REQUEST"]
    assert si["precision"] == pytest.approx(1.0) and si["recall"] == pytest.approx(0.75)
    assert (si["correct"], si["total"]) == (3, 4)


def test_categories_keep_their_fixed_order_whatever_they_score():
    """A category keeps its row; ranking by score would move them around."""
    names = [c["name"] for c in web.score_view(SCORE)["categories"]]
    assert names == ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]


def test_the_confusion_matrix_is_rows_actual_columns_predicted():
    matrix = web.score_view(SCORE)["matrix"]
    si = next(r for r in matrix if r["actual"] == "SI_REQUEST")
    cell = next(c for c in si["cells"] if c["predicted"] == "BL_COMPARISON")
    assert cell["n"] == 1 and not cell["hit"]        # one SI email called a BL check
    assert cell["share"] == pytest.approx(0.25)       # 1 of the 4 actual SI emails


def test_misclassifications_are_counted_off_the_diagonal():
    assert web.score_view(SCORE)["off_diagonal"] == 2


def test_the_parts_add_up_to_their_weighted_contributions():
    parts = {p["name"]: p for p in web.score_view(SCORE)["parts"]}
    assert parts["Stage 1"]["contributes"] == pytest.approx(0.3 * 0.85)
    assert parts["Stage 3"]["contributes"] == pytest.approx(0.2 * 0.857)
    assert parts["End-to-end"]["contributes"] == pytest.approx(0.5 * 0.75)
    assert parts["End-to-end"]["count"] == "3 / 4"


def test_empty_counts_do_not_divide_by_zero():
    blank = dict(SCORE, stage1=dict(SCORE["stage1"],
                                    per={"SPAM": {"tp": 0, "fp": 0, "fn": 0}}, confusion={}))
    spam = next(c for c in web.score_view(blank)["categories"] if c["name"] == "SPAM")
    assert spam["precision"] == spam["recall"] == spam["f1"] == 0.0


# --- where the score is read from ----------------------------------------

def test_the_copy_that_ships_with_the_code_is_read_first(tmp_path, monkeypatch):
    """On a deploy OUT_DIR is a volume seeded once and never overwritten, so a
    re-scored file committed later would never reach it."""
    shipped, volume = tmp_path / "root", tmp_path / "volume"
    (shipped / "out").mkdir(parents=True)
    volume.mkdir()
    (shipped / "out" / "score.json").write_text(json.dumps({"final_score": 0.9}))
    (volume / "score.json").write_text(json.dumps({"final_score": 0.1}))
    monkeypatch.setattr(web, "ROOT", shipped)
    monkeypatch.setattr(web, "OUT_DIR", volume)
    assert web.load_score()["final_score"] == 0.9


def test_no_score_file_means_none(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ROOT", tmp_path / "nothing")
    monkeypatch.setattr(web, "OUT_DIR", tmp_path / "nothing-either")
    assert web.load_score() is None


# --- the page ------------------------------------------------------------

@pytest.fixture
def site(tmp_path, monkeypatch):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "score.json").write_text(json.dumps(SCORE))
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "OUT_DIR", tmp_path / "out")
    return TestClient(web.app)


def test_the_page_leads_with_the_final_score(site):
    html = site.get("/tests").text
    assert "Final score" in html
    assert "0.8015" in html and "80%" in html


def test_the_page_shows_every_part_of_the_scoreboard(site):
    flat = " ".join(site.get("/tests").text.split())
    for heading in ("Stage 1 · Email classification", "Confusion matrix",
                    "Stage 3 · SI vs BL comparison", "Reliability", "End-to-end"):
        assert heading in flat, heading
    assert "2 emails off the diagonal" in flat       # the imperfect run says so
    assert "3 / 4" in flat                             # end-to-end count


def test_every_value_is_printed_not_left_to_colour(site):
    """A meter's width is decoration; the number beside it is the value."""
    html = site.get("/tests").text
    assert 'role="meter"' in html
    assert "0.750" in html                            # defect precision, in ink


def test_the_page_says_the_score_is_not_held_out(site):
    flat = " ".join(site.get("/tests").text.split())
    assert "Not a held-out result" in flat


def test_with_no_score_the_page_says_how_to_make_one(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ROOT", tmp_path / "nothing")
    monkeypatch.setattr(web, "OUT_DIR", tmp_path / "nothing-either")
    html = TestClient(web.app).get("/tests").text
    assert "score_cli.py" in html
    assert "Final score" not in html


def test_the_rail_links_to_it(site):
    rail = site.get("/").text.split('<aside class="rail"', 1)[1].split("</aside>", 1)[0]
    assert 'href="/tests"' in rail and "Test results" in rail
