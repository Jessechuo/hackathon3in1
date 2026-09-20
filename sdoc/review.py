"""A reviewer's decision is the final word on an email. Pure functions.

The brief: "Let a person confirm or correct it, then update the report."
The system's answer is kept alongside, so the report can say what changed.
These views feed the app only; submission.json stays the system's answers.

A decision records the OUTCOME, not agreement with the system:
  {"decision": "verified", "at": ...}                 documents are fine -> OK
  {"decision": "mismatch", "fields": [...], "at": ...} these fields differ -> MISMATCH
"""


def effective(result: dict, decision: dict | None) -> dict:
    out = dict(result)
    out["system_status"] = result.get("status")
    out["system_defect_fields"] = list(result.get("defect_fields") or [])
    out["review"] = decision
    out["reviewed"] = False
    out["reviewer_changed"] = False

    # Only document-check emails have an SI/BL outcome for a person to decide.
    if not decision or result.get("category") != "BL_COMPARISON":
        return out

    if decision.get("decision") == "verified":
        out.update(status="OK", defect_fields=[], has_defect=False, review_reason=None)
    else:
        out.update(status="MISMATCH", defect_fields=list(decision.get("fields") or []),
                   has_defect=True, review_reason=None)
    out["reviewed"] = True
    out["reviewer_changed"] = (
        (out["status"], sorted(out["defect_fields"]))
        != (out["system_status"], sorted(out["system_defect_fields"]))
    )
    return out


def apply_reviews(results: dict, decisions: dict) -> dict:
    return {eid: effective(r, decisions.get(eid)) for eid, r in results.items()}
