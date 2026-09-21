"""FastAPI app. Reads the bundle plus whatever the pipeline has produced.

Renders whatever exists: with no categories.json it still shows all 520
emails, with the category and verification columns reserved but empty.
"""
import json
import logging
import os
import shutil
import threading
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from sdoc.ai.classify import CATEGORIES
from sdoc.config import MAIL_DIR, OUT_DIR, ROOT
from sdoc.core.fields import FIELDS
from sdoc.extract import read_document
from sdoc.ingest import forget, load_mail_results
from sdoc.inbox import attachment_path, load_all_emails
from sdoc.mail.send import send as send_mail
from sdoc.mail.send import note_unreachable, reachable, valid_address
from sdoc.mail.send import probe as probe_smtp
from sdoc.mail.store import delete_sent
from sdoc.pipeline import _assign, submission_csv
from sdoc.review import apply_reviews
from sdoc.web import auth, checks, i18n, watcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    """One process serves the UI and polls the mailbox.

    Two processes would mean two things to deploy, pay for and restart. The
    watch runs in a daemon thread and stops itself when the app shuts down;
    with no mail credentials set it simply never starts.
    """
    watcher.seed_output()       # a mounted volume starts empty
    start_clean()               # once per tag: only the 520, as the organizers sent them
    forget_sent_mail()          # sent mail is no longer kept; clear what was
    # Whether mail can leave this host at all. Off the startup path so a
    # blocked route delays nothing; the compose page reads the answer.
    threading.Thread(target=probe_smtp, daemon=True, name="smtp-probe").start()
    handle = watcher.start()
    yield
    if handle:
        handle[1].set()


app = FastAPI(title="MailOps", lifespan=lifespan)

# Reachable without an account: the front door itself, the way back out, and
# the logo the front door shows.
OPEN_PATHS = {"/login", "/register", "/logout", "/logo.png", "/favicon.ico"}
LOGO = Path(__file__).parent / "static" / "mailops.png"


