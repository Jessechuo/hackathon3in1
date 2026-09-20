# Receiving Mail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a new email arrive — typed into a compose form, or sent to a real Gmail address — and be classified and compared automatically, with the result appearing in the app.

**Architecture:** Received mail is stored in its own directory (`mail/`) under its own `mail_NNNN` ids, never in the organizers' bundle. One function, `ingest()`, takes a received email from arrival to a decision by reusing the existing `classify()` and `process()` unchanged, and writes to `out/mail_results.json`. The web app merges bundle results and mail results for display. Two front doors feed the same `ingest()`: a compose form in the UI (Part A, no network) and an IMAP poller against Gmail (Part B).

**Tech Stack:** Python 3.11+, FastAPI + Jinja2, `python-multipart` (new — FastAPI file uploads), stdlib `imaplib` and `email` (no new dependency for Gmail).

**Spec:** `docs/superpowers/specs/2026-09-19-sdoc-verification-design.md` — this plan extends it with an ingest path. The spec's rules about escalation, the four review reasons and "AI reads, code decides" are unchanged and must stay unchanged: received mail goes through the exact same `pipeline.process()`.

## Global Constraints

- **The bundle is read-only.** Nothing may write into `sdoc-hackathon-bundle/`. It is the graded dataset.
- **`out/submission.json` must contain exactly the 520 bundle ids.** Received mail never enters it. `sdoc/inbox.py::load_emails()` stays bundle-only for this reason; the UI uses a new `load_all_emails()`.
- **`out/results.json` belongs to the bundle.** A full `python -m sdoc.run_pipeline` rewrites it from the 520 bundle ids and would drop anything else, so received results live in `out/mail_results.json`.
- **Commits are authored `CHUO JESSE` only.** No `Co-Authored-By` lines, no `Generated with` lines, in any commit message in this plan.
- **Tests never touch the network and never need an API key.** Every LLM call is replaced by a test double, as in the existing 121 tests.
- **No em-dashes or box characters in anything printed to a console.** The Windows default console encoding crashes on them. Plain hyphens only in log lines.
- **Secrets go in `.env`,** which is already gitignored (`.env`, `.env.*`, `*.env`, `.env.txt`). Never commit a mail password.
- **Filenames arriving from email are untrusted.** Directory parts must be stripped before anything is written to disk.
- Run `python -m pytest -q` before every commit. It must stay green.

---

## File Structure

| File | Responsibility |
|---|---|
| `sdoc/config.py` (modify) | Add `MAIL_DIR`. Still the only place a path is named. |
| `sdoc/inbox.py` (modify) | Add `load_received()`, `load_all_emails()`, `attachment_path()`. Still knows nothing about AI. |
| `sdoc/mail/store.py` (create) | Writing a received email to disk: id allocation, safe filenames. No AI, no network. |
| `sdoc/mail/parse.py` (create) | RFC 822 bytes -> sender/subject/body/attachments. Pure; no network. |
| `sdoc/mail/gmail.py` (create) | IMAP connection. The only file that talks to a mail server. |
| `sdoc/ingest.py` (create) | One received email -> classified, compared, saved. Reuses `classify()` and `process()`. |
| `sdoc/run_watch.py` (create) | CLI: poll the mailbox, ingest what arrives. |
| `sdoc/web/app.py` (modify) | Merge mail results into the view; compose routes; serve mail attachments. |
| `sdoc/web/templates/compose.html` (create) | The compose form. |
| `sdoc/web/templates/base.html` (modify) | Rail link to compose, a plus icon, the mail address in the header. |

Dependencies still point inward: `mail/` knows files and MIME but not AI; `ingest.py` knows both but not the web layer; `web/` calls `ingest()` and knows nothing about IMAP.

---

## Part A — the compose form (Tasks 1-4)

Delivers a working "new email arrives, gets classified and compared" demo with no network dependency at all.

### Task 1: A place to put received mail

**Files:**
- Modify: `sdoc/config.py`
- Modify: `sdoc/inbox.py`
- Create: `sdoc/mail/__init__.py` (empty)
- Create: `sdoc/mail/store.py`
- Test: `tests/mail/__init__.py` (empty), `tests/mail/test_store.py`

**Interfaces:**
- Consumes: `sdoc.config.MAIL_DIR`
- Produces:
  - `sdoc.mail.store.next_id(root: Path | None = None) -> str` — `"mail_0001"`
  - `sdoc.mail.store.safe_name(email_id: str, filename: str) -> str`
  - `sdoc.mail.store.save_email(sender: str, subject: str, body: str, attachments: list[tuple[str, bytes]], root: Path | None = None, email_id: str | None = None) -> dict`
  - `sdoc.inbox.load_received() -> list[dict]`
  - `sdoc.inbox.load_all_emails() -> list[dict]`
  - `sdoc.inbox.attachment_path(rel_path: str) -> Path`

- [ ] **Step 1: Write the failing tests**

Create `tests/mail/__init__.py` as an empty file, then `tests/mail/test_store.py`:

```python
import json
from pathlib import Path

import pytest

from sdoc import inbox
from sdoc.mail import store
from sdoc.pipeline import _assign


def test_ids_start_at_one_and_count_up(tmp_path):
    assert store.next_id(tmp_path) == "mail_0001"
    store.save_email("a@b.com", "s", "b", [], root=tmp_path)
    assert store.next_id(tmp_path) == "mail_0002"


def test_saved_email_has_the_same_shape_as_a_bundle_email(tmp_path):
    email = store.save_email("docs@shipper.sg", "Check this BL", "Hi,\nPlease check.",
                             [("SI.txt", b"SHIPPER: ACME")], root=tmp_path)
    assert email["email_id"] == "mail_0001"
    assert email["from"] == "docs@shipper.sg"
    assert email["subject"] == "Check this BL"
    assert email["attachments"] == ["mail/attachments/mail_0001__SI.txt"]
    on_disk = json.loads((tmp_path / "inbox" / "mail_0001.json").read_text(encoding="utf-8"))
    assert on_disk == email


def test_attachment_bytes_are_written_unchanged(tmp_path):
    store.save_email("a@b.com", "s", "b", [("BL.txt", b"BILL OF LADING")], root=tmp_path)
    assert (tmp_path / "attachments" / "mail_0001__BL.txt").read_bytes() == b"BILL OF LADING"


def test_a_senders_filename_cannot_escape_the_attachments_folder(tmp_path):
    email = store.save_email("a@b.com", "s", "b",
                             [("../../../etc/passwd", b"x"),
                              ("C:\\Windows\\System32\\evil.txt", b"y")], root=tmp_path)
    assert email["attachments"] == ["mail/attachments/mail_0001__passwd",
                                    "mail/attachments/mail_0001__evil.txt"]
    assert sorted(p.name for p in (tmp_path / "attachments").iterdir()) == [
        "mail_0001__evil.txt", "mail_0001__passwd"]


def test_odd_characters_in_a_filename_are_replaced(tmp_path):
    email = store.save_email("a@b.com", "s", "b", [("my SI (final).txt", b"x")], root=tmp_path)
    assert email["attachments"] == ["mail/attachments/mail_0001__my_SI_final_.txt"]


def test_the_prefix_keeps_si_and_bl_recognisable_to_the_pipeline(tmp_path):
    """pipeline._assign looks for `_SI.` / `_BL.`; the `__` prefix supplies it."""
    email = store.save_email("a@b.com", "s", "b",
                             [("SI.txt", b"x"), ("BL.txt", b"y")], root=tmp_path)
    si, bl = _assign(email["attachments"])
    assert si == "mail/attachments/mail_0001__SI.txt"
    assert bl == "mail/attachments/mail_0001__BL.txt"


@pytest.fixture
def mail_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "MAIL_DIR", tmp_path)
    return tmp_path


def test_load_received_is_empty_before_anything_arrives(mail_dir):
    assert inbox.load_received() == []


def test_load_received_returns_saved_mail_in_order(mail_dir):
    store.save_email("a@b.com", "first", "b", [], root=mail_dir)
    store.save_email("c@d.com", "second", "b", [], root=mail_dir)
    assert [e["subject"] for e in inbox.load_received()] == ["first", "second"]


def test_load_all_emails_is_the_bundle_plus_what_arrived(mail_dir):
    bundle = inbox.load_emails()
    store.save_email("a@b.com", "new", "b", [], root=mail_dir)
    everything = inbox.load_all_emails()
    assert len(everything) == len(bundle) + 1
    assert everything[-1]["email_id"] == "mail_0001"
    # load_emails stays bundle-only: submission.json depends on it
    assert len(inbox.load_emails()) == len(bundle)


def test_mail_attachments_resolve_to_the_mail_folder(mail_dir):
    store.save_email("a@b.com", "s", "b", [("SI.txt", b"hello")], root=mail_dir)
    assert inbox.read_attachment_bytes("mail/attachments/mail_0001__SI.txt") == b"hello"


def test_bundle_attachments_still_resolve_to_the_bundle(mail_dir):
    assert inbox.attachment_path("attachments/email_004_SI.txt") == (
        Path(inbox.BUNDLE_DIR) / "attachments" / "email_004_SI.txt")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/mail/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.mail'`

