"""One email in, one decision out. The checks run in a fixed order and the
first one that fails decides the review reason — the most specific failure
is always reported, never a symptom of it (spec, section 4)."""
import csv
import io
from dataclasses import asdict

from sdoc.ai.extract_pair import extract_pair
from sdoc.core.compare import compare
from sdoc.extract import read_document

_DOC_NAMES = {"SHIPPING_INSTRUCTION": "shipping instruction",
              "BILL_OF_LADING": "bill of lading",
              "OTHER": "different kind of document (e.g. invoice or packing list)"}


def base_result(cls: dict) -> dict:
    return {
        "category": cls.get("category", "GENERAL"),
        "reason": cls.get("reason", ""),
        "status": "OK",
        "review_reason": None,
        "has_defect": False,
        "defect_fields": [],
        "fields": [],
        "note": None,
        "error": cls.get("error"),
        "failed": False,
    }


def _review(r: dict, reason: str, note: str) -> dict:
    r.update(status="NEEDS_REVIEW", review_reason=reason, note=note)
    return r


def _assign(attachments: list[str]) -> tuple[str | None, str | None]:
    si = next((a for a in attachments if "_SI." in a.upper()), None)
    bl = next((a for a in attachments if "_BL." in a.upper()), None)
    if si is None and bl is None and len(attachments) == 2:
        si, bl = attachments
    return si, bl


def process(email: dict, cls: dict) -> dict:
    r = base_result(cls)
    if r["category"] != "BL_COMPARISON":
        return r

    # 1. Attachments
    attachments = email.get("attachments") or []
    if not attachments:
        if cls.get("documents_meant_to_be_attached"):
            return _review(r, "missing_attachment",
                           "The email says the SI and BL are attached, but no files came through.")
        r["note"] = "No documents attached yet - the sender is asking for the draft BL to be sent."
        return r
    si_path, bl_path = _assign(attachments)
    if not si_path or not bl_path:
        which = "draft BL" if not bl_path else "shipping instruction"
        return _review(r, "missing_attachment", f"The {which} is not attached.")

    # 2. Readable
    si_doc, bl_doc = read_document(si_path), read_document(bl_path)
    for label, doc in (("SI", si_doc), ("BL", bl_doc)):
        if not doc.readable:
            return _review(r, "unreadable",
                           f"{label} attachment {doc.path.split('/')[-1]}: {doc.problem}.")

    # 3. Extract (Claude)
    pair = extract_pair(si_doc.text, bl_doc.text)

    # 4. Right document types
    wrong = []
    if pair.si_doc_type != "SHIPPING_INSTRUCTION":
        wrong.append(f"the file attached as the SI is a {_DOC_NAMES[pair.si_doc_type]}")
    if pair.bl_doc_type != "BILL_OF_LADING":
        wrong.append(f"the file attached as the BL is a {_DOC_NAMES[pair.bl_doc_type]}")
    if wrong:
        msg = "; ".join(wrong)          # not .capitalize(): it would lowercase "SI"/"BL"
        return _review(r, "wrong_doc_type", msg[0].upper() + msg[1:] + ".")

    # 5. Blank values, then 6. compare
    result = compare(pair.si, pair.bl, pair.si_en, pair.bl_en)
    r["fields"] = [asdict(row) for row in result.rows]
    if result.missing:
        return _review(r, "missing_value",
                       "Blank or placeholder value for: " + ", ".join(result.missing) + ".")
    if result.defects:
        r.update(status="MISMATCH", has_defect=True, defect_fields=result.defects)
        return r
    r["note"] = "No mismatch detected."
    return r


def to_submission(results: dict, all_ids: list[str]) -> dict:
    """Exactly the five scored keys, for every id — a missing id is invalid."""
    sub = {}
    for eid in all_ids:
        r = results.get(eid, {})
        sub[eid] = {
            "category": r.get("category", "GENERAL"),
            "status": r.get("status", "OK"),
            "review_reason": r.get("review_reason"),
            "has_defect": bool(r.get("has_defect")),
            "defect_fields": list(r.get("defect_fields") or []),
        }
    return sub


CSV_COLUMNS = ["email_id", "category", "status", "review_reason", "has_defect", "defect_fields"]


def submission_csv(submission: dict) -> str:
    """submission.json as CSV: one row per email, in email_id order, the same
    five fields. Two wrong fields share one cell, joined by ";" - 26 emails
    have two - and true/false stay lowercase, as in the JSON."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for eid in sorted(submission):
        v = submission[eid]
        writer.writerow([eid, v["category"], v["status"], v["review_reason"] or "",
                         "true" if v["has_defect"] else "false", ";".join(v["defect_fields"])])
    return out.getvalue()
