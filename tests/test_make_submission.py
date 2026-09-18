from tools import make_submission


def test_every_id_is_present_even_when_unclassified():
    """A missing key is an invalid submission. Ids absent from
    categories.json must still appear, defaulted."""
    categories = {"email_001": {"category": "SPAM", "reason": "x", "error": None}}
    all_ids = ["email_001", "email_002", "email_003"]

    result = make_submission.build(categories, all_ids)

    assert set(result) == {"email_001", "email_002", "email_003"}
    assert result["email_001"]["category"] == "SPAM"
    assert result["email_002"]["category"] == "GENERAL"


def test_shape_matches_the_scorer_contract():
    categories = {"email_001": {"category": "BL_COMPARISON", "reason": "x", "error": None}}
    result = make_submission.build(categories, ["email_001"])

    assert result["email_001"] == {
        "category": "BL_COMPARISON",
        "status": "OK",
        "review_reason": None,
        "has_defect": False,
        "defect_fields": [],
    }