- [ ] **Step 3: Add `MAIL_DIR` to the config**

In `sdoc/config.py`, immediately after the `CACHE_DIR` line, add:

```python
# Mail that arrives after the bundle - typed into the compose form or fetched
# from a mailbox. Kept apart from BUNDLE_DIR on purpose: the bundle is the
# graded dataset and its 520 ids are exactly what submission.json must hold.
MAIL_DIR = Path(os.environ.get("SDOC_MAIL", ROOT / "mail"))
```

- [ ] **Step 4: Teach `inbox.py` about received mail**

Replace the whole of `sdoc/inbox.py` with:

```python
"""Reads the participant bundle, plus any mail received since. Knows nothing
about AI or comparison."""
import json
from pathlib import Path

from sdoc.config import BUNDLE_DIR, MAIL_DIR

# Received attachments carry this prefix so one look at the path says which
# folder it lives in. The bundle's own paths start "attachments/".
MAIL_PREFIX = "mail/"


def load_emails() -> list[dict]:
    """The organizers' 520. Stays bundle-only: run_pipeline builds
    submission.json from these ids, and a stray id there is invalid."""
    inbox_dir = Path(BUNDLE_DIR) / "inbox"
    paths = sorted(inbox_dir.glob("email_*.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def load_received() -> list[dict]:
    """Mail that arrived after the bundle, oldest first."""
    inbox_dir = Path(MAIL_DIR) / "inbox"
    if not inbox_dir.exists():
        return []
    paths = sorted(inbox_dir.glob("mail_*.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def load_all_emails() -> list[dict]:
    """Everything the app shows: the bundle first, then what arrived."""
    return load_emails() + load_received()


def attachment_path(rel_path: str) -> Path:
    if rel_path.startswith(MAIL_PREFIX):
        return Path(MAIL_DIR) / rel_path[len(MAIL_PREFIX):]
    return Path(BUNDLE_DIR) / rel_path


def read_attachment_bytes(rel_path: str) -> bytes:
    return attachment_path(rel_path).read_bytes()


def read_attachment_text(rel_path: str) -> str:
    # errors="replace" because several attachments are deliberately corrupt.
    # Detecting that is the pipeline's job; reading must never raise here.
    return read_attachment_bytes(rel_path).decode("utf-8", errors="replace")
```

- [ ] **Step 5: Write the store**

Create `sdoc/mail/__init__.py` as an empty file, then `sdoc/mail/store.py`:

```python
"""Writing a received email to disk. No AI, no network, no shipping knowledge.

Everything here lands under MAIL_DIR, never in the bundle: the bundle is the
graded dataset and must not grow an email the organizers did not send.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sdoc.config import MAIL_DIR

# Anything outside this set is replaced. Filenames come from email and are
# not trusted: directory parts are dropped before this runs.
UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else Path(MAIL_DIR)


def next_id(root: Path | None = None) -> str:
    inbox_dir = _root(root) / "inbox"
    used = []
    if inbox_dir.exists():
        for p in inbox_dir.glob("mail_*.json"):
            try:
                used.append(int(p.stem.split("_")[1]))
            except (IndexError, ValueError):
                continue
    return f"mail_{max(used, default=0) + 1:04d}"


def safe_name(email_id: str, filename: str) -> str:
    """`SI.txt` -> `mail_0001__SI.txt`.

    The double underscore is not decoration. pipeline._assign decides which
    file is the SI and which is the BL by looking for `_SI.` / `_BL.` in the
    name, so prefixing makes a sender's plain `SI.txt` recognisable.
    """
    base = Path(filename.replace("\\", "/")).name
    cleaned = UNSAFE.sub("_", base).lstrip(".")
    return f"{email_id}__{cleaned or 'file'}"


def save_email(sender: str, subject: str, body: str,
               attachments: list[tuple[str, bytes]],
               root: Path | None = None, email_id: str | None = None) -> dict:
    """Write one received email and its files. Returns the email dict, in
    exactly the shape load_emails() yields for a bundle email."""
    base = _root(root)
    eid = email_id or next_id(base)
    (base / "inbox").mkdir(parents=True, exist_ok=True)
    (base / "attachments").mkdir(parents=True, exist_ok=True)

    rels = []
    for filename, data in attachments:
        name = safe_name(eid, filename)
        (base / "attachments" / name).write_bytes(data)
        rels.append(f"mail/attachments/{name}")

    email = {
        "email_id": eid,
        "from": sender,
        "subject": subject,
        "body": body,
        "attachments": rels,
        # Extra key; the bundle has no equivalent. Consumers ignore unknown
        # keys, and the UI uses it to show when something arrived.
        "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (base / "inbox" / f"{eid}.json").write_text(json.dumps(email, indent=2), encoding="utf-8")
    return email
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/mail/test_store.py -q`
Expected: PASS, 11 tests

Then the whole suite, to prove the `inbox.py` rewrite broke nothing:

Run: `python -m pytest -q`
Expected: PASS, 132 tests

- [ ] **Step 7: Ignore the mail folder**

