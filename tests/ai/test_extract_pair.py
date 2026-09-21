from sdoc.ai import extract_pair as X
from sdoc.config import EXTRACT_MODEL
from sdoc.core.fields import FIELDS


def test_prompt_contains_both_documents_in_order():
    p = X.build_prompt("SI BODY TEXT", "BL BODY TEXT")
    assert "DOCUMENT A" in p and "DOCUMENT B" in p
    assert p.index("SI BODY TEXT") < p.index("BL BODY TEXT")


def flat(text: str) -> str:
    """Prompt phrases wrap across lines; compare with whitespace collapsed."""
    return " ".join(text.split()).lower()


def test_prompt_forbids_reconciling_the_two_documents():
    assert "never fill in or correct one document" in flat(X.build_prompt("a", "b"))


def test_prompt_treats_a_bl_instruction_as_an_si():
    # SI PDFs are titled "BILL OF LADING INSTRUCTION"; SI xlsx say "BL INSTRUCTION"
    assert "bill of lading instruction" in flat(X.build_prompt("a", "b"))


def test_braces_in_document_text_survive():
    assert "{weird} {{text}}" in X.build_prompt("{weird} {{text}}", "b")


def test_extract_pair_uses_the_extract_model_with_room_to_think(monkeypatch):
    seen = {}

    def fake(prompt, schema, model, max_tokens=2048):
        seen.update(model=model, max_tokens=max_tokens)
        empty = {f: None for f in FIELDS}
        return schema(si_doc_type="SHIPPING_INSTRUCTION", bl_doc_type="BILL_OF_LADING",
                      si=empty, bl=empty, si_en=empty, bl_en=empty)

    monkeypatch.setattr(X, "call_structured", fake)
    r = X.extract_pair("si", "bl")
    assert seen["model"] == EXTRACT_MODEL
    assert seen["max_tokens"] >= 8000
    assert r.bl_doc_type == "BILL_OF_LADING"
