import pytest

from sdoc import pipeline
from sdoc.ai.extract_pair import PairExtraction
from sdoc.core.fields import ShipmentFields
from sdoc.extract import DocText


def fields(**over):
    base = dict(
        shipper="APRIL FAR EAST (M) SDN BHD", consignee="MOORIM SP CO., LTD",
        notify_party="UAB NOVAKOPA", port_of_loading="PORT KLANG (WESTPORT), MALAYSIA (MYPKG)",
        port_of_discharge="CALLAO, PERU (PECLL)", container_count="1 x 40'HC",
        gross_weight_kg="21,577 KG",
    )
    base.update(over)
    return ShipmentFields(**base)


BL = {"category": "BL_COMPARISON", "reason": "check", "documents_meant_to_be_attached": True}
TWO = {"email_id": "email_900",
       "attachments": ["attachments/email_900_SI.txt", "attachments/email_900_BL.txt"]}


@pytest.fixture
def readable(monkeypatch):
    monkeypatch.setattr(pipeline, "read_document", lambda p: DocText(p, "some text " * 20, True))


def use_pair(monkeypatch, si=None, bl=None, si_type="SHIPPING_INSTRUCTION", bl_type="BILL_OF_LADING"):
    si, bl = si or fields(), bl or fields()
    # English documents: the English forms are the values themselves.
    pair = PairExtraction(si_doc_type=si_type, bl_doc_type=bl_type,
                          si=si, bl=bl, si_en=si, bl_en=bl)
    monkeypatch.setattr(pipeline, "extract_pair", lambda s, b: pair)


def test_other_categories_pass_through():
    r = pipeline.process({"email_id": "e", "attachments": []}, {"category": "SPAM", "reason": "scam"})
    assert (r["category"], r["status"], r["review_reason"], r["defect_fields"]) == ("SPAM", "OK", None, [])


def test_no_attachments_and_none_promised_is_ok():
    r = pipeline.process({"email_id": "e", "attachments": []}, {**BL, "documents_meant_to_be_attached": False})
    assert (r["status"], r["review_reason"]) == ("OK", None)


def test_no_attachments_but_promised_is_missing_attachment():
    r = pipeline.process({"email_id": "e", "attachments": []}, BL)
    assert (r["status"], r["review_reason"]) == ("NEEDS_REVIEW", "missing_attachment")


def test_only_one_attachment_is_missing_attachment():
    r = pipeline.process({"email_id": "e", "attachments": ["attachments/e_SI.txt"]}, BL)
    assert r["review_reason"] == "missing_attachment" and "draft BL" in r["note"]


def test_unreadable_file_escalates(monkeypatch):
    monkeypatch.setattr(pipeline, "read_document",
                        lambda p: DocText(p, "", False, "file is empty") if p.endswith("_BL.txt")
                        else DocText(p, "x" * 80, True))
    r = pipeline.process(TWO, BL)
    assert r["review_reason"] == "unreadable" and "file is empty" in r["note"]


def test_wrong_document_type_is_reported_before_blank_values(monkeypatch, readable):
    use_pair(monkeypatch, bl_type="OTHER",
             bl=fields(port_of_loading=None, port_of_discharge=None,
                       container_count=None, gross_weight_kg=None))
    r = pipeline.process(TWO, BL)
    assert r["review_reason"] == "wrong_doc_type"
    assert r["note"].startswith("The file attached as the BL is a different kind of document")


def test_blank_value_escalates_as_missing_value(monkeypatch, readable):
    use_pair(monkeypatch, si=fields(gross_weight_kg="____MT"))
    r = pipeline.process(TWO, BL)
    assert r["review_reason"] == "missing_value" and "gross_weight_kg" in r["note"]


def test_mismatch_reports_exact_fields(monkeypatch, readable):
    use_pair(monkeypatch, bl=fields(consignee="UAB NOVAKOPA", notify_party="EAST BRIGHT FZ-LLC"))
    r = pipeline.process(TWO, BL)
    assert (r["status"], r["has_defect"]) == ("MISMATCH", True)
    assert r["defect_fields"] == ["consignee", "notify_party"]
    assert {f["name"] for f in r["fields"] if f["match"] is False} == {"consignee", "notify_party"}


def test_everything_matching_is_ok(monkeypatch, readable):
    use_pair(monkeypatch, bl=fields(consignee="MOORIM SP CO LTD", gross_weight_kg="21577"))
    r = pipeline.process(TWO, BL)
    assert r["status"] == "OK" and r["note"] == "No mismatch detected." and len(r["fields"]) == 7


def test_submission_has_every_id_and_only_scored_keys():
    results = {"email_001": {"category": "BL_COMPARISON", "status": "MISMATCH", "review_reason": None,
                             "has_defect": True, "defect_fields": ["consignee"], "fields": [], "note": "x"}}
    sub = pipeline.to_submission(results, ["email_001", "email_002"])
    assert set(sub) == {"email_001", "email_002"}
    assert sub["email_001"] == {"category": "BL_COMPARISON", "status": "MISMATCH", "review_reason": None,
                                "has_defect": True, "defect_fields": ["consignee"]}
    assert sub["email_002"]["category"] == "GENERAL"