Append to `.gitignore`:

```
# Mail received at runtime - local state, like out/ and .cache/
mail/
```

- [ ] **Step 8: Commit**

```bash
git add sdoc/config.py sdoc/inbox.py sdoc/mail/ tests/mail/ .gitignore
git commit -m "feat: somewhere to put mail that arrives after the bundle"
```

---

### Task 2: One received email, from arrival to a decision

**Files:**
- Create: `sdoc/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `sdoc.ai.classify.classify(email) -> Classification`, `sdoc.pipeline.process(email, cls) -> dict`, `sdoc.pipeline.base_result(cls) -> dict`
- Produces:
  - `sdoc.ingest.ingest(email: dict, out_dir: Path | None = None) -> dict`
  - `sdoc.ingest.load_mail_results(out_dir: Path | None = None) -> dict`
  - `sdoc.ingest.save_mail_results(state: dict, out_dir: Path | None = None) -> None`

`out_dir` is an explicit parameter, not read from the module global, because the web app passes its own `OUT_DIR` so the existing test fixtures (`monkeypatch.setattr(web, "OUT_DIR", tmp_path)`) keep working unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingest.py`:

```python
import json

import pytest

from sdoc import ingest as ing
from sdoc.ai.classify import Classification

EMAIL = {"email_id": "mail_0001", "from": "a@b.com", "subject": "Check this BL",
         "body": "Please compare the attached.", "attachments": []}


def fake_classification(category="BL_COMPARISON", attached=False):
    return Classification(category=category, documents_meant_to_be_attached=attached,
                          reason="test")


def test_a_received_email_is_classified_and_compared(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("SPAM"))
    result = ing.ingest(EMAIL, out_dir=tmp_path)
    assert result["category"] == "SPAM"
    assert result["status"] == "OK"


def test_the_result_is_written_where_the_app_can_find_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("GENERAL"))
    ing.ingest(EMAIL, out_dir=tmp_path)
    saved = json.loads((tmp_path / "mail_results.json").read_text(encoding="utf-8"))
    assert saved["mail_0001"]["category"] == "GENERAL"


def test_ingesting_a_second_email_keeps_the_first(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("GENERAL"))
    ing.ingest(EMAIL, out_dir=tmp_path)
    ing.ingest({**EMAIL, "email_id": "mail_0002"}, out_dir=tmp_path)
    assert sorted(ing.load_mail_results(tmp_path)) == ["mail_0001", "mail_0002"]


def test_a_document_check_with_no_attachments_escalates(tmp_path, monkeypatch):
    """The promise of attachments with none present is the missing_attachment gate."""
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("BL_COMPARISON", True))
    result = ing.ingest(EMAIL, out_dir=tmp_path)
    assert result["status"] == "NEEDS_REVIEW"
    assert result["review_reason"] == "missing_attachment"


def test_a_classification_failure_does_not_take_the_watcher_down(tmp_path, monkeypatch):
    def boom(email):
        raise RuntimeError("api is down")
    monkeypatch.setattr(ing, "classify", boom)
    result = ing.ingest(EMAIL, out_dir=tmp_path)
    assert result["category"] == "GENERAL"
    assert "api is down" in result["error"]


def test_a_processing_failure_is_recorded_as_needing_review(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "classify", lambda e: fake_classification("BL_COMPARISON"))

    def boom(email, cls):
        raise RuntimeError("pdf exploded")
    monkeypatch.setattr(ing, "process", boom)
    result = ing.ingest(EMAIL, out_dir=tmp_path)
    assert result["status"] == "NEEDS_REVIEW"
    assert result["failed"] is True
    assert "pdf exploded" in result["error"]


def test_no_results_file_yet_is_not_an_error(tmp_path):
    assert ing.load_mail_results(tmp_path) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_ingest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.ingest'`

- [ ] **Step 3: Write the ingest module**

Create `sdoc/ingest.py`:

```python
"""A received email, taken from arrival to a decision.

The same two steps the batch runners do - classify, then compare - but for
one email at a time. Both steps are the untouched functions the graded run
uses, so a received email is judged by exactly the same rules.

Results go to mail_results.json, not results.json: a full `run_pipeline`
rewrites results.json from the 520 bundle ids and would drop anything else.
"""
import json
import logging
import traceback
from pathlib import Path

from sdoc.ai.classify import classify
from sdoc.config import OUT_DIR
from sdoc.pipeline import base_result, process

log = logging.getLogger(__name__)

MAIL_RESULTS = "mail_results.json"


def _dir(out_dir: Path | None) -> Path:
    return Path(out_dir) if out_dir is not None else Path(OUT_DIR)


def load_mail_results(out_dir: Path | None = None) -> dict:
    path = _dir(out_dir) / MAIL_RESULTS
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_mail_results(state: dict, out_dir: Path | None = None) -> None:
    base = _dir(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    (base / MAIL_RESULTS).write_text(json.dumps(state, indent=2), encoding="utf-8")


def ingest(email: dict, out_dir: Path | None = None) -> dict:
    """Classify, compare if it is a document check, save, return the result.

    Never raises. A watcher runs unattended, so one bad email records its own
    failure and the next one still gets processed - the same bargain
    run_classify and run_pipeline already make.
    """
    try:
        c = classify(email)
        cls = {"category": c.category,
               "documents_meant_to_be_attached": c.documents_meant_to_be_attached,
               "reason": c.reason, "error": None}
    except Exception:
        log.warning("classification failed for %s", email["email_id"])
        cls = {"category": "GENERAL", "documents_meant_to_be_attached": None,
               "reason": "classification failed", "error": traceback.format_exc()}

    try:
        result = process(email, cls)
    except Exception:
        log.warning("processing failed for %s", email["email_id"])
        result = base_result(cls)
        result.update(status="NEEDS_REVIEW", review_reason="unreadable", failed=True,
                      note="Processing failed before a decision was reached - see the error.",
                      error=traceback.format_exc())

    state = load_mail_results(out_dir)
    state[email["email_id"]] = result
    save_mail_results(state, out_dir)
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_ingest.py -q`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add sdoc/ingest.py tests/test_ingest.py
git commit -m "feat: classify and compare a single received email"
```

---

### Task 3: The app shows received mail

**Files:**
- Modify: `sdoc/web/app.py`
- Test: `tests/test_received_mail_in_ui.py`

**Interfaces:**
- Consumes: `sdoc.inbox.load_all_emails`, `sdoc.inbox.attachment_path`, `sdoc.ingest.load_mail_results`
- Produces: `sdoc.web.app.load_results()` now returns bundle results with mail results merged on top; `_shell()` context gains `n_received`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_received_mail_in_ui.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.mail import store
from sdoc.web import app as web


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Three patches, one per module that resolves a directory at call time:
    the app's output dir, the app's mail dir, and the loader's mail dir."""
    out, mail = tmp_path / "out", tmp_path / "mail"
    out.mkdir()
    monkeypatch.setattr(web, "OUT_DIR", out)
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)
    return TestClient(web.app), out, mail


def test_a_received_email_appears_in_the_inbox(site):
    client, out, mail = site
    store.save_email("captain@line.com", "Please check BL", "body", [], root=mail)
    html = client.get("/").text
    assert 'data-id="mail_0001"' in html
    assert "Please check BL" in html


def test_its_verdict_comes_from_mail_results(site):
    client, out, mail = site
    store.save_email("a@b.com", "s", "b", [], root=mail)
    (out / "mail_results.json").write_text(json.dumps({
        "mail_0001": {"category": "BL_COMPARISON", "status": "MISMATCH",
                      "has_defect": True, "defect_fields": ["shipper"], "fields": []}}),
        encoding="utf-8")
    assert web.load_results()["mail_0001"]["status"] == "MISMATCH"
    assert 'data-id="mail_0001"' in client.get("/?status=MISMATCH").text


def test_bundle_results_and_mail_results_live_side_by_side(site):
    client, out, mail = site
    (out / "results.json").write_text(
        json.dumps({"email_001": {"category": "SPAM", "status": "OK"}}), encoding="utf-8")
    (out / "mail_results.json").write_text(
        json.dumps({"mail_0001": {"category": "SPAM", "status": "OK"}}), encoding="utf-8")
    results = web.load_results()
    assert "email_001" in results and "mail_0001" in results


def test_the_detail_page_opens_for_a_received_email(site):
    client, out, mail = site
    store.save_email("a@b.com", "Draft BL attached", "Please compare.", [], root=mail)
    r = client.get("/email/mail_0001")
    assert r.status_code == 200
    assert "Draft BL attached" in r.text


def test_a_received_attachment_can_be_opened(site):
    client, out, mail = site
    store.save_email("a@b.com", "s", "b",
                     [("SI.txt", b"SHIPPER: ACME LOGISTICS PTE LTD\nPOL: SINGAPORE")],
                     root=mail)
    r = client.get("/attachment/mail/attachments/mail_0001__SI.txt")
    assert r.status_code == 200
    assert "ACME LOGISTICS" in r.text


def test_a_path_outside_the_two_attachment_folders_is_refused(site):
    client, _, _ = site
    for bad in ("/attachment/mail/../secrets.txt",
                "/attachment/out/ground_truth.json",
                "/attachment/mail/inbox/mail_0001.json"):
        assert client.get(bad).status_code == 400


def test_the_header_counts_what_arrived(site):
    client, out, mail = site
    store.save_email("a@b.com", "s", "b", [], root=mail)
    assert "1 received" in client.get("/").text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_received_mail_in_ui.py -q`
