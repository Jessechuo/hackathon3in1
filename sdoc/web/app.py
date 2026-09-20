"""FastAPI app. Reads the bundle plus whatever the pipeline has produced.

Renders whatever exists: with no categories.json it still shows all 520
emails, with the category and verification columns reserved but empty.
"""
import json
import logging
import os
import threading
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from sdoc.ai.classify import CATEGORIES
from sdoc.config import MAIL_DIR, OUT_DIR
from sdoc.core.fields import FIELDS
from sdoc.extract import read_document
from sdoc.ingest import ingest, load_mail_results, mark_pending, update_result
from sdoc.inbox import attachment_path, load_all_emails, load_received
from sdoc.mail.send import send as send_mail
from sdoc.mail.send import note_unreachable, reachable, valid_address
from sdoc.mail.send import probe as probe_smtp
from sdoc.mail.store import save_email
from sdoc.review import apply_reviews
from sdoc.web import auth, watcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    """One process serves the UI and polls the mailbox.

    Two processes would mean two things to deploy, pay for and restart. The
    watch runs in a daemon thread and stops itself when the app shuts down;
    with no mail credentials set it simply never starts.
    """
    watcher.seed_output()       # a mounted volume starts empty
    # Whether mail can leave this host at all. Off the startup path so a
    # blocked route delays nothing; the compose page reads the answer.
    threading.Thread(target=probe_smtp, daemon=True, name="smtp-probe").start()
    handle = watcher.start()
    yield
    if handle:
        handle[1].set()


app = FastAPI(title="SDOC Inbox", lifespan=lifespan)

# Reachable without an account: the front door itself, and the way back out.
OPEN_PATHS = {"/login", "/register", "/logout"}


@app.middleware("http")
async def sign_in_wall(request: Request, call_next):
    """The queue is behind a sign-in. Signup being open is what makes that
    fair: nobody is locked out, they make an account first."""
    path = request.url.path
    if (auth.require_login() and path not in OPEN_PATHS
            and not auth.current_user(request)):
        target = path if request.method == "GET" else "/"
        return RedirectResponse(f"/login?next={quote(target, safe='/')}",
                                status_code=303)
    return await call_next(request)


# Added LAST so it is the outermost layer and runs FIRST. Starlette builds
# the stack in reverse, so registering this before sign_in_wall would leave
# the wall reading request.session before it exists - it would see nobody
# signed in, redirect to /login, and loop there forever.
#
# Signed cookie, not server-side storage: one process, no database, and the
# only thing in it is which account is signed in.
app.add_middleware(SessionMiddleware, secret_key=auth.session_secret(),
                   same_site="lax", https_only=False)


log = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

KINDS = {
    ".txt": "Plain text",
    ".pdf": "PDF document",
    ".docx": "Word document",
    ".xlsx": "Excel workbook",
}

# A person typing a demo email, not a mail server: small, sane caps so a
# misdropped file cannot fill the disk or run up an extraction bill.
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024


def load_results() -> dict:
    """Pipeline output, or {} before it has run.

    Prefers results.json (Day 2: category + verification status) and falls
    back to categories.json (Day 1: category only). Anything received since
    the bundle is merged on top - it is kept in a file of its own because a
    full run_pipeline rewrites results.json from the 520 bundle ids.
    """
    out = Path(OUT_DIR)
    results = {}
    for name in ("results.json", "categories.json"):
        path = out / name
        if path.exists():
            results = json.loads(path.read_text(encoding="utf-8"))
            break
    return {**results, **load_mail_results(OUT_DIR)}


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


def load_view() -> dict:
    """What every page shows: the pipeline's results with any reviewer
    decisions applied on top. submission.json is never touched by this."""
    return apply_reviews(load_results(), load_review())


def _human_size(n: int) -> str:
    return f"{n / 1024:.1f} KB" if n >= 1024 else f"{n} B"


def _attachment_meta(paths: list[str]) -> list[dict]:
    meta = []
    for rel in paths:
        p = attachment_path(rel)
        suffix = p.suffix.lower()
        meta.append({
            "path": rel,
            "name": p.name,
            "kind": KINDS.get(suffix, suffix.lstrip(".").upper() or "File"),
            "size": _human_size(p.stat().st_size) if p.exists() else "missing",
        })
    return meta


