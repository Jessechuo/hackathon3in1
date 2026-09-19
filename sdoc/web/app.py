"""FastAPI app. Reads the bundle plus whatever the pipeline has produced.

Renders whatever exists: with no categories.json it still shows all 520
emails, with the category and verification columns reserved but empty.
"""
import json
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from sdoc.ai.classify import CATEGORIES
from sdoc.config import BUNDLE_DIR, OUT_DIR
from sdoc.extract import read_document
from sdoc.inbox import load_emails

app = FastAPI(title="SDOC Inbox")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

KINDS = {
    ".txt": "Plain text",
    ".pdf": "PDF document",
    ".docx": "Word document",
    ".xlsx": "Excel workbook",
}


def load_results() -> dict:
    """Pipeline output, or {} before it has run.

    Prefers results.json (Day 2: category + verification status) and falls
    back to categories.json (Day 1: category only).
    """
    out = Path(OUT_DIR)
    for name in ("results.json", "categories.json"):
        path = out / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


DECISIONS = {"verified", "mismatch"}
STATUSES = ["OK", "MISMATCH", "NEEDS_REVIEW"]


def load_review() -> dict:
    """Human decisions recorded from the UI. The human-in-the-loop record:
    what a person confirmed or corrected, and when."""
    path = Path(OUT_DIR) / "review.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_review(state: dict) -> None:
    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    (Path(OUT_DIR) / "review.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )


def _human_size(n: int) -> str:
    return f"{n / 1024:.1f} KB" if n >= 1024 else f"{n} B"


def _attachment_meta(paths: list[str]) -> list[dict]:
    meta = []
    for rel in paths:
        p = Path(BUNDLE_DIR) / rel
        suffix = p.suffix.lower()
        meta.append({
            "path": rel,
            "name": p.name,
            "kind": KINDS.get(suffix, suffix.lstrip(".").upper() or "File"),
            "size": _human_size(p.stat().st_size) if p.exists() else "missing",
        })
    return meta


def _shell(results: dict, active: str | None, active_status: str | None = None) -> dict:
    """Context the base template needs for the header, rail and filters."""
    statuses = [r.get("status") for r in results.values()
                if r.get("category") == "BL_COMPARISON" and r.get("status")
                and r.get("note") != "Not processed yet."]
    return {
        "cats": results,
        "categories_list": CATEGORIES,
        "statuses": STATUSES,
        "has_categories": bool(results),
        "has_comparison": bool(statuses),     # categories.json entries carry no status
        "n_ok": statuses.count("OK"),
        "n_mismatch": statuses.count("MISMATCH"),
        "n_review": statuses.count("NEEDS_REVIEW"),
        "active": active,
        "active_status": active_status,
    }


def _bar_rows(counts: Counter, href=None) -> list[dict]:
    """Rank largest first; widths are relative to the largest bar."""
    ranked = counts.most_common()
    if not ranked:
        return []
    top = ranked[0][1]
    total = sum(counts.values())
    return [{
        "label": label,
        "count": n,
        "width": round(n / top * 100, 1),
        "share": round(n / total * 100),
        "href": href(label) if href else None,
    } for label, n in ranked]


def dashboard_stats(results: dict, review: dict) -> dict:
    """Every number on the dashboard, from results.json and review.json only."""
    checked = {eid: r for eid, r in results.items()
               if r.get("category") == "BL_COMPARISON" and r.get("status")
               and r.get("note") != "Not processed yet."}
    mismatches = [eid for eid, r in checked.items() if r["status"] == "MISMATCH"]
    reviews = [eid for eid, r in checked.items() if r["status"] == "NEEDS_REVIEW"]
    attention = set(mismatches) | set(reviews)
    by_field = Counter(f for eid in mismatches for f in results[eid].get("defect_fields") or [])
    by_category = Counter(r["category"] for r in results.values() if r.get("category"))
    return {
        "total": len(results),
        "has_comparison": bool(checked),
        "mismatches": len(mismatches),
        "needs_review": len(reviews),
        "attention": len(attention),
        # Only decisions on flagged emails count as reviewing the flagged work.
        "decided": sum(1 for eid in attention if eid in review),
        "by_category": _bar_rows(by_category, lambda c: f"/?category={c}"),
        "by_field": _bar_rows(by_field),
    }


def _last_run() -> str | None:
    for name in ("results.json", "categories.json"):
        path = Path(OUT_DIR) / name
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d %b %Y, %H:%M:%S")
    return None


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    results = load_results()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "page": "dashboard",
            "total": len(load_emails()),
            "stats": dashboard_stats(results, load_review()),
            "last_run": _last_run(),
            **_shell(results, None),
        },
    )