Expected: FAIL — `AttributeError: <module 'sdoc.web.app'> does not have the attribute 'MAIL_DIR'`

- [ ] **Step 3: Update the imports in `sdoc/web/app.py`**

Replace these three import lines:

```python
from sdoc.config import BUNDLE_DIR, OUT_DIR
from sdoc.extract import read_document
from sdoc.inbox import load_emails
```

with:

```python
from sdoc.config import MAIL_DIR, OUT_DIR
from sdoc.extract import read_document
from sdoc.ingest import load_mail_results
from sdoc.inbox import attachment_path, load_all_emails
```

`BUNDLE_DIR` and `load_emails` are no longer used in this file: the app shows everything, and paths are resolved by `attachment_path`.

- [ ] **Step 4: Merge mail results into the view**

Replace `load_results()`:

```python
def load_results() -> dict:
    """Pipeline output, or {} before it has run.

    Prefers results.json (category + verification status) and falls back to
    categories.json (category only). Anything received since the bundle is
    merged on top - it is kept in its own file because a full run_pipeline
    rewrites results.json from the 520 bundle ids.
    """
    out = Path(OUT_DIR)
    results = {}
    for name in ("results.json", "categories.json"):
        path = out / name
        if path.exists():
            results = json.loads(path.read_text(encoding="utf-8"))
            break
    return {**results, **load_mail_results(OUT_DIR)}
```

- [ ] **Step 5: Resolve attachment paths through the loader**

In `_attachment_meta`, replace:

```python
        p = Path(BUNDLE_DIR) / rel
```

with:

```python
        p = attachment_path(rel)
```

- [ ] **Step 6: Count received mail in the shell context**

In `_shell()`, add one key to the returned dict, immediately after `"n_reviewed": ...`:

```python
        "n_received": sum(1 for eid in results if eid.startswith("mail_")),
```

Then in `sdoc/web/templates/base.html`, replace this line:

```html
  <span class="chip-count">{% block count %}{{ total }} emails{% endblock %}</span>
```

with:

```html
  <span class="chip-count">{% block count %}{{ total }} emails{% endblock %}</span>
  {% if n_received %}<span class="chip-count">{{ n_received }} received</span>{% endif %}
```

- [ ] **Step 7: Show every email, not just the bundle's**

Replace each of the four `load_emails()` calls in `sdoc/web/app.py` with `load_all_emails()`:

- in `dashboard()`: `"total": len(load_all_emails()),`
- in `inbox()`: `all_emails = load_all_emails()`
- in `email_detail()`: `ordered = load_all_emails()`
- in `record_review()`: `if not any(e["email_id"] == email_id for e in load_all_emails()):`

- [ ] **Step 8: Let the attachment route serve received files**

In `attachment()`, replace the guard:

```python
    # Path traversal guard: only serve files inside the bundle's attachments/.
    if not path.startswith("attachments/") or ".." in path:
        raise HTTPException(status_code=400, detail="bad attachment path")
```

with:

```python
    # Path traversal guard: only ever serve files from the two attachment
    # folders - the bundle's and the received-mail one. Nothing else under
    # either directory, and no traversal out of them.
    if ".." in path or not path.startswith(("attachments/", "mail/attachments/")):
        raise HTTPException(status_code=400, detail="bad attachment path")
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python -m pytest tests/test_received_mail_in_ui.py -q`
Expected: PASS, 7 tests

Run: `python -m pytest -q`
Expected: PASS, 146 tests

- [ ] **Step 10: Commit**

```bash
git add sdoc/web/app.py sdoc/web/templates/base.html tests/test_received_mail_in_ui.py
git commit -m "feat: received mail appears in the inbox alongside the bundle"
```

---

### Task 4: The compose form

**Files:**
- Modify: `requirements.txt`
- Modify: `sdoc/web/app.py`
- Create: `sdoc/web/templates/compose.html`
- Modify: `sdoc/web/templates/base.html`
- Test: `tests/test_compose.py`

**Interfaces:**
- Consumes: `sdoc.mail.store.save_email`, `sdoc.ingest.ingest`
- Produces: `GET /compose` (the form), `POST /compose` (303 redirect to `/email/{id}`)

- [ ] **Step 1: Add the upload dependency**

FastAPI raises at import time on a `Form`/`File` route without it. Append to `requirements.txt`:

```
python-multipart>=0.0.9
```

Run: `python -m pip install -r requirements.txt`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_compose.py`:

```python
import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.web import app as web


@pytest.fixture
def site(tmp_path, monkeypatch):
    out, mail = tmp_path / "out", tmp_path / "mail"
    out.mkdir()
    monkeypatch.setattr(web, "OUT_DIR", out)
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)

    seen = []
    # The real ingest calls Claude. Record the email instead.
    monkeypatch.setattr(web, "ingest", lambda email, out_dir=None: seen.append(email))
    return TestClient(web.app), mail, seen