def _shell(results: dict, active: str | None, active_status: str | None = None,
           active_reviewed: bool = False, user: str | None = None) -> dict:
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
        "n_reviewed": sum(1 for r in results.values() if r.get("reviewed")),
        # Counted from the mail folder, not from results: an email that has
        # just arrived should show in the header before it has been processed.
        "n_received": len(load_received()),
        # Read per request, not at import: the watcher may be started later.
        "mail_address": os.environ.get("SDOC_MAIL_USER") or None,
        "user": user,
        "user_name": (auth.get_user(user, OUT_DIR) or {}).get("name") if user else None,
        "active": active,
        "active_status": active_status,
        "active_reviewed": active_reviewed,
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
    """Every number on the dashboard, from results.json and review.json only.

    Mismatches and needs-review reflect reviewer decisions, so the review
    queue empties as a person works through it. 'Flagged' is what the
    SYSTEM flagged: the denominator for human decisions."""
    view = apply_reviews(results, review)
    checked = {eid: r for eid, r in view.items()
               if r.get("category") == "BL_COMPARISON" and r.get("status")
               and r.get("note") != "Not processed yet."}
    mismatches = [eid for eid, r in checked.items() if r["status"] == "MISMATCH"]
    reviews = [eid for eid, r in checked.items() if r["status"] == "NEEDS_REVIEW"]
    flagged = [eid for eid, r in checked.items()
               if r["system_status"] in ("MISMATCH", "NEEDS_REVIEW")]
    by_field = Counter(f for eid in mismatches for f in view[eid].get("defect_fields") or [])
    by_category = Counter(r["category"] for r in view.values() if r.get("category"))
    return {
        "total": len(view),
        "has_comparison": bool(checked),
        "mismatches": len(mismatches),
        "needs_review": len(reviews),
        "attention": len(flagged),
        "decided": sum(1 for eid in flagged if view[eid]["reviewed"]),
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
    results, decisions = load_results(), load_review()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "page": "dashboard",
            "total": len(load_all_emails()),
            "stats": dashboard_stats(results, decisions),
            "last_run": _last_run(),
            **_shell(apply_reviews(results, decisions), None, user=auth.current_user(request)),
        },
    )


@app.get("/", response_class=HTMLResponse)
def inbox(request: Request, category: str | None = None, status: str | None = None,
          reviewed: bool = False):
    all_emails = load_all_emails()
    results = load_view()

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
    if reviewed:
        emails = [e for e in emails if results.get(e["email_id"], {}).get("reviewed")]

    return templates.TemplateResponse(
        request=request,
        name="inbox.html",
        context={"page": "inbox", "emails": emails, "total": len(all_emails),
                 **_shell(results, category, status, reviewed,
                          user=auth.current_user(request))},
    )


@app.get("/email/{email_id}", response_class=HTMLResponse)
def email_detail(request: Request, email_id: str):
    ordered = load_all_emails()
    index = {e["email_id"]: i for i, e in enumerate(ordered)}
    if email_id not in index:
        raise HTTPException(status_code=404, detail=f"no such email: {email_id}")

    i = index[email_id]
    email = ordered[i]
    results = load_view()
    cat = results.get(email_id) or {}
    review = cat.get("review")
    # The tick list starts from the reviewer's own fields, else the system's findings.
    preticked = (review.get("fields") if review and review.get("decision") == "mismatch"
                 else cat.get("system_defect_fields")) or []

    return templates.TemplateResponse(
        request=request,
        name="email.html",
        context={
            "page": "inbox",
            "email": email,
            "cat": cat or None,
            "review": review,
            "can_review": cat.get("category") == "BL_COMPARISON",
            "field_names": FIELDS,
            "preticked": preticked,
            "attachments": _attachment_meta(email["attachments"]),
            "prev_id": ordered[i - 1]["email_id"] if i > 0 else None,
            "next_id": ordered[i + 1]["email_id"] if i + 1 < len(ordered) else None,
            "position": i + 1,
            "total": len(ordered),
            **_shell(results, None, user=auth.current_user(request)),
        },
    )


