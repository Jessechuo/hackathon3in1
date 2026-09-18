"""FastAPI app. Reads the bundle plus whatever the pipeline has produced.

Renders whatever exists: with no categories.json it still shows all 520
emails, with the category and verification columns reserved but empty.
"""
import json
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sdoc.ai.classify import CATEGORIES
from sdoc.config import BUNDLE_DIR, OUT_DIR
from sdoc.inbox import load_emails, read_attachment_text

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


def _shell(results: dict, active: str | None) -> dict:
    """Context the base template needs for the header, rail and filters."""
    statuses = [r.get("status") for r in results.values() if r.get("status")]
    return {
        "cats": results,
        "categories_list": CATEGORIES,
        "has_categories": bool(results),
        "has_comparison": bool(statuses),
        "n_ok": statuses.count("OK"),
        "n_mismatch": statuses.count("MISMATCH"),
        "n_review": statuses.count("NEEDS_REVIEW"),
        "active": active,
    }


@app.get("/", response_class=HTMLResponse)
def inbox(request: Request, category: str | None = None):
    all_emails = load_emails()
    results = load_results()

    emails = all_emails
    if category:
        if category not in CATEGORIES:
            raise HTTPException(status_code=400, detail=f"unknown category: {category}")
        emails = [e for e in all_emails
                  if results.get(e["email_id"], {}).get("category") == category]

    return templates.TemplateResponse(
        request=request,
        name="inbox.html",
        context={"emails": emails, "total": len(all_emails), **_shell(results, category)},
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
            "email": email,
            "cat": results.get(email_id),
            "attachments": _attachment_meta(email["attachments"]),
            "prev_id": ordered[i - 1]["email_id"] if i > 0 else None,
            "next_id": ordered[i + 1]["email_id"] if i + 1 < len(ordered) else None,
            "total": len(ordered),
            **_shell(results, None),
        },
    )


@app.get("/attachment/{path:path}", response_class=HTMLResponse)
def attachment(path: str):
    # Path traversal guard: only serve files inside the bundle's attachments/.
    if not path.startswith("attachments/") or ".." in path:
        raise HTTPException(status_code=400, detail="bad attachment path")

    try:
        text = read_attachment_text(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"missing file: {path}")

    if not text.strip():
        text = "(this file is empty)"

    # Binary formats (.pdf/.docx/.xlsx) decode to mojibake here. That is
    # expected until Day 2's extract/ module can render their real text.
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