def test_the_form_asks_for_what_an_email_needs(site):
    client, _, _ = site
    html = client.get("/compose").text
    for field in ('name="sender"', 'name="subject"', 'name="body"', 'name="files"'):
        assert field in html


def test_sending_stores_the_email_and_opens_its_page(site):
    client, mail, seen = site
    r = client.post("/compose", data={
        "sender": "ops@shipper.com", "subject": "Check BL vs SI", "body": "Attached."},
        files=[("files", ("SI.txt", b"SHIPPER: ACME", "text/plain")),
               ("files", ("BL.txt", b"SHIPPER: ACME CORP", "text/plain"))],
        follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/email/mail_0001"
    assert (mail / "attachments" / "mail_0001__SI.txt").read_bytes() == b"SHIPPER: ACME"
    assert [e["email_id"] for e in inbox.load_received()] == ["mail_0001"]


def test_the_new_email_goes_straight_through_the_pipeline(site):
    client, _, seen = site
    client.post("/compose", data={"sender": "a@b.com", "subject": "s", "body": "b"},
                follow_redirects=False)
    assert [e["subject"] for e in seen] == ["s"]


def test_sending_with_no_attachments_is_allowed(site):
    client, _, _ = site
    r = client.post("/compose", data={"sender": "a@b.com", "subject": "s", "body": "b"},
                    follow_redirects=False)
    assert r.status_code == 303


def test_a_blank_sender_or_subject_is_refused(site):
    client, _, _ = site
    for data in ({"sender": "  ", "subject": "s", "body": "b"},
                 {"sender": "a@b.com", "subject": "", "body": "b"}):
        assert client.post("/compose", data=data, follow_redirects=False).status_code == 400


def test_too_many_attachments_are_refused(site):
    client, _, _ = site
    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(6)]
    r = client.post("/compose", data={"sender": "a@b.com", "subject": "s", "body": "b"},
                    files=files, follow_redirects=False)
    assert r.status_code == 400
    assert "at most" in r.json()["detail"]


def test_an_oversized_attachment_is_refused(site):
    client, _, _ = site
    big = b"x" * (web.MAX_ATTACHMENT_BYTES + 1)
    r = client.post("/compose", data={"sender": "a@b.com", "subject": "s", "body": "b"},
                    files=[("files", ("big.txt", big, "text/plain"))], follow_redirects=False)
    assert r.status_code == 400
    assert "too large" in r.json()["detail"]


def test_the_rail_links_to_the_form(site):
    client, _, _ = site
    assert 'href="/compose"' in client.get("/").text
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_compose.py -q`
Expected: FAIL — `AttributeError: module 'sdoc.web.app' has no attribute 'ingest'`

- [ ] **Step 4: Add the routes**

In `sdoc/web/app.py`, extend the FastAPI import line:

```python
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
```

and the response import line:

```python
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
```

and add to the `sdoc.ingest` import:

```python
from sdoc.ingest import ingest, load_mail_results
```

and the store:

```python
from sdoc.mail.store import save_email
```

Below the `KINDS` dict, add the limits:

```python
# A person typing a demo email, not a mail server: small, sane caps so a
# misdropped file cannot fill the disk or run up an extraction bill.
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
```

Then add both routes immediately before the `@app.get("/attachment/...")` route:

```python
@app.get("/compose", response_class=HTMLResponse)
def compose_form(request: Request):
    results = load_view()
    return templates.TemplateResponse(
        request=request,
        name="compose.html",
        context={"page": "compose", "total": len(load_all_emails()), **_shell(results, None)},
    )


@app.post("/compose")
async def compose_submit(sender: str = Form(...), subject: str = Form(...),
                         body: str = Form(""), files: list[UploadFile] = File(default=[])):
    """Take a typed email exactly as if it had arrived, then run it through
    the same classify-and-compare the batch runner uses."""
    if not sender.strip() or not subject.strip():
        raise HTTPException(status_code=400, detail="sender and subject are required")

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

    email = save_email(sender.strip(), subject.strip(), body, attachments, root=MAIL_DIR)
    ingest(email, out_dir=OUT_DIR)
    return RedirectResponse(f"/email/{email['email_id']}", status_code=303)
```

- [ ] **Step 5: Write the form template**

Create `sdoc/web/templates/compose.html`:

```html
{% extends "base.html" %}
{% block title %}New email{% endblock %}
{% block count %}{{ total }} emails{% endblock %}

{% block content %}
<style>
  .compose { max-width:720px; padding:var(--lg); }
  .compose h1 { margin:0 0 var(--xs); }
  .compose .lede { color:var(--fg-2); margin:0 0 var(--lg); max-width:60ch; }
  .field { display:block; margin-bottom:var(--md); }
  .field > span { display:block; font-size:12px; letter-spacing:.04em;
    text-transform:uppercase; color:var(--fg-2); margin-bottom:6px; }
  .field input[type=text], .field textarea, .field input[type=file] {
    width:100%; box-sizing:border-box; padding:10px 12px;
    border:1px solid var(--line); border-radius:4px;
    background:var(--bg); color:var(--fg); font:inherit; }
  .field textarea { min-height:180px; resize:vertical; line-height:1.6; }
  .field input:focus, .field textarea:focus { outline:2px solid var(--primary); outline-offset:-1px; }
  .hint { color:var(--fg-2); font-size:12px; margin-top:6px; }
  .send { display:inline-flex; align-items:center; gap:8px; padding:10px 18px;
    border:0; border-radius:4px; background:var(--primary); color:var(--on-primary);
    font:inherit; font-weight:600; cursor:pointer; }
  .send:hover { filter:brightness(1.08); }
</style>

<div class="compose">
  <h1 class="t-headline-sm">New email</h1>
  <p class="lede">Sends this through the same classifier and the same comparison the
  graded run uses. Nothing here is hard-coded: whatever you type is read by Claude
  for the first time.</p>

  <form method="post" action="/compose" enctype="multipart/form-data">
    <label class="field">
      <span>From</span>
      <input type="text" name="sender" required placeholder="ops@shipper.com">
    </label>
    <label class="field">
      <span>Subject</span>
      <input type="text" name="subject" required
             placeholder="Please check draft BL against SI - PO 26067">
    </label>
    <label class="field">
      <span>Body</span>
      <textarea name="body" placeholder="Hi,&#10;&#10;Attached are the SI and draft BL. Please check the details and confirm.&#10;&#10;Thanks"></textarea>
    </label>
    <label class="field">
      <span>Attachments</span>
      <input type="file" name="files" multiple>
      <span class="hint">Up to {{ 5 }} files, 2 MB each. Name them so SI and BL are
      tellable apart - <code>SI.txt</code> and <code>BL.txt</code> is enough.
      txt, pdf, docx and xlsx can be read.</span>
    </label>
    <button class="send" type="submit">
      <svg class="ico ico-sm"><use href="#i-send"/></svg> Send to inbox
    </button>
    <p class="hint">Classification and comparison run now, so this costs about
    2 cents of API credit.</p>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 6: Add the icon and the rail link**