@app.get("/logo.png", include_in_schema=False)
@app.get("/favicon.ico", include_in_schema=False)     # asked for by browsers regardless
def logo():
    return FileResponse(LOGO, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.middleware("http")
async def sign_in_wall(request: Request, call_next):
    """The queue is behind a sign-in. Signup being open is what makes that
    fair: nobody is locked out, they make an account first."""
    path = request.url.path
    if (auth.require_login() and path not in OPEN_PATHS
            and not path.startswith("/lang/")
            and not auth.current_user(request)):
        target = path if request.method == "GET" else "/"
        return RedirectResponse(f"/login?next={quote(target, safe='/')}",
                                status_code=303)
    return await call_next(request)


@app.middleware("http")
async def language(request: Request, call_next):
    """Every page renders in the visitor's language: their saved choice,
    else their browser's."""
    token = i18n.use(i18n.pick(request.cookies.get(i18n.COOKIE),
                               request.headers.get("accept-language")))
    try:
        return await call_next(request)
    finally:
        i18n.reset(token)


@app.get("/lang/{code}", include_in_schema=False)
def set_language(code: str, next: str = "/"):
    """The EN / BM / 中文 switch: remember the choice, go back to the page."""
    if code not in i18n.LANGS:
        raise HTTPException(status_code=404, detail="unknown language")
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(i18n.COOKIE, code, max_age=365 * 24 * 3600, samesite="lax")
    return response


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
templates.env.globals.update(t=i18n.t, lang=i18n.current, LANGS=i18n.LANGS,
                             HTML_LANG=i18n.HTML_LANG, js_strings=i18n.strings)


def bold(value) -> Markup:
    """<b>value</b>, the value escaped: a bold word inside a translated
    sentence. Built as "<b>" ~ (value|e) ~ "</b>" instead, the escaped value
    turned the whole string into escaped markup and the page showed the
    tags as text - "From <b>hackathon3in1@gmail.com</b>"."""
    return Markup("<b>{}</b>").format(value)


templates.env.globals["bold"] = bold

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
    # Which file is the SI and which the BL, decided the way the pipeline
    # decides it, so the viewer puts each one on its side.
    si, bl = _assign(paths)
    meta = []
    for rel in paths:
        p = attachment_path(rel)
        suffix = p.suffix.lower()
        meta.append({
            "path": rel,
            "name": p.name,
            "kind": KINDS.get(suffix, suffix.lstrip(".").upper() or "File"),
            "size": _human_size(p.stat().st_size) if p.exists() else "missing",
            "role": "SI" if rel == si else "BL" if rel == bl else None,
        })
    return meta


def _marks(cat: dict) -> list[dict]:
    """The compared values, for the viewer to find and colour in each
    document. Coloured by the final answer, as the comparison table is: a
    reviewer's decision replaces the system's."""
    if cat.get("category") != "BL_COMPARISON":
        return []
    wrong = cat.get("defect_fields") or []
    return [{"name": f["name"], "si": f.get("si"), "bl": f.get("bl"),
             "state": "bad" if f["name"] in wrong else "miss" if f.get("match") is None else "ok"}
            for f in cat.get("fields") or []]


def filter_href(category: str | None = None, status: str | None = None,
                reviewed: bool = False) -> str:
    """The inbox URL for one combination of header filters.

    Every filter link is built here, so choosing one keeps the others.
    Only BL_COMPARISON emails are compared, so only they carry a status or
    a review: a status never rides along to another category, where it
    could only ever show an empty list.
    """
    if category and category != "BL_COMPARISON":
        status, reviewed = None, False
    params = [(k, v) for k, v in (("category", category), ("status", status)) if v]
    if reviewed:
        params.append(("reviewed", "1"))
    return "/" + ("?" + "&".join(f"{k}={quote(v)}" for k, v in params) if params else "")


templates.env.globals["filter_href"] = filter_href


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


def graded_file(name: str) -> Path | None:
    """A graded result - score.json, submission.json - from the copy that
    ships with the code first. On a deploy OUT_DIR is a volume seeded once
    and never overwritten, so a file committed later would never reach it,
    and these are build results, not runtime state."""
    for base in (Path(ROOT) / "out", Path(OUT_DIR)):
        if (base / name).exists():
            return base / name
    return None


def load_score() -> dict | None:
    """The organizers' scorer output, saved as out/score.json. The answer
    key itself never ships; only these metrics do."""
    path = graded_file("score.json")
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("%s is not readable JSON", path)
        return None


def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def score_view(s: dict) -> dict:
    """Shape the scorer output for the page.

    Categories are listed in their fixed order, never by score, so a category
    keeps its row whatever happens to it. The confusion matrix is normalised
    by row - the share of each actual category predicted as each column - so
    a perfect run reads as a clean diagonal whatever the class sizes.
    """
    s1 = s.get("stage1", {})
    per = s1.get("per", {})
    categories = []
    for c in CATEGORIES:
        d = per.get(c, {})
        tp, fp, fn = d.get("tp", 0), d.get("fp", 0), d.get("fn", 0)
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        categories.append({
            "name": c, "correct": tp, "total": tp + fn,
            "precision": precision, "recall": recall,
            "f1": _ratio(2 * precision * recall, precision + recall),
        })

    confusion = s1.get("confusion", {})         # actual -> predicted -> n
    matrix = []
    for actual in CATEGORIES:
        row = confusion.get(actual, {})
        total = sum(row.values())
        matrix.append({"actual": actual, "total": total, "cells": [
            {"predicted": pred, "n": row.get(pred, 0),
             "share": _ratio(row.get(pred, 0), total), "hit": pred == actual}
            for pred in CATEGORIES]})
    off_diagonal = sum(c["n"] for r in matrix for c in r["cells"] if not c["hit"])

    rel = s.get("reliability", {})
    reasons = [{"name": k, "caught": v.get("caught", 0), "total": v.get("total", 0),
                "rate": _ratio(v.get("caught", 0), v.get("total", 0))}
               for k, v in rel.get("per_reason", {}).items()]

    w = s.get("weights", {})
    e2e = s.get("end_to_end", {})
    parts = [
        {"name": i18n.t("Stage 1"), "what": i18n.t("Email classification"), "weight": w.get("stage1", 0),
         "metric": "macro-F1", "value": s1.get("macro_f1", 0)},
        {"name": i18n.t("Stage 3"), "what": i18n.t("SI vs BL comparison"), "weight": w.get("stage3", 0),
         "metric": i18n.t("defect F1"), "value": s.get("stage3", {}).get("defect_f1", 0)},
        {"name": i18n.t("End-to-end"), "what": i18n.t("Defects caught all the way through"),
         "weight": w.get("end_to_end", 0), "metric": i18n.t("caught"),
         "value": e2e.get("rate", 0), "count": f'{e2e.get("success", 0)} / {e2e.get("total", 0)}'},
    ]
    for part in parts:
        part["contributes"] = part["weight"] * part["value"]

    return {"raw": s, "final": s.get("final_score", 0), "n": s.get("n_emails", 0),
            "parts": parts, "categories": categories, "matrix": matrix,
            "off_diagonal": off_diagonal, "reasons": reasons,
            "stage3": s.get("stage3", {}), "reliability": rel, "end_to_end": e2e}


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


@app.get("/tests", response_class=HTMLResponse)
def tests_page(request: Request):
    """The organizers' scorer, run against submission.json - on one page."""
    raw = load_score()
    view = load_view()
    # A reviewer's decision changes what the app shows, never submission.json,
    # so it cannot move the score. Counted so the page can say so.
    overrides = sum(1 for r in view.values() if r.get("reviewer_changed"))
    return templates.TemplateResponse(
        request=request, name="tests.html",
        context={"page": "tests", "score": score_view(raw) if raw else None,
                 "checks": checks.status(), "overrides": overrides,
                 **_shell(view, None, user=auth.current_user(request))},
    )


@app.post("/tests/run")
def tests_run():
    """Start the live checks. They run in the background and the page polls
    /tests/status; one run at a time, with a short cooldown between runs."""
    started, reason = checks.start(load_score)
    if not started:
        code = 409 if reason == "already running" else 429
        return JSONResponse({"started": False, "reason": reason, **checks.status()},
                            status_code=code)
    return JSONResponse({"started": True, **checks.status()}, status_code=202)


@app.get("/tests/export.csv")
def tests_export():
    """The graded answers for the 520 emails - submission.json - as a CSV
    file, the format the organizers asked for. Built from the JSON on every
    request, so the two can never disagree."""
    path = graded_file("submission.json")
    if path is None:
        raise HTTPException(status_code=404, detail=i18n.t("No submission file yet."))
    sub = json.loads(path.read_text(encoding="utf-8"))
    return Response(submission_csv(sub), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="mailops_submission.csv"'})


@app.get("/tests/status")
def tests_status():
    return JSONResponse(checks.status())


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
            "marks": _marks(cat),
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
                          error=i18n.t("That email and password do not match an account."),
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
                          error=i18n.t("That access code is not right."))
    if not acknowledge:
        return _auth_page(request, "register.html", status=400, **typed,
                          error=i18n.t("You need to acknowledge the audit logging policy."))
    try:
        auth.create_user(email, password, out_dir=OUT_DIR, name=name, desk=desk,
                         confirm=confirm)
    except ValueError as e:
        return _auth_page(request, "register.html", status=400, **typed, error=str(e))
    request.session[auth.SESSION_KEY] = auth.normalise(email)
    return RedirectResponse("/", status_code=303)


def forget_sent_mail() -> list[str]:
    """Delete the mail the app used to keep when it sent something, with its
    results and any review decision on it. Run at startup: the first start
    after this change clears a deploy's volume, and later ones find nothing."""
    gone = delete_sent(MAIL_DIR)
    if gone:
        forget(gone, OUT_DIR)
        review = load_review()
        if any(eid in review for eid in gone):
            save_review({eid: d for eid, d in review.items() if eid not in gone})
        log.info("deleted %d sent emails: %s", len(gone), ", ".join(gone))
    return gone


# Everything typed in while testing - received mail, what the AI made of it,
# reviewer decisions - is cleared once per tag, so the site shows the
# organizers' 520 emails and nothing else. Set SDOC_RESET to a new value on
# the host to clear again; a restart with the same value leaves it alone.
RESET = os.environ.get("SDOC_RESET", "2026-09-21-recording")


def start_clean(tag: str | None = None) -> bool:
    """Clear the deploy's volume back to the 520. True if it cleared.

    The results for the 520, the graded submission and the accounts are
    kept. Only ever a deploy's own volume: the repo's out/ and mail/ are
    never cleared, so a local run or a test cannot wipe them."""
    out, mail = Path(OUT_DIR), Path(MAIL_DIR)
    if Path(ROOT).resolve() in (out.resolve().parent, mail.resolve().parent):
        return False
    tag = "".join(c if c.isalnum() or c in "-_." else "_" for c in (tag or RESET))
    marker = out / f".reset-{tag}"
    if marker.exists():
        return False
    for folder in ("inbox", "attachments"):
        shutil.rmtree(mail / folder, ignore_errors=True)
    for name in ("mail_results.json", "review.json"):
        (out / name).unlink(missing_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    log.info("started clean (%s): received mail, its results and review decisions cleared", tag)
    return True


def _compose_page(request: Request, status: int = 200, **extra):
    return templates.TemplateResponse(
        request=request,
        name="compose.html",
        status_code=status,
        context={"page": "compose",
                 "max_attachments": MAX_ATTACHMENTS,
                 "max_mb": MAX_ATTACHMENT_BYTES // 1024 // 1024,
                 "can_send": bool(auth.current_user(request)),
                 "smtp_reachable": reachable(),
                 **extra,
                 **_shell(load_view(), None, user=auth.current_user(request))},
    )


@app.get("/compose", response_class=HTMLResponse)
def compose_form(request: Request):
    # Said once, after the redirect that follows a send, then gone.
    return _compose_page(request, sent_to=request.session.pop("sent_to", None))


@app.post("/compose")
async def compose_submit(request: Request, to: str = Form(""), subject: str = Form(""),
                         body: str = Form(""),
                         files: list[UploadFile] = File(default=[])):
    """Send the email, as it is, with its attachments. Nothing is stored and
    nothing is checked: the Triage Queue is for mail that arrives. The page
    waits the second or two Gmail takes to accept it, so it can say whether
    it went.

    Fields are declared optional and checked here. A required Form field
    that arrives empty is dropped by the encoder and reported as missing,
    which is a 422 full of schema noise; this way blank and whitespace-only
    both give the same readable 400.
    """
    if not auth.current_user(request):
        raise HTTPException(status_code=401, detail=i18n.t("Sign in to send mail."))

    to, subject = to.strip(), subject.strip()
    if not valid_address(to):
        raise HTTPException(status_code=400, detail=i18n.t("Not an email address: {to}", to=to))
    if not subject:
        raise HTTPException(status_code=400, detail=i18n.t("A subject is required."))

    uploads = [f for f in files if f.filename]
    if len(uploads) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=400,
                            detail=i18n.t("At most {n} attachments.", n=MAX_ATTACHMENTS))

    attachments = []
    for f in uploads:
        data = await f.read()
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=400,
                detail=i18n.t("{name} is too large (limit {mb} MB).", name=f.filename,
                              mb=MAX_ATTACHMENT_BYTES // 1024 // 1024))
        attachments.append((f.filename, data))

    # Sent from the desk's shared address, which is the only account the app
    # may send as - but named for the person, and replies go back to them.
    who = auth.current_user(request)
    who_name = (auth.get_user(who, OUT_DIR) or {}).get("name") or None
    try:
        await run_in_threadpool(send_mail, to, subject, body, attachments,
                                reply_to=who, sender_name=who_name)
    except Exception as e:
        log.warning("could not send to %s: %s", to, e)
        if "unreachable" in str(e).lower() or "outbound SMTP" in str(e):
            note_unreachable()      # stop offering what cannot work
        return _compose_page(request, status=502, send_error=f"{type(e).__name__}: {e}",
                             typed={"to": to, "subject": subject, "body": body})
    request.session["sent_to"] = to
    return RedirectResponse("/compose", status_code=303)


# The reasons sdoc.extract gives for a file it cannot read, word for word.
# Two more carry a detail and are translated in say_problem.
UNREADABLE = ("file not found", "file is empty",
              "no text layer - looks like a scanned image", "almost no readable text")

# The files a browser may show itself. Anything else is handed over as a
# download: received attachments come from anyone who emails the inbox, and
# an .html one shown by the browser would run as part of this site.
SHOWN_INLINE = {".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8"}


def say_problem(problem: str) -> str:
    """Why a file cannot be read, in the page language."""
    if problem.startswith("unsupported file type "):
        suffix = problem.rsplit(" ", 1)[1]
        return i18n.t("unsupported file type {suffix}", suffix=suffix)
    if problem.startswith("file is corrupt or cannot be opened ("):
        error = problem.rsplit("(", 1)[1].rstrip(")")
        return i18n.t("file is corrupt or cannot be opened ({error})", error=error)
    return i18n.t(problem)


def _original(path: str) -> FileResponse:
    file = attachment_path(path)
    if not file.is_file():
        raise HTTPException(status_code=404, detail=f"missing file: {path}")
    media = SHOWN_INLINE.get(file.suffix.lower())
    return FileResponse(file, media_type=media or "application/octet-stream", filename=file.name,
                        content_disposition_type="inline" if media else "attachment",
                        headers={"X-Content-Type-Options": "nosniff"})


@app.get("/attachment/{path:path}", response_class=HTMLResponse)
def attachment(path: str, view: str = ""):
    """The text read from an attachment. ?view=json is what the email page's
    viewer asks for; ?view=original is the file itself; with neither, a
    plain page of the text - where a ctrl-click on a file still goes."""
    # Path traversal guard: only ever serve files from the two attachment
    # folders - the bundle's and the received-mail one. Nothing else under
    # either directory, and no traversal out of them.
    if ".." in path or not path.startswith(("attachments/", "mail/attachments/")):
        raise HTTPException(status_code=400, detail="bad attachment path")
    if view == "original":
        return _original(path)

    doc = read_document(path)
    if doc.problem == "file not found":
        raise HTTPException(status_code=404, detail=f"missing file: {path}")
    if view == "json":
        return JSONResponse({"name": path.split("/")[-1], "text": doc.text, "readable": doc.readable,
                             "problem": say_problem(doc.problem) if doc.problem else None})
    text = doc.text if doc.readable else "(" + i18n.t(
        "This file cannot be read: {problem}.", problem=say_problem(doc.problem)) + ")"

    name = escape(path.split("/")[-1])
    return HTMLResponse(
        f"<!doctype html><html lang='{i18n.HTML_LANG[i18n.current()]}'><head><meta charset='utf-8'>"
        f"<title>{name}</title>"
        "<style>:root{color-scheme:light dark}"
        "body{margin:0;font-family:ui-monospace,'JetBrains Mono',Menlo,Consolas,monospace}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:24px;"
        "font-size:13px;line-height:1.6;margin:0}</style></head>"
        f"<body><pre>{escape(text)}</pre></body></html>"
    )
