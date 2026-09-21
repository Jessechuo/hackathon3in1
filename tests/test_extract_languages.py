from sdoc import pipeline
from sdoc.ai import extract_pair as X
from sdoc.core.fields import ShipmentFields


def test_the_prompt_asks_for_an_english_form_from_each_document_alone():
    p = X.build_prompt("SI TEXT", "BL TEXT")
    assert "si_en" in p and "bl_en" in p
    assert "already in English" in p and "copy it exactly" in p
    assert "never from the other document" in p
    assert "English, Malay or Chinese" in p


def test_the_schema_requires_the_english_forms():
    """Required, so the structured output always fills them."""
    required = X.PairExtraction.model_json_schema()["required"]
    assert "si_en" in required and "bl_en" in required


def test_the_pipeline_compares_with_the_english_forms(monkeypatch):
    full = dict(shipper="A SDN BHD", consignee="B CO", notify_party="B CO", port_of_loading="PORT KLANG",
                port_of_discharge="HAIPHONG", container_count="3 x 40'HC", gross_weight_kg="61,250 KG")
    si = ShipmentFields(**{**full, "port_of_loading": "巴生港"})
    bl = ShipmentFields(**full)
    pair = X.PairExtraction(si_doc_type="SHIPPING_INSTRUCTION", bl_doc_type="BILL_OF_LADING",
                            si=si, bl=bl, si_en=ShipmentFields(**full), bl_en=ShipmentFields(**full))
    monkeypatch.setattr(pipeline, "extract_pair", lambda a, b: pair)
    doc = type("Doc", (), {"readable": True, "text": "x", "path": "p", "problem": None})
    monkeypatch.setattr(pipeline, "read_document", lambda path: doc)
    r = pipeline.process({"attachments": ["x_SI.txt", "x_BL.txt"]},
                         {"category": "BL_COMPARISON", "reason": "check"})
    assert r["status"] == "OK"
    pol = next(f for f in r["fields"] if f["name"] == "port_of_loading")
    assert pol["si"] == "巴生港" and pol["si_en"] == "PORT KLANG"