In `sdoc/web/templates/base.html`, inside `<defs>`, next to the other symbols, add:

```html
  <symbol id="i-send" viewBox="0 0 24 24"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/></symbol>
```

Then in the rail's `<nav>`, immediately after the Triage Queue link, add:

```html
    <a href="/compose" aria-current="{{ 'page' if page == 'compose' else 'false' }}" title="New email"><svg class="ico ico-lg"><use href="#i-send"/></svg><span class="vh">New email</span></a>
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_compose.py -q`
Expected: PASS, 8 tests

Run: `python -m pytest -q`
Expected: PASS, 154 tests

- [ ] **Step 8: Commit**

```bash
git add requirements.txt sdoc/web/app.py sdoc/web/templates/compose.html sdoc/web/templates/base.html tests/test_compose.py
git commit -m "feat: compose an email in the app and watch it get triaged"
```

**Part A is now demo-ready.** Ask before starting the server; the reviewer runs
`python -m uvicorn sdoc.web.app:app --reload --port 8000`, opens `/compose`, sends an
SI and a BL that differ in one field, and sees `MISMATCH` on that field.

---

## Part B — a real Gmail address (Tasks 5-7)

### Task 5: A real message becomes an email dict

**Files:**
- Create: `sdoc/mail/parse.py`
- Test: `tests/mail/test_parse.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `sdoc.mail.parse.parse_message(raw: bytes) -> dict` with keys `from`, `subject`, `body`, `attachments` (`list[tuple[str, bytes]]`). Note: **not** an `email_id` — Task 6 passes these to `store.save_email`, which allocates the id.

- [ ] **Step 1: Write the failing tests**

Create `tests/mail/test_parse.py`:

```python
from email.message import EmailMessage

from sdoc.mail.parse import parse_message


def build(subject="Check this BL", sender="Ops Team <ops@shipper.com>",
          text="Hi,\n\nPlease compare the attached.\n", html=None, files=()):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "sdoc@example.com"
    if text is not None:
        msg.set_content(text)
    if html is not None:
        if text is None:
            msg.set_content(html, subtype="html")
        else:
            msg.add_alternative(html, subtype="html")
    for name, data in files:
        msg.add_attachment(data, maintype="application", subtype="octet-stream",
                           filename=name)
    return msg.as_bytes()


def test_the_sender_is_the_bare_address():
    assert parse_message(build())["from"] == "ops@shipper.com"


def test_subject_and_body_come_through():
    parsed = parse_message(build())
    assert parsed["subject"] == "Check this BL"
    assert "Please compare the attached." in parsed["body"]


def test_attachments_come_back_as_name_and_bytes():
    parsed = parse_message(build(files=[("SI.txt", b"SHIPPER: ACME"),
                                        ("BL.txt", b"SHIPPER: ACME CORP")]))
    assert parsed["attachments"] == [("SI.txt", b"SHIPPER: ACME"),
                                     ("BL.txt", b"SHIPPER: ACME CORP")]


def test_plain_text_is_preferred_over_html():
    parsed = parse_message(build(text="the plain one", html="<p>the html one</p>"))
    assert "the plain one" in parsed["body"]
    assert "the html one" not in parsed["body"]


def test_an_html_only_message_is_reduced_to_readable_text():
    html = ("<html><head><style>p{color:red}</style></head><body>"
            "<p>Hi,</p><p>Please check the&nbsp;attached BL.</p>"
            "<script>alert(1)</script></body></html>")
    body = parse_message(build(text=None, html=html))["body"]
    assert "Hi," in body and "Please check the attached BL." in body
    assert "<p>" not in body and "alert" not in body and "color:red" not in body


def test_a_subject_encoded_for_non_ascii_is_decoded():
    raw = build(subject="Sj\u00f6fart BL kontroll")
    assert parse_message(raw)["subject"] == "Sj\u00f6fart BL kontroll"


def test_a_message_with_no_subject_or_body_does_not_crash():
    msg = EmailMessage()
    msg["From"] = "a@b.com"
    parsed = parse_message(msg.as_bytes())
    assert parsed["subject"] == "" and parsed["from"] == "a@b.com"
    assert parsed["attachments"] == []


def test_an_attachment_with_no_filename_is_skipped():
    msg = EmailMessage()
    msg["From"] = "a@b.com"
    msg["Subject"] = "s"
    msg.set_content("body")
    msg.add_attachment(b"\x89PNG", maintype="image", subtype="png")
    assert parse_message(msg.as_bytes())["attachments"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/mail/test_parse.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.mail.parse'`

- [ ] **Step 3: Write the parser**

Create `sdoc/mail/parse.py`:

```python
"""RFC 822 bytes -> the four things the pipeline needs. No network, no AI.

A real message is messier than a bundle email: the body may be HTML, the
subject may be MIME-encoded, and a signature image arrives as an attachment
with no filename. All of that is flattened here so everything downstream
sees exactly the shape load_emails() yields.
"""
import re
from email import message_from_bytes, policy
from email.utils import parseaddr
from html import unescape

_DROP = re.compile(r"(?is)<(script|style)\b.*?</\1>")
_BREAK = re.compile(r"(?i)<br\s*/?>|</(p|div|tr|li|h[1-6])>")
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


def parse_message(raw: bytes) -> dict:
    msg = message_from_bytes(raw, policy=policy.default)
    sender = parseaddr(str(msg.get("From", "")))[1] or str(msg.get("From", ""))
    return {
        "from": sender,
        "subject": str(msg.get("Subject", "") or ""),
        "body": _body(msg),
        "attachments": _attachments(msg),
    }


def _text(part) -> str:
    try:
        return part.get_content()
    except Exception:
        return (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")


def _body(msg) -> str:
    """The plain-text part if the sender wrote one, else the HTML flattened.

    Outlook and Gmail both send multipart/alternative; the plain part is the
    same words without the markup, so it is always the better input.
    """
    part = msg.get_body(preferencelist=("plain", "html")) if msg.is_multipart() else msg
    if part is None:
        return ""
    text = _text(part)
    if part.get_content_type() == "text/html":
        text = strip_html(text)
    return text.strip()


def strip_html(html: str) -> str:
    text = _DROP.sub("", html)
    text = _BREAK.sub("\n", text)
    text = _TAG.sub("", text)
    text = unescape(text).replace("\u00a0", " ")
    lines = [line.strip() for line in text.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def _attachments(msg) -> list[tuple[str, bytes]]:
    out = []
    if not msg.is_multipart():
        return out
    for part in msg.iter_attachments():
        name = part.get_filename()
        if not name:
            continue        # inline signature images and the like
        out.append((str(name), part.get_payload(decode=True) or b""))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/mail/test_parse.py -q`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add sdoc/mail/parse.py tests/mail/test_parse.py
git commit -m "feat: turn a real email message into the shape the pipeline reads"
```

---

### Task 6: Fetch from Gmail and ingest what arrives

**Files:**
- Create: `sdoc/mail/gmail.py`
- Create: `sdoc/run_watch.py`
- Test: `tests/mail/test_watch.py`

**Interfaces:**
- Consumes: `sdoc.mail.parse.parse_message`, `sdoc.mail.store.save_email`, `sdoc.ingest.ingest`
- Produces:
  - `sdoc.mail.gmail.Mailbox(user=None, password=None, host="imap.gmail.com")` with `.fetch_unseen(limit: int = 20) -> list[bytes]`
  - `sdoc.run_watch.poll_once(mailbox, root=None, out_dir=None) -> list[dict]` — returns the results ingested
  - `sdoc.run_watch.main()` — the CLI

`poll_once` takes the mailbox as an argument so the tests drive it with a stub and never open a socket.

- [ ] **Step 1: Write the failing tests**

Create `tests/mail/test_watch.py`:

```python
from email.message import EmailMessage

import pytest

from sdoc import inbox
from sdoc import run_watch


def message(subject="Check BL", files=()):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "ops@shipper.com"
    msg.set_content("Please compare the attached.")
    for name, data in files:
        msg.add_attachment(data, maintype="text", subtype="plain", filename=name)
    return msg.as_bytes()


class StubMailbox:
    """Hands out one batch per call, like a mailbox that has been drained."""

    def __init__(self, *batches):
        self.batches = list(batches)
        self.calls = 0

    def fetch_unseen(self, limit=20):
        self.calls += 1
        return self.batches.pop(0) if self.batches else []


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    out, mail = tmp_path / "out", tmp_path / "mail"
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)
    monkeypatch.setattr(run_watch, "ingest",
                        lambda email, out_dir=None: {"category": "BL_COMPARISON",
                                                     "status": "OK", "email_id": email["email_id"]})
    return out, mail