@app.post("/review/{email_id}")
async def record_review(email_id: str, request: Request):
    """Record a reviewer's final word on a document-check email.

    {"decision": "verified"}                        the documents are fine
    {"decision": "mismatch", "fields": [...]}       these fields differ
    {"decision": null}                              clear; the system's answer stands
    """
    if not any(e["email_id"] == email_id for e in load_all_emails()):
        raise HTTPException(status_code=404, detail=f"no such email: {email_id}")
    if load_results().get(email_id, {}).get("category") != "BL_COMPARISON":
        raise HTTPException(status_code=400,
                            detail="only document-check (BL_COMPARISON) emails can be reviewed")

    payload = await request.json()
    decision = payload.get("decision")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if decision is None:
        current = None
    elif decision == "verified":
        current = {"decision": "verified", "at": now}
    elif decision == "mismatch":
        fields = payload.get("fields") or []
        unknown = [f for f in fields if f not in FIELDS]
        if not fields or unknown:
            raise HTTPException(status_code=400,
                                detail=f"tick at least one of {FIELDS}; unknown: {unknown}")
        current = {"decision": "mismatch", "fields": [f for f in FIELDS if f in fields], "at": now}
    else:
        raise HTTPException(status_code=400, detail=f"bad decision: {decision!r}")

    state = load_review()
    if current is None:
        state.pop(email_id, None)
    else:
        state[email_id] = current
    save_review(state)
    return JSONResponse({"email_id": email_id, "review": current})


def _safe_next(target: str) -> str:
    """Where to go after signing in. Same-site paths only.

    `next` arrives from the URL, so it is attacker-controlled. A leading
    slash is not enough of a check: `//evil.example/x` starts with one and
    browsers read it as protocol-relative, landing on another host.
    """
    if not target or not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


def _auth_page(request: Request, template: str, status: int = 200, **extra):
    """The sign-in and registration screens are their own shell - a person
    who is not signed in has no queue, no filters and no rail to show.

    The template argument is `template`, not `name`: the registration form
    posts a field called `name` and it is forwarded straight through here.
    """
    return templates.TemplateResponse(
        request=request, name=template, status_code=status,
        context={"page": template.removesuffix(".html"),
                 "code_required": auth.code_required(),
                 "desks": auth.DESKS,
                 "min_password": auth.MIN_PASSWORD,
                 "mail_address": os.environ.get("SDOC_MAIL_USER") or None,
                 **extra},
    )


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    if auth.current_user(request):
        return RedirectResponse(_safe_next(next), status_code=303)
    return _auth_page(request, "login.html", next=next)