@app.get("/", response_class=HTMLResponse)
def inbox(request: Request, category: str | None = None, status: str | None = None):
    all_emails = load_emails()
    results = load_results()

    emails = all_emails
    if category:
        if category not in CATEGORIES:
            raise HTTPException(status_code=400, detail=f"unknown category: {category}")
        emails = [e for e in emails
                  if results.get(e["email_id"], {}).get("category") == category]
    if status:
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail=f"unknown status: {status}")
        emails = [e for e in emails
                  if results.get(e["email_id"], {}).get("category") == "BL_COMPARISON"
                  and results.get(e["email_id"], {}).get("status") == status]

    return templates.TemplateResponse(
        request=request,
        name="inbox.html",
        context={"page": "inbox", "emails": emails, "total": len(all_emails),
                 **_shell(results, category, status)},
    )


@app.get("/email/{email_id}", response_class=HTMLResponse)
def email_detail(request: Request, email_id: str):
    ordered = load_emails()
    index = {e["email_id"]: i for i, e in enumerate(ordered)}
    if email_id not in index:
        raise HTTPException(status_code=404, detail=f"no such email: {email_id}")

    i = index[email_id]
    email = ordered[i]
    results = load_results()

    return templates.TemplateResponse(
        request=request,
        name="email.html",
        context={
            "page": "inbox",
            "email": email,
            "cat": results.get(email_id),
            "review": load_review().get(email_id),
            "attachments": _attachment_meta(email["attachments"]),
            "prev_id": ordered[i - 1]["email_id"] if i > 0 else None,
            "next_id": ordered[i + 1]["email_id"] if i + 1 < len(ordered) else None,
            "position": i + 1,
            "total": len(ordered),
            **_shell(results, None),
        },
    )


@app.post("/review/{email_id}")
async def record_review(email_id: str, request: Request):
    """Record a human decision. Toggling the same decision clears it."""
    if not any(e["email_id"] == email_id for e in load_emails()):
        raise HTTPException(status_code=404, detail=f"no such email: {email_id}")

    payload = await request.json()
    decision = payload.get("decision")
    if decision not in DECISIONS:
        raise HTTPException(status_code=400, detail=f"bad decision: {decision!r}")

    state = load_review()
    if state.get(email_id, {}).get("decision") == decision:
        state.pop(email_id, None)          # clicking the same button undoes it
        current = None
    else:
        current = {"decision": decision,
                   "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        state[email_id] = current
    save_review(state)

    return JSONResponse({"email_id": email_id, "review": current})


@app.get("/attachment/{path:path}", response_class=HTMLResponse)
def attachment(path: str):
    # Path traversal guard: only serve files inside the bundle's attachments/.
    if not path.startswith("attachments/") or ".." in path:
        raise HTTPException(status_code=400, detail="bad attachment path")

    doc = read_document(path)
    if doc.problem == "file not found":
        raise HTTPException(status_code=404, detail=f"missing file: {path}")
    text = doc.text if doc.readable else f"(This file cannot be read: {doc.problem}.)"

    name = escape(path.split("/")[-1])
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{name}</title>"
        "<style>:root{color-scheme:light dark}"
        "body{margin:0;font-family:ui-monospace,'JetBrains Mono',Menlo,Consolas,monospace}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:24px;"
        "font-size:13px;line-height:1.6;margin:0}</style></head>"
        f"<body><pre>{escape(text)}</pre></body></html>"
    )