def test_nothing_waiting_means_nothing_happens(dirs):
    out, mail = dirs
    assert run_watch.poll_once(StubMailbox(), root=mail, out_dir=out) == []


def test_a_waiting_message_is_stored_and_ingested(dirs):
    out, mail = dirs
    box = StubMailbox([message(files=[("SI.txt", b"SHIPPER: ACME"),
                                      ("BL.txt", b"SHIPPER: ACME CORP")])])
    results = run_watch.poll_once(box, root=mail, out_dir=out)
    assert len(results) == 1
    saved = inbox.load_received()
    assert [e["subject"] for e in saved] == ["Check BL"]
    assert saved[0]["attachments"] == ["mail/attachments/mail_0001__SI.txt",
                                       "mail/attachments/mail_0001__BL.txt"]


def test_two_messages_in_one_batch_get_separate_ids(dirs):
    out, mail = dirs
    box = StubMailbox([message("first"), message("second")])
    run_watch.poll_once(box, root=mail, out_dir=out)
    assert [e["email_id"] for e in inbox.load_received()] == ["mail_0001", "mail_0002"]


def test_one_unparseable_message_does_not_stop_the_rest(dirs, monkeypatch):
    out, mail = dirs
    real = run_watch.parse_message

    def flaky(raw):
        if b"poison" in raw:
            raise ValueError("cannot parse")
        return real(raw)

    monkeypatch.setattr(run_watch, "parse_message", flaky)
    box = StubMailbox([b"poison", message("good")])
    results = run_watch.poll_once(box, root=mail, out_dir=out)
    assert len(results) == 1
    assert [e["subject"] for e in inbox.load_received()] == ["good"]