@app.post("/login")
def login_submit(request: Request, email: str = Form(""), password: str = Form(""),
                 next: str = Form("/"), remember: str = Form("")):
    who = auth.authenticate(email, password, OUT_DIR)
    if not who:
        # One message for both halves: saying which was wrong tells an
        # attacker which addresses have accounts.
        return _auth_page(request, "login.html", status=401, next=next,
                          error="That email and password do not match an account.",
                          email=email)
    request.session[auth.SESSION_KEY] = who
    # The screen offers to keep the terminal signed in; honour it.
    request.session["ttl"] = "12h" if remember else "session"
    return RedirectResponse(_safe_next(next), status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.pop(auth.SESSION_KEY, None)
    return RedirectResponse("/", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return _auth_page(request, "register.html")


@app.post("/register")
def register_submit(request: Request, name: str = Form(""), email: str = Form(""),
                    password: str = Form(""), confirm: str = Form(""),
                    desk: str = Form(""), code: str = Form(""),
                    acknowledge: str = Form("")):
    typed = {"name": name, "email": email, "desk": desk}
    if not auth.code_ok(code):
        return _auth_page(request, "register.html", status=400, **typed,
                          error="That access code is not right.")
    if not acknowledge:
        return _auth_page(request, "register.html", status=400, **typed,
                          error="You need to acknowledge the audit logging policy.")
    try:
        auth.create_user(email, password, out_dir=OUT_DIR, name=name, desk=desk,
                         confirm=confirm)
    except ValueError as e:
        return _auth_page(request, "register.html", status=400, **typed, error=str(e))
    request.session[auth.SESSION_KEY] = auth.normalise(email)
    return RedirectResponse("/", status_code=303)


@app.get("/compose", response_class=HTMLResponse)
def compose_form(request: Request):
    results = load_view()
    return templates.TemplateResponse(
        request=request,
        name="compose.html",
        context={"page": "compose", "total": len(load_all_emails()),
                 "max_attachments": MAX_ATTACHMENTS,
                 "max_mb": MAX_ATTACHMENT_BYTES // 1024 // 1024,
                 "can_send": bool(auth.current_user(request)),
                 "smtp_reachable": reachable(),
                 **_shell(results, None, user=auth.current_user(request))},
    )


def _check_then_send(email: dict, to: str, subject: str, body: str,
                     attachments: list[tuple[str, bytes]]) -> None:
    """The slow half of sending, off the request.

    Reading two documents with Opus and opening an SMTP connection together
    take the better part of half a minute. Doing that before responding left
    a person watching a spinner, so the page comes back immediately and this
    fills in behind it.

    The check still runs before the send: catching a discrepancy after the
    draft has gone is worth much less.
    """
    ingest(email, out_dir=OUT_DIR)          # never raises; records its own failure
    try:
        send_mail(to, subject, body, attachments)
        update_result(email["email_id"], OUT_DIR, sent=True, send_error=None,
                      sent_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    except Exception as e:
        log.warning("could not send %s: %s", email["email_id"], e)
        if "unreachable" in str(e).lower() or "outbound SMTP" in str(e):
            note_unreachable()      # stop offering what cannot work
        update_result(email["email_id"], OUT_DIR, sent=False,
                      send_error=f"{type(e).__name__}: {e}")


@app.post("/compose")
async def compose_submit(request: Request, to: str = Form(""), subject: str = Form(""),
                         body: str = Form(""),
                         files: list[UploadFile] = File(default=[])):
    """Check the attached documents, then send the email.

    The check runs first on purpose: a discrepancy is worth catching before
    a draft leaves rather than after the customer finds it. The verdict is
    recorded either way and shown on the email's page.

    Fields are declared optional and checked here. A required Form field
    that arrives empty is dropped by the encoder and reported as missing,
    which is a 422 full of schema noise; this way blank and whitespace-only
    both give the same readable 400.
    """
    if not auth.current_user(request):
        raise HTTPException(status_code=401, detail="sign in to send mail")

    to, subject = to.strip(), subject.strip()
    if not valid_address(to):
        raise HTTPException(status_code=400, detail=f"not an email address: {to!r}")
    if not subject:
        raise HTTPException(status_code=400, detail="subject is required")

    uploads = [f for f in files if f.filename]
    if len(uploads) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=400,
                            detail=f"at most {MAX_ATTACHMENTS} attachments")

    attachments = []
    for f in uploads:
        data = await f.read()
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"{f.filename} is too large (limit "
                       f"{MAX_ATTACHMENT_BYTES // 1024 // 1024} MB)")
        attachments.append((f.filename, data))

    account = os.environ.get("SDOC_MAIL_USER") or "sdoc@localhost"
    email = save_email(account, subject, body, attachments, root=MAIL_DIR,
                       recipient=to, direction="sent")
    mark_pending(email, out_dir=OUT_DIR)
    threading.Thread(target=_check_then_send, daemon=True,
                     args=(email, to, subject, body, attachments),
                     name=f"send-{email['email_id']}").start()
    return RedirectResponse(f"/email/{email['email_id']}", status_code=303)


@app.get("/attachment/{path:path}", response_class=HTMLResponse)
def attachment(path: str):
    # Path traversal guard: only ever serve files from the two attachment
    # folders - the bundle's and the received-mail one. Nothing else under
    # either directory, and no traversal out of them.
    if ".." in path or not path.startswith(("attachments/", "mail/attachments/")):
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
