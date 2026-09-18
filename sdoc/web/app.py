"""FastAPI app. Reads the bundle plus whatever the pipeline has produced.

Renders whatever exists: with no categories.json it still shows all 520
emails, with the category column reserved but empty.
"""
import json
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sdoc.ai.classify import CATEGORIES
from sdoc.config import OUT_DIR
from sdoc.inbox import load_emails, read_attachment_text

app = FastAPI(title="SDOC Inbox")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def load_categories() -> dict:
    """Classification results, or {} before the pipeline has run."""
    path = Path(OUT_DIR) / "categories.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _shell(cats: dict, active: str | None) -> dict:
    """Context every template needs for the header and filter nav."""
    return {
        "cats": cats,
        "categories_list": CATEGORIES,
        "has_categories": bool(cats),
        "active": active,
    }


@app.get("/", response_class=HTMLResponse)
def inbox(request: Request, category: str | None = None):
    all_emails = load_emails()
    cats = load_categories()

    emails = all_emails
    if category:
        if category not in CATEGORIES:
            raise HTTPException(status_code=400, detail=f"unknown category: {category}")
        emails = [e for e in all_emails if cats.get(e["email_id"], {}).get("category") == category]

    return templates.TemplateResponse(
        request=request,
        name="inbox.html",
        context={"emails": emails, "total": len(all_emails), **_shell(cats, category)},
    )


@app.get("/email/{email_id}", response_class=HTMLResponse)
def email_detail(request: Request, email_id: str):
    emails = {e["email_id"]: e for e in load_emails()}
    if email_id not in emails:
        raise HTTPException(status_code=404, detail=f"no such email: {email_id}")

    cats = load_categories()
    return templates.TemplateResponse(
        request=request,
        name="email.html",
        context={"email": emails[email_id], "cat": cats.get(email_id), **_shell(cats, None)},
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
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{escape(path.split('/')[-1])}</title>"
        "<style>:root{color-scheme:light dark}"
        "body{margin:0;font-family:ui-monospace,Menlo,Consolas,monospace}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:24px;"
        "font-size:13px;line-height:1.6;margin:0}</style></head>"
        f"<body><pre>{escape(text)}</pre></body></html>"
    )