def test_a_mailbox_needs_a_user_and_a_password():
    from sdoc.mail.gmail import Mailbox
    with pytest.raises(RuntimeError) as e:
        Mailbox(user=None, password=None)
    assert "SDOC_MAIL_USER" in str(e.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/mail/test_watch.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.run_watch'`

- [ ] **Step 3: Write the mailbox**

Create `sdoc/mail/gmail.py`:

```python
"""Gmail over IMAP. The only file in the project that talks to a mail server.

Gmail needs an App Password, not the account password: turn on 2-Step
Verification, then create one at myaccount.google.com/apppasswords. Put both
values in .env (gitignored) and export them:

    SDOC_MAIL_USER=hackathon3in1@gmail.com
    SDOC_MAIL_PASSWORD=abcdefghijklmnop
"""
import imaplib
import logging
import os

log = logging.getLogger(__name__)

HOST = "imap.gmail.com"


class Mailbox:
    def __init__(self, user: str | None = None, password: str | None = None,
                 host: str = HOST):
        self.user = user or os.environ.get("SDOC_MAIL_USER")
        self.password = password or os.environ.get("SDOC_MAIL_PASSWORD")
        self.host = host
        if not self.user or not self.password:
            raise RuntimeError(
                "set SDOC_MAIL_USER and SDOC_MAIL_PASSWORD (a Gmail App Password, "
                "not the account password)")

    def fetch_unseen(self, limit: int = 20) -> list[bytes]:
        """Raw messages waiting in INBOX, marked read as they are taken.

        Marking read is what stops a message being processed - and billed -
        twice: the next poll no longer sees it.
        """
        raw: list[bytes] = []
        with imaplib.IMAP4_SSL(self.host) as M:
            M.login(self.user, self.password)
            M.select("INBOX")
            _, data = M.search(None, "UNSEEN")
            for num in (data[0].split() if data and data[0] else [])[:limit]:
                _, parts = M.fetch(num, "(RFC822)")
                for part in parts:
                    if isinstance(part, tuple) and part[1]:
                        raw.append(part[1])
                        break
                M.store(num, "+FLAGS", "\\Seen")
        return raw
```

- [ ] **Step 4: Write the watcher CLI**

Create `sdoc/run_watch.py`:

```python
"""Watch a mailbox. Anything that arrives is classified and compared.

    python -m sdoc.run_watch --once        one pass, then stop
    python -m sdoc.run_watch               poll every 20 seconds
"""
import argparse
import logging
import time
import traceback
from pathlib import Path

from sdoc.ingest import ingest
from sdoc.mail.parse import parse_message
from sdoc.mail.store import save_email

log = logging.getLogger(__name__)

INTERVAL = 20


def poll_once(mailbox, root: Path | None = None, out_dir: Path | None = None) -> list[dict]:
    """Fetch, store and process whatever is waiting. Returns the results.

    A message that cannot even be parsed is logged and skipped rather than
    stopping the pass - it has already been marked read, so it will not come
    back, and the rest of the batch still gets through.
    """
    results = []
    for raw in mailbox.fetch_unseen():
        try:
            parsed = parse_message(raw)
        except Exception:
            log.warning("could not parse a message, skipping it:\n%s", traceback.format_exc())
            continue
        email = save_email(parsed["from"], parsed["subject"], parsed["body"],
                           parsed["attachments"], root=root)
        result = ingest(email, out_dir=out_dir)
        log.info("%s  %-14s %-12s %s", email["email_id"], result.get("category", "?"),
                 result.get("status", "?"), email["subject"][:60])
        results.append(result)
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true", help="one pass, then stop")
    ap.add_argument("--interval", type=int, default=INTERVAL,
                    help=f"seconds between polls (default {INTERVAL})")
    args = ap.parse_args()

    from sdoc.mail.gmail import Mailbox      # imported here so --help needs no credentials
    mailbox = Mailbox()
    log.info("watching %s", mailbox.user)

    while True:
        try:
            poll_once(mailbox)
        except Exception:
            # A dropped connection or a flaky network must not end the watch.
            log.warning("poll failed, retrying next tick:\n%s", traceback.format_exc())
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/mail/test_watch.py -q`
Expected: PASS, 5 tests

Run: `python -m pytest -q`
Expected: PASS, 167 tests

- [ ] **Step 6: Commit**

```bash
git add sdoc/mail/gmail.py sdoc/run_watch.py tests/mail/test_watch.py
git commit -m "feat: watch a Gmail inbox and triage what arrives"
```

---

### Task 7: Show the address, and write it all down

**Files:**
- Modify: `sdoc/web/app.py`
- Modify: `sdoc/web/templates/compose.html`
- Modify: `README.md`
- Test: `tests/test_compose.py` (add one test)

**Interfaces:**
- Consumes: `SDOC_MAIL_USER`
- Produces: `_shell()` context gains `mail_address: str | None`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_compose.py`:

```python
def test_the_address_is_shown_when_one_is_configured(site, monkeypatch):
    client, _, _ = site
    monkeypatch.setenv("SDOC_MAIL_USER", "hackathon3in1@gmail.com")
    assert "hackathon3in1@gmail.com" in client.get("/compose").text


def test_no_address_configured_says_so_instead(site, monkeypatch):
    client, _, _ = site
    monkeypatch.delenv("SDOC_MAIL_USER", raising=False)
    html = client.get("/compose").text
    assert "hackathon3in1@gmail.com" not in html
    assert "python -m sdoc.run_watch" in html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_compose.py -q`
Expected: FAIL — the address is not in the page

- [ ] **Step 3: Put the address in the shell context**

In `sdoc/web/app.py`, add `import os` to the imports, then add one key to the dict `_shell()` returns, after `"n_received": ...`:

```python
        # Read per request, not at import: the watcher may be started later.
        "mail_address": os.environ.get("SDOC_MAIL_USER") or None,
```

- [ ] **Step 4: Show it on the compose page**

In `sdoc/web/templates/compose.html`, immediately after the `<p class="lede">...</p>` paragraph, add:

```html
  {% if mail_address %}
  <p class="lede">Or send a real email to
    <strong>{{ mail_address }}</strong> - the watcher picks it up within 20 seconds.</p>
  {% else %}
  <p class="lede">To accept real email as well, set <code>SDOC_MAIL_USER</code> and
    <code>SDOC_MAIL_PASSWORD</code> and run <code>python -m sdoc.run_watch</code>.</p>
  {% endif %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_compose.py -q`
Expected: PASS, 10 tests

- [ ] **Step 6: Update the README**

In the Status table, after the Human review loop row, add:

```markdown
| ✅ New mail, triaged on arrival | Compose one in the app, or send a real email to the watched Gmail address; it is classified and compared on arrival |
```

Add this section after **Run the comparison**:

````markdown
## Send it a new email

Two ways in, both ending in the same classify-and-compare the graded run uses.

**In the app** — open **New email** in the left rail (`/compose`), type a From,
Subject and Body, attach an SI and a BL, and send. The email appears in the
inbox with its category and verdict. Nothing is hard-coded: Claude reads what
you typed for the first time, which is the point of demoing it this way. Costs
about 2 cents per document check.

**From a real mailbox** — the watcher polls a Gmail inbox over IMAP:

```bash
export SDOC_MAIL_USER=hackathon3in1@gmail.com
export SDOC_MAIL_PASSWORD=abcdefghijklmnop     # a Gmail App Password
python -m sdoc.run_watch
```

Gmail needs an **App Password**, not the account password: turn on 2-Step
Verification, then create one at
[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
Keep both values in `.env`, which is gitignored.

```bash
python -m sdoc.run_watch --once            # one pass, then stop
python -m sdoc.run_watch --interval 60     # poll once a minute
```

Messages are marked read as they are taken, so nothing is processed - or
billed - twice.

Received mail is kept apart from the organizers' data on purpose:

| | |
|---|---|
| `mail/inbox/mail_NNNN.json` | the received emails |
| `mail/attachments/` | their files |
| `out/mail_results.json` | their verdicts |

`sdoc-hackathon-bundle/` is never written to, and `out/submission.json` keeps
exactly the 520 graded ids. `mail/` is gitignored - it is local state, like
`out/` and `.cache/`.
````

Update the Configuration table with three rows:

```markdown
| `SDOC_MAIL` | `./mail` | Where received mail is stored |
| `SDOC_MAIL_USER` | — | Gmail address the watcher polls |
| `SDOC_MAIL_PASSWORD` | — | Gmail App Password for that address |
```

Update the Layout block — add under `sdoc/`:

```
├── ingest.py          one received email -> classified, compared, saved
├── run_watch.py       CLI: watch a mailbox
├── mail/
│   ├── store.py       writing a received email to disk
│   ├── parse.py       RFC 822 bytes -> sender, subject, body, files
│   └── gmail.py       IMAP; the only file that talks to a mail server
```

Update the test count in **Run the tests** from `121 tests` to `169 tests`.

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS, 169 tests

- [ ] **Step 8: Commit**

```bash
git add sdoc/web/app.py sdoc/web/templates/compose.html README.md tests/test_compose.py
git commit -m "docs: how to send the system a new email"
```

---

## Self-Review

**Spec coverage.** The design spec's rules are untouched by construction: received mail goes through the same `classify()` and the same `pipeline.process()`, so the six gates, the four review reasons and "AI reads, code decides" all still hold. The one spec-adjacent risk — that `submission.json` must contain exactly the 520 graded ids — is handled by keeping `load_emails()` bundle-only (Task 1) and results in a separate file (Task 2), and is asserted by `test_load_all_emails_is_the_bundle_plus_what_arrived`.

**Interfaces line up.** `store.save_email` returns the dict `ingest()` takes; `parse_message` returns exactly the four arguments `save_email` takes, and deliberately no `email_id` (the store allocates it); `load_mail_results(out_dir)` takes the explicit directory `web.load_results()` passes so the existing `monkeypatch.setattr(web, "OUT_DIR", ...)` fixtures keep working.

**Two things worth watching during execution:**

1. **Three directory patches, not one.** `web.OUT_DIR`, `web.MAIL_DIR` and `inbox.MAIL_DIR` are separate module globals. A test that patches only some will read the developer's real `mail/` folder and pass or fail for the wrong reason. The fixtures in Tasks 3 and 4 patch all three.
2. **Test counts in this plan are arithmetic, not measured.** 121 + 11 + 7 + 7 + 8 + 8 + 5 + 2 = 169. If a step's count is off, trust the run and correct the README in Task 7 Step 6.

**Deliberately not built:** no delete/undo for a received email (remove the file from `mail/inbox/` and its id from `out/mail_results.json`), no pagination of `mail/`, no OAuth (an App Password is enough for one demo account), and no reprocessing of a message already marked read.
