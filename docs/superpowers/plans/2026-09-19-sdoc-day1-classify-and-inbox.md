# SDOC Day 1 — Classification + Email Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify all 520 emails with Claude, score the result, and browse them in a web inbox with real category badges.

**Architecture:** A disk-cached Claude client sits behind every API call so re-runs are free and instant. A classifier turns one email into one of five categories. A batch runner fans that across 520 emails into `out/categories.json`. A FastAPI app reads the bundle plus that file and renders a two-pane inbox. Nothing in this plan touches document extraction or field comparison — that is Day 2.

**Tech Stack:** Python 3.13, `anthropic` SDK, Pydantic v2, FastAPI + Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-19-sdoc-verification-design.md`

## Global Constraints

- Model for all calls: `claude-opus-5`. Never hardcode it at a call site — always read from `sdoc/config.py`.
- Every Claude call goes through the disk cache. No direct `client.messages.*` calls outside `sdoc/ai/client.py`.
- `sdoc-hackathon-docker/data_v2/ground_truth.json` is a scoreboard, never a lookup table. **No file under `sdoc/` may read it.** Only `tools/diff_errors.py` may, and that is a developer tool, not pipeline code.
- The submission must always contain all 520 email ids. A missing key is an invalid submission.
- Read input from `sdoc-hackathon-bundle/` only. The `data_v2/` folder is for scoring.
- Deviation from spec, deliberate: the spec lists `ai/config.py` for model names. This plan uses one `sdoc/config.py` holding both paths and model names — same "one place to change it" property, one fewer file.

---

## File Structure

| File | Responsibility |
|---|---|
| `requirements.txt` | Pinned dependencies |
| `.gitignore` | Excludes `.cache/`, `out/`, `__pycache__/` |
| `sdoc/config.py` | All paths and model names. The only place either is written. |
| `sdoc/ai/cache.py` | Content-addressed disk cache. Knows nothing about Claude. |
| `sdoc/ai/client.py` | Anthropic client + cache + typed error handling. The only file that imports `anthropic`. |
| `sdoc/ai/classify.py` | Email dict → `Classification`. Owns the prompt. |
| `sdoc/inbox.py` | Reads the bundle. Knows nothing about AI. |
| `sdoc/run_classify.py` | CLI: fan classification across the inbox → `out/categories.json` |
| `tools/make_submission.py` | `categories.json` → `out/submission.json` |
| `tools/diff_errors.py` | Developer tool: which emails did we get wrong? |
| `sdoc/web/app.py` | FastAPI routes |
| `sdoc/web/templates/*.html` | Jinja2 templates |
| `tests/` | Mirrors the `sdoc/` layout |

---

### Task 1: Project scaffold and disk cache

**Files:**
- Create: `requirements.txt`, `.gitignore`, `sdoc/__init__.py`, `sdoc/ai/__init__.py`, `sdoc/config.py`, `sdoc/ai/cache.py`
- Test: `tests/ai/test_cache.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `sdoc.config.BUNDLE_DIR: Path`, `OUT_DIR: Path`, `CACHE_DIR: Path`, `CLASSIFY_MODEL: str`, `EXTRACT_MODEL: str`, `VISION_MODEL: str`
  - `sdoc.ai.cache.cache_key(model: str, prompt: str, schema: type[BaseModel]) -> str`
  - `sdoc.ai.cache.cache_get(key: str) -> dict | None`
  - `sdoc.ai.cache.cache_put(key: str, value: dict) -> None`

- [ ] **Step 1: Initialise the repository**

```bash
cd "c:/Users/Admin/Documents/hackathon"
git init
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.pyc
.cache/
out/
.venv/
.pytest_cache/
```

- [ ] **Step 3: Create `requirements.txt`**

```
anthropic>=1.0
pydantic>=2.0
fastapi>=0.110
uvicorn[standard]>=0.27
jinja2>=3.1
pytest>=8.0
openpyxl>=3.1
python-docx>=1.1
pdfplumber>=0.11
```

- [ ] **Step 4: Install and create package directories**

```bash
python -m pip install -r requirements.txt
mkdir -p sdoc/ai sdoc/web/templates tools tests/ai
touch sdoc/__init__.py sdoc/ai/__init__.py sdoc/web/__init__.py tests/__init__.py tests/ai/__init__.py
```

- [ ] **Step 5: Create `sdoc/config.py`**

```python
"""All paths and model names. The only place either is written."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BUNDLE_DIR = Path(os.environ.get("SDOC_BUNDLE", ROOT / "sdoc-hackathon-bundle"))
OUT_DIR = Path(os.environ.get("SDOC_OUT", ROOT / "out"))
CACHE_DIR = Path(os.environ.get("SDOC_CACHE", ROOT / ".cache"))

# One model for everything on day 1. Change here to experiment; nothing
# else in the codebase names a model.
CLASSIFY_MODEL = "claude-opus-5"
EXTRACT_MODEL = "claude-opus-5"
VISION_MODEL = "claude-opus-5"
```

- [ ] **Step 6: Write the failing test**

Create `tests/ai/test_cache.py`:

```python
import pytest
from pydantic import BaseModel

from sdoc.ai import cache


class Schema(BaseModel):
    value: str


class OtherSchema(BaseModel):
    value: int


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def test_key_is_deterministic():
    a = cache.cache_key("claude-opus-5", "hello", Schema)
    b = cache.cache_key("claude-opus-5", "hello", Schema)
    assert a == b


def test_key_changes_with_prompt():
    a = cache.cache_key("claude-opus-5", "hello", Schema)
    b = cache.cache_key("claude-opus-5", "goodbye", Schema)
    assert a != b


def test_key_changes_with_model():
    a = cache.cache_key("claude-opus-5", "hello", Schema)
    b = cache.cache_key("claude-haiku-4-5", "hello", Schema)
    assert a != b


def test_key_changes_with_schema():
    """A changed output schema must invalidate — stale entries no longer parse."""
    a = cache.cache_key("claude-opus-5", "hello", Schema)
    b = cache.cache_key("claude-opus-5", "hello", OtherSchema)
    assert a != b


def test_miss_returns_none():
    assert cache.cache_get("nonexistent") is None


def test_roundtrip():
    cache.cache_put("abc123", {"value": "stored"})
    assert cache.cache_get("abc123") == {"value": "stored"}
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `python -m pytest tests/ai/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.ai.cache'`

- [ ] **Step 8: Implement `sdoc/ai/cache.py`**

```python
"""Content-addressed disk cache for LLM responses.

Keyed on model + prompt + output schema, so any change to any of the three
produces a different key and the stale entry is simply never read.
"""
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from sdoc.config import CACHE_DIR


def cache_key(model: str, prompt: str, schema: type[BaseModel]) -> str:
    # sort_keys matters: dict ordering must not change the key.
    schema_json = json.dumps(schema.model_json_schema(), sort_keys=True)
    payload = f"{model}\x00{prompt}\x00{schema_json}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _path(key: str) -> Path:
    return Path(CACHE_DIR) / f"{key}.json"


def cache_get(key: str) -> dict | None:
    path = _path(key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def cache_put(key: str, value: dict) -> None:
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    _path(key).write_text(json.dumps(value), encoding="utf-8")
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `python -m pytest tests/ai/test_cache.py -v`
Expected: PASS, 6 tests

Note: `tmp_cache` monkeypatches the module-level `CACHE_DIR`, which is why
`_path` reads `CACHE_DIR` at call time rather than binding it at import.

- [ ] **Step 10: Commit**

```bash
git add .gitignore requirements.txt sdoc/ tests/
git commit -m "feat: project scaffold and content-addressed disk cache"
```

---

### Task 2: Cached Claude client

**Files:**
- Create: `sdoc/ai/client.py`
- Test: `tests/ai/test_client.py`

**Interfaces:**
- Consumes: `sdoc.ai.cache.cache_key`, `cache_get`, `cache_put`; `sdoc.config.*`
- Produces: `sdoc.ai.client.call_structured(prompt: str, schema: type[T], model: str) -> T` where `T` is a `BaseModel` subclass

- [ ] **Step 1: Write the failing test**

Create `tests/ai/test_client.py`:

```python
import pytest
from pydantic import BaseModel

from sdoc.ai import cache, client


class Answer(BaseModel):
    label: str


class FakeParsed:
    def __init__(self, obj):
        self.parsed_output = obj


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def test_calls_api_on_miss_and_returns_parsed(monkeypatch):
    calls = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        return FakeParsed(Answer(label="SPAM"))

    monkeypatch.setattr(client, "_parse", fake_parse)

    result = client.call_structured("is this spam?", Answer, "claude-opus-5")

    assert result.label == "SPAM"
    assert len(calls) == 1
    assert calls[0]["model"] == "claude-opus-5"


def test_second_identical_call_hits_cache(monkeypatch):
    calls = []

    def fake_parse(**kwargs):
        calls.append(kwargs)
        return FakeParsed(Answer(label="SPAM"))

    monkeypatch.setattr(client, "_parse", fake_parse)

    client.call_structured("is this spam?", Answer, "claude-opus-5")
    result = client.call_structured("is this spam?", Answer, "claude-opus-5")

    assert result.label == "SPAM"
    assert len(calls) == 1, "second call must come from cache, not the API"


def test_different_prompt_calls_api_again(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client, "_parse", lambda **kw: (calls.append(kw), FakeParsed(Answer(label="OK")))[1]
    )

    client.call_structured("prompt A", Answer, "claude-opus-5")
    client.call_structured("prompt B", Answer, "claude-opus-5")

    assert len(calls) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/ai/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.ai.client'`

- [ ] **Step 3: Implement `sdoc/ai/client.py`**

```python
"""The only file that imports `anthropic`.

Every call is cached on disk, so re-running the pipeline after changing
downstream logic costs nothing and returns instantly.
"""
import logging
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from sdoc.ai.cache import cache_get, cache_key, cache_put

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# max_retries covers 429s, 5xx and connection errors with backoff. Raised
# above the default of 2 because this is a long unattended batch job.
_client = anthropic.Anthropic(max_retries=4)


def _parse(**kwargs):
    """Seam for tests to replace. Production path calls the real API."""
    return _client.messages.parse(**kwargs)


def call_structured(prompt: str, schema: type[T], model: str) -> T:
    key = cache_key(model, prompt, schema)

    hit = cache_get(key)
    if hit is not None:
        return schema(**hit)

    try:
        response = _parse(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
    except anthropic.NotFoundError:
        log.error("Unknown model %r — check sdoc/config.py", model)
        raise
    except anthropic.RateLimitError:
        log.error("Rate limited after retries; lower --workers or wait")
        raise
    except anthropic.APIStatusError as e:
        log.error("API returned %s: %s", e.status_code, e)
        raise
    except anthropic.APIConnectionError:
        log.error("Could not reach the API — check your connection")
        raise

    result = response.parsed_output
    cache_put(key, result.model_dump())
    return result
```

The four `except` clauses are ordered most-specific-first. A single broad
`except Exception` would lose the distinction between "wait and retry" and
"your config is wrong", and you would spend an hour finding out which.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/ai/test_client.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add sdoc/ai/client.py tests/ai/test_client.py
git commit -m "feat: cached Claude client with typed error handling"
```

---

### Task 3: Inbox loader

**Files:**
- Create: `sdoc/inbox.py`
- Test: `tests/test_inbox.py`

**Interfaces:**
- Consumes: `sdoc.config.BUNDLE_DIR`
- Produces:
  - `sdoc.inbox.load_emails() -> list[dict]` — sorted by `email_id`, each with keys `email_id`, `from`, `subject`, `body`, `attachments`
  - `sdoc.inbox.read_attachment_bytes(rel_path: str) -> bytes`
  - `sdoc.inbox.read_attachment_text(rel_path: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_inbox.py`:

```python
from sdoc import inbox


def test_loads_all_520_emails():
    emails = inbox.load_emails()
    assert len(emails) == 520


def test_emails_are_sorted_by_id():
    emails = inbox.load_emails()
    ids = [e["email_id"] for e in emails]
    assert ids == sorted(ids)
    assert ids[0] == "email_001"
    assert ids[-1] == "email_520"


def test_every_email_has_required_keys():
    for e in inbox.load_emails():
        assert set(e) >= {"email_id", "from", "subject", "body", "attachments"}


def test_reads_attachment_text():
    text = inbox.read_attachment_text("attachments/email_001_SI.txt")
    assert "SHIPPING INSTRUCTION" in text


def test_attachment_text_survives_bad_bytes():
    """Some attachments are deliberately corrupt. Reading must not raise."""
    text = inbox.read_attachment_text("attachments/email_001_BL.txt")
    assert isinstance(text, str)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_inbox.py -v`
Expected: FAIL — `ImportError: cannot import name 'inbox'`

- [ ] **Step 3: Implement `sdoc/inbox.py`**

```python
"""Reads the participant bundle. Knows nothing about AI or comparison."""
import json
from pathlib import Path

from sdoc.config import BUNDLE_DIR


def load_emails() -> list[dict]:
    inbox_dir = Path(BUNDLE_DIR) / "inbox"
    paths = sorted(inbox_dir.glob("email_*.json"))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def read_attachment_bytes(rel_path: str) -> bytes:
    return (Path(BUNDLE_DIR) / rel_path).read_bytes()


def read_attachment_text(rel_path: str) -> str:
    # errors="replace" because several attachments are deliberately corrupt.
    # Detecting that is Day 2's job; reading must never raise here.
    return read_attachment_bytes(rel_path).decode("utf-8", errors="replace")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_inbox.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add sdoc/inbox.py tests/test_inbox.py
git commit -m "feat: bundle inbox loader"
```

---

### Task 4: Email classifier

**Files:**
- Create: `sdoc/ai/classify.py`
- Test: `tests/ai/test_classify.py`

**Interfaces:**
- Consumes: `sdoc.ai.client.call_structured`, `sdoc.config.CLASSIFY_MODEL`
- Produces:
  - `sdoc.ai.classify.Classification` — Pydantic model with `category: str`, `reason: str`
  - `sdoc.ai.classify.CATEGORIES: list[str]`
  - `sdoc.ai.classify.build_prompt(email: dict) -> str`
  - `sdoc.ai.classify.classify(email: dict) -> Classification`

- [ ] **Step 1: Write the failing test**

Create `tests/ai/test_classify.py`:

```python
from sdoc.ai import classify


def test_prompt_contains_all_five_categories():
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "email_001"}
    prompt = classify.build_prompt(email)
    for category in ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]:
        assert category in prompt


def test_prompt_contains_the_email_content():
    email = {
        "from": "shipper@example.com",
        "subject": "TO CONFIRM DOCS",
        "body": "Attached are the SI and draft BL",
        "email_id": "email_001",
    }
    prompt = classify.build_prompt(email)
    assert "shipper@example.com" in prompt
    assert "TO CONFIRM DOCS" in prompt
    assert "Attached are the SI and draft BL" in prompt


def test_prompt_warns_that_subjects_mislead():
    """125 of 125 SI_REQUEST bodies contain the phrase 'draft BL'. The
    prompt must steer on intent, not vocabulary."""
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "email_001"}
    prompt = classify.build_prompt(email).lower()
    assert "subject" in prompt
    assert "intent" in prompt or "asking" in prompt


def test_classify_delegates_to_the_client(monkeypatch):
    captured = {}

    def fake_call(prompt, schema, model):
        captured["prompt"] = prompt
        captured["model"] = model
        return schema(category="SPAM", reason="prize scam")

    monkeypatch.setattr(classify, "call_structured", fake_call)

    email = {"from": "x@y.z", "subject": "You WON", "body": "claim now", "email_id": "email_003"}
    result = classify.classify(email)

    assert result.category == "SPAM"
    assert result.reason == "prize scam"
    assert captured["model"] == "claude-opus-5"
    assert "You WON" in captured["prompt"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/ai/test_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.ai.classify'`

- [ ] **Step 3: Implement `sdoc/ai/classify.py`**

```python
"""Email → one of five categories. Owns the classification prompt."""
from typing import Literal

from pydantic import BaseModel

from sdoc.ai.client import call_structured
from sdoc.config import CLASSIFY_MODEL

CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]


class Classification(BaseModel):
    category: Literal["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
    reason: str


PROMPT = """You are triaging a shipping operations inbox.

Classify this email into exactly one category.

BL_COMPARISON  Someone is asking for a draft Bill of Lading to be CHECKED or
               COMPARED against a Shipping Instruction, or asking for the draft
               BL to be sent so it can be checked.
SI_REQUEST     Someone is PROVIDING shipment details and asking that a Shipping
               Instruction or a draft BL be PREPARED from them.
INVOICE_QUERY  About invoices, billing, GR postings, local charges, D&D,
               freight amounts, or cancelling an invoice.
GENERAL        Operational updates, berthing reports, outstanding-BL lists,
               automated notifications, reminders, HR or company announcements.
SPAM           Marketing, phishing, prize scams, unsolicited offers.

Important: subject lines are unreliable and often misleading. Almost every
email in this inbox mentions "SI" or "draft BL" somewhere, so those phrases
carry no information. Decide on INTENT — what is the sender asking the
recipient to DO next?

  "make me a BL from these details"   -> SI_REQUEST
  "check this BL against the SI"      -> BL_COMPARISON
  "send me the draft BL for checking" -> BL_COMPARISON

From: {sender}
Subject: {subject}
Body:
{body}

Give the category and a short reason (under 15 words)."""


def build_prompt(email: dict) -> str:
    return PROMPT.format(
        sender=email["from"],
        subject=email["subject"],
        body=email["body"],
    )


def classify(email: dict) -> Classification:
    return call_structured(build_prompt(email), Classification, CLASSIFY_MODEL)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/ai/test_classify.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Smoke-test against the real API on one email**

```bash
python -c "from sdoc.inbox import load_emails; from sdoc.ai.classify import classify; e=load_emails()[0]; r=classify(e); print(e['email_id'], r.category, '|', r.reason)"
```

Expected: `email_001 BL_COMPARISON | ...`. This is the first real API call —
if it fails, check `ANTHROPIC_API_KEY` is set:
PowerShell `$env:ANTHROPIC_API_KEY="sk-ant-..."` / Git Bash `export ANTHROPIC_API_KEY=sk-ant-...`

Run it a second time — it must return instantly and cost nothing, proving the cache works.

- [ ] **Step 6: Commit**

```bash
git add sdoc/ai/classify.py tests/ai/test_classify.py
git commit -m "feat: email classifier with intent-based prompt"
```

---

### Task 5: Batch classification runner

**Files:**
- Create: `sdoc/run_classify.py`
- Test: `tests/test_run_classify.py`

**Interfaces:**
- Consumes: `sdoc.inbox.load_emails`, `sdoc.ai.classify.classify`, `sdoc.config.OUT_DIR`
- Produces:
  - `sdoc.run_classify.classify_all(emails: list[dict], workers: int = 8) -> dict[str, dict]` — maps `email_id` to `{"category": str, "reason": str, "error": str | None}`
  - CLI: `python -m sdoc.run_classify [--limit N] [--workers N]` writing `out/categories.json`

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_classify.py`:

```python
from sdoc import run_classify
from sdoc.ai.classify import Classification


def test_classifies_every_email(monkeypatch):
    monkeypatch.setattr(
        run_classify, "classify",
        lambda e: Classification(category="SPAM", reason="test"),
    )
    emails = [{"email_id": f"email_{i:03d}"} for i in range(1, 6)]

    result = run_classify.classify_all(emails, workers=2)

    assert len(result) == 5
    assert result["email_001"]["category"] == "SPAM"
    assert result["email_001"]["error"] is None


def test_one_failure_does_not_kill_the_batch(monkeypatch):
    """The submission must contain all 520 keys. A crash on one email
    must not drop the other 519."""
    def flaky(email):
        if email["email_id"] == "email_003":
            raise RuntimeError("boom")
        return Classification(category="GENERAL", reason="ok")

    monkeypatch.setattr(run_classify, "classify", flaky)
    emails = [{"email_id": f"email_{i:03d}"} for i in range(1, 6)]

    result = run_classify.classify_all(emails, workers=2)

    assert len(result) == 5, "every email must appear, even the failed one"
    assert result["email_003"]["error"] is not None
    assert "boom" in result["email_003"]["error"]
    assert result["email_003"]["category"] == "GENERAL", "failed emails fall back"
    assert result["email_004"]["category"] == "GENERAL"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_run_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.run_classify'`

- [ ] **Step 3: Implement `sdoc/run_classify.py`**

```python
"""Fan classification across the whole inbox into out/categories.json."""
import argparse
import json
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sdoc.ai.classify import classify
from sdoc.config import OUT_DIR
from sdoc.inbox import load_emails

log = logging.getLogger(__name__)

# When classification fails we still need a category. GENERAL is the
# lowest-harm guess: it is the scorer's own default for a missing entry.
FALLBACK_CATEGORY = "GENERAL"


def _one(email: dict) -> tuple[str, dict]:
    eid = email["email_id"]
    try:
        result = classify(email)
        return eid, {"category": result.category, "reason": result.reason, "error": None}
    except Exception:
        log.warning("classification failed for %s", eid)
        return eid, {
            "category": FALLBACK_CATEGORY,
            "reason": "classification failed",
            "error": traceback.format_exc(),
        }


def classify_all(emails: list[dict], workers: int = 8) -> dict[str, dict]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(_one, emails))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only process the first N emails")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    emails = load_emails()
    if args.limit:
        emails = emails[: args.limit]

    log.info("classifying %d emails with %d workers", len(emails), args.workers)
    results = classify_all(emails, workers=args.workers)

    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    out = Path(OUT_DIR) / "categories.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    failures = sum(1 for r in results.values() if r["error"])
    counts: dict[str, int] = {}
    for r in results.values():
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    log.info("wrote %s", out)
    log.info("category mix: %s", counts)
    if failures:
        log.warning("%d emails failed and fell back to %s", failures, FALLBACK_CATEGORY)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_run_classify.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Run on 20 emails against the real API**

```bash
python -m sdoc.run_classify --limit 20
```

Expected: finishes in well under a minute, logs a category mix, writes `out/categories.json` with 20 entries.

- [ ] **Step 6: Run the full 520**

```bash
python -m sdoc.run_classify
```

Expected: ~3–6 minutes, ~$2. The logged mix should be in the neighbourhood of
`BL_COMPARISON 220, SI_REQUEST 125, INVOICE_QUERY 75, GENERAL 60, SPAM 40`.
A wildly different mix means the prompt needs work — note it, do not tune yet.

Re-run the same command. It must finish in seconds from cache.

- [ ] **Step 7: Commit**

```bash
git add sdoc/run_classify.py tests/test_run_classify.py
git commit -m "feat: batch classification runner with per-email failure isolation"
```

---

### Task 6: Submission builder and error diff

**Files:**
- Create: `tools/make_submission.py`, `tools/diff_errors.py`
- Test: `tests/test_make_submission.py`

**Interfaces:**
- Consumes: `out/categories.json`
- Produces:
  - `tools.make_submission.build(categories: dict, all_ids: list[str]) -> dict`
  - CLI: `python tools/make_submission.py` writing `out/submission.json`
  - CLI: `python tools/diff_errors.py` printing mismatched email ids

- [ ] **Step 1: Write the failing test**

Create `tests/test_make_submission.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import make_submission


def test_every_id_is_present_even_when_unclassified():
    """A missing key is an invalid submission. Ids absent from
    categories.json must still appear, defaulted."""
    categories = {"email_001": {"category": "SPAM", "reason": "x", "error": None}}
    all_ids = ["email_001", "email_002", "email_003"]

    result = make_submission.build(categories, all_ids)

    assert set(result) == {"email_001", "email_002", "email_003"}
    assert result["email_001"]["category"] == "SPAM"
    assert result["email_002"]["category"] == "GENERAL"


def test_shape_matches_the_scorer_contract():
    categories = {"email_001": {"category": "BL_COMPARISON", "reason": "x", "error": None}}
    result = make_submission.build(categories, ["email_001"])

    assert result["email_001"] == {
        "category": "BL_COMPARISON",
        "status": "OK",
        "review_reason": None,
        "has_defect": False,
        "defect_fields": [],
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_make_submission.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools'`

- [ ] **Step 3: Create `tools/__init__.py` and implement `tools/make_submission.py`**

```bash
touch tools/__init__.py
```

```python
"""categories.json -> submission.json.

Day 1 only fills in the category. status/defect fields are defaulted, so
stage 3 and end-to-end will score zero. That is expected — Day 2 fills them.
"""
import json
from pathlib import Path

from sdoc.config import OUT_DIR
from sdoc.inbox import load_emails


def build(categories: dict, all_ids: list[str]) -> dict:
    submission = {}
    for eid in all_ids:
        entry = categories.get(eid, {})
        submission[eid] = {
            "category": entry.get("category", "GENERAL"),
            "status": "OK",
            "review_reason": None,
            "has_defect": False,
            "defect_fields": [],
        }
    return submission


def main() -> None:
    out = Path(OUT_DIR)
    categories = json.loads((out / "categories.json").read_text(encoding="utf-8"))
    all_ids = [e["email_id"] for e in load_emails()]

    submission = build(categories, all_ids)
    path = out / "submission.json"
    path.write_text(json.dumps(submission, indent=2), encoding="utf-8")
    print(f"wrote {path} with {len(submission)} entries")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_make_submission.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Build the submission and score it**

```bash
python tools/make_submission.py
cd sdoc-hackathon-docker/server
PYTHONIOENCODING=utf-8 python score_cli.py ../../out/submission.json
cd ../..
```

(PowerShell: `$env:PYTHONIOENCODING="utf-8"` first, then run without the prefix.
The `score_cli.py` script prints block characters and crashes on the default
Windows console encoding.)

Expected: STAGE 1 macro-F1 above 0.85. STAGE 3 and END-TO-END will be 0.000 —
correct for Day 1, since nothing is comparing documents yet. Final score should
land near `0.30 x macro_f1`, so roughly 0.26–0.29.

**Write the number down.** Every later change is measured against it.

- [ ] **Step 6: Implement `tools/diff_errors.py`**

```python
"""Developer tool: which emails did we classify wrong?

Reads ground_truth.json. NOTHING under sdoc/ may do this — it is a
scoreboard, not a lookup table. Use it to find the emails to go read,
then fix the underlying prompt or rule, never the individual case.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GT = ROOT / "sdoc-hackathon-docker" / "data_v2" / "ground_truth.json"
SUB = ROOT / "out" / "submission.json"


def main() -> None:
    gt = json.loads(GT.read_text(encoding="utf-8"))
    sub = json.loads(SUB.read_text(encoding="utf-8"))

    wrong_category = []
    wrong_fields = []

    for eid, truth in gt.items():
        mine = sub.get(eid, {})
        if mine.get("category") != truth["category"]:
            wrong_category.append((eid, mine.get("category"), truth["category"]))
        elif set(mine.get("defect_fields", [])) != set(truth["defect_fields"]):
            wrong_fields.append((eid, mine.get("defect_fields"), truth["defect_fields"]))

    print(f"CATEGORY WRONG: {len(wrong_category)}")
    for eid, got, want in wrong_category[:40]:
        print(f"  {eid}  said {got:<14} actual {want}")
    if len(wrong_category) > 40:
        print(f"  ... and {len(wrong_category) - 40} more")

    print(f"\nDEFECT FIELDS WRONG: {len(wrong_fields)}")
    for eid, got, want in wrong_fields[:40]:
        print(f"  {eid}  said {got} actual {want}")
    if len(wrong_fields) > 40:
        print(f"  ... and {len(wrong_fields) - 40} more")

    if not wrong_category and not wrong_fields:
        print("\nNothing wrong. Suspicious — check the submission is not empty.")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Run the diff and read three wrong emails**

```bash
python tools/diff_errors.py
```

Open three of the listed emails in `sdoc-hackathon-bundle/inbox/` and work out
*why* the classifier was wrong. Fix the prompt in `sdoc/ai/classify.py` if a
pattern emerges. Do not add per-email special cases.

Note: changing the prompt changes the cache key, so the next run re-calls the
API for all 520 (~$2). Batch your prompt edits rather than re-running after each one.

- [ ] **Step 8: Commit**

```bash
git add tools/ tests/test_make_submission.py
git commit -m "feat: submission builder and error-diff developer tool"
```

---

### Task 7: Web inbox list

**Files:**
- Create: `sdoc/web/app.py`, `sdoc/web/templates/base.html`, `sdoc/web/templates/inbox.html`

**Interfaces:**
- Consumes: `sdoc.inbox.load_emails`, `out/categories.json`
- Produces:
  - `sdoc.web.app.app` — the FastAPI instance
  - `sdoc.web.app.load_categories() -> dict[str, dict]` — returns `{}` when the file is absent
  - Route `GET /` — inbox list, optional `?category=` filter

- [ ] **Step 1: Create `sdoc/web/templates/base.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}SDOC Inbox{% endblock %}</title>
  <style>
    :root {
      --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280;
      --line: #e5e7eb; --hover: #f9fafb; --accent: #2563eb;
      --bl: #2563eb; --si: #7c3aed; --inv: #d97706;
      --gen: #6b7280; --spam: #dc2626;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af;
        --line: #262b33; --hover: #171a20; --accent: #60a5fa;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; background: var(--bg); color: var(--fg);
      font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    }
    header {
      padding: 12px 20px; border-bottom: 1px solid var(--line);
      display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap;
    }
    header h1 { font-size: 15px; margin: 0; font-weight: 600; }
    header .count { color: var(--muted); font-size: 13px; }
    nav { display: flex; gap: 6px; flex-wrap: wrap; margin-left: auto; }
    nav a {
      color: var(--muted); text-decoration: none; padding: 3px 9px;
      border: 1px solid var(--line); border-radius: 99px; font-size: 12px;
    }
    nav a.on { color: var(--bg); background: var(--fg); border-color: var(--fg); }
    main { padding: 0; }
    .badge {
      display: inline-block; padding: 1px 7px; border-radius: 4px;
      font-size: 11px; font-weight: 600; letter-spacing: .02em;
      color: #fff; white-space: nowrap;
    }
    .badge.BL_COMPARISON { background: var(--bl); }
    .badge.SI_REQUEST    { background: var(--si); }
    .badge.INVOICE_QUERY { background: var(--inv); }
    .badge.GENERAL       { background: var(--gen); }
    .badge.SPAM          { background: var(--spam); }
    .badge.none          { background: transparent; color: var(--muted);
                           border: 1px dashed var(--line); }
  </style>
</head>
<body>
  <header>
    <h1>SDOC Inbox</h1>
    <span class="count">{% block count %}{% endblock %}</span>
    <nav>
      <a href="/" class="{% if not active %}on{% endif %}">All</a>
      {% for c in categories_list %}
        <a href="/?category={{ c }}" class="{% if active == c %}on{% endif %}">{{ c }}</a>
      {% endfor %}
    </nav>
  </header>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```

- [ ] **Step 2: Create `sdoc/web/templates/inbox.html`**

```html
{% extends "base.html" %}
{% block count %}{{ emails|length }} of {{ total }} emails{% endblock %}
{% block content %}
<style>
  table { width: 100%; border-collapse: collapse; }
  tr { border-bottom: 1px solid var(--line); }
  tr:hover { background: var(--hover); }
  td { padding: 9px 12px; vertical-align: top; }
  td.id { color: var(--muted); font-family: ui-monospace, monospace;
          font-size: 12px; white-space: nowrap; width: 1%; }
  td.cat { width: 1%; }
  td.subj a { color: var(--fg); text-decoration: none; }
  td.subj a:hover { color: var(--accent); text-decoration: underline; }
  td.from { color: var(--muted); font-size: 12px; white-space: nowrap; }
  td.att { color: var(--muted); font-size: 12px; white-space: nowrap; width: 1%; }
  .empty { padding: 40px 20px; color: var(--muted); text-align: center; }
</style>
{% if not emails %}
  <p class="empty">No emails in this category.</p>
{% else %}
<table>
  {% for e in emails %}
  <tr>
    <td class="id">{{ e.email_id }}</td>
    <td class="cat">
      {% set c = cats.get(e.email_id, {}).get('category') %}
      {% if c %}<span class="badge {{ c }}">{{ c }}</span>
      {% else %}<span class="badge none">unclassified</span>{% endif %}
    </td>
    <td class="subj"><a href="/email/{{ e.email_id }}">{{ e.subject }}</a></td>
    <td class="from">{{ e['from'] }}</td>
    <td class="att">{% if e.attachments %}&#128206; {{ e.attachments|length }}{% endif %}</td>
  </tr>
  {% endfor %}
</table>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Implement `sdoc/web/app.py`**

```python
"""FastAPI app. Reads the bundle plus whatever the pipeline has produced.

Renders whatever exists: with no categories.json it still shows all 520
emails, badges marked "unclassified".
"""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from sdoc.ai.classify import CATEGORIES
from sdoc.config import OUT_DIR
from sdoc.inbox import load_emails

app = FastAPI(title="SDOC Inbox")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def load_categories() -> dict:
    path = Path(OUT_DIR) / "categories.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
def inbox(request: Request, category: str | None = None):
    emails = load_emails()
    cats = load_categories()

    if category:
        emails = [e for e in emails if cats.get(e["email_id"], {}).get("category") == category]

    return templates.TemplateResponse(
        request=request,
        name="inbox.html",
        context={
            "emails": emails,
            "total": len(load_emails()),
            "cats": cats,
            "categories_list": CATEGORIES,
            "active": category,
        },
    )
```

- [ ] **Step 4: Run the server and verify in a browser**

```bash
python -m uvicorn sdoc.web.app:app --reload --port 8000
```

Open `http://localhost:8000`. Verify:
- 520 rows render
- each has a coloured category badge
- the filter pills across the top narrow the list
- `?category=SPAM` shows roughly 40 rows

- [ ] **Step 5: Commit**

```bash
git add sdoc/web/
git commit -m "feat: web inbox list with category badges and filtering"
```

---

### Task 8: Email reader with attachments

**Files:**
- Create: `sdoc/web/templates/email.html`
- Modify: `sdoc/web/app.py` — add two routes

**Interfaces:**
- Consumes: `sdoc.inbox.load_emails`, `read_attachment_text`, `read_attachment_bytes`
- Produces:
  - Route `GET /email/{email_id}` — full email with classification reason and attachment list
  - Route `GET /attachment/{path:path}` — plain-text view of one attachment

- [ ] **Step 1: Create `sdoc/web/templates/email.html`**

```html
{% extends "base.html" %}
{% block title %}{{ email.email_id }} — SDOC{% endblock %}
{% block content %}
<style>
  .wrap { max-width: 860px; padding: 20px; }
  .back { color: var(--muted); text-decoration: none; font-size: 13px; }
  .back:hover { color: var(--accent); }
  h2 { font-size: 17px; margin: 14px 0 6px; font-weight: 600; }
  .meta { color: var(--muted); font-size: 13px; margin-bottom: 4px; }
  .why { color: var(--muted); font-size: 12px; font-style: italic; margin-top: 6px; }
  pre.body {
    white-space: pre-wrap; word-wrap: break-word; background: var(--hover);
    border: 1px solid var(--line); border-radius: 6px; padding: 14px;
    margin: 16px 0; font: 13px/1.6 ui-monospace, monospace; overflow-x: auto;
  }
  .atts { border-top: 1px solid var(--line); padding-top: 14px; }
  .atts h3 { font-size: 13px; color: var(--muted); margin: 0 0 8px; font-weight: 600; }
  .atts a { display: inline-block; margin-right: 12px; color: var(--accent);
            text-decoration: none; font-size: 13px; }
  .atts a:hover { text-decoration: underline; }
  .none { color: var(--muted); font-size: 13px; }
  .slot { border: 1px dashed var(--line); border-radius: 6px; padding: 12px;
          color: var(--muted); font-size: 12px; margin: 16px 0; }
</style>
<div class="wrap">
  <a class="back" href="/">&larr; Inbox</a>
  <h2>{{ email.subject }}</h2>
  <div class="meta">{{ email.email_id }} &middot; from {{ email['from'] }}</div>
  {% if cat %}
    <span class="badge {{ cat.category }}">{{ cat.category }}</span>
    {% if cat.reason %}<div class="why">{{ cat.reason }}</div>{% endif %}
  {% else %}
    <span class="badge none">unclassified</span>
  {% endif %}

  <pre class="body">{{ email.body }}</pre>

  <!-- Day 2 fills this: SI/BL field comparison table -->
  <div class="slot">Comparison report appears here once the pipeline runs.</div>

  <div class="atts">
    <h3>Attachments</h3>
    {% if email.attachments %}
      {% for a in email.attachments %}
        <a href="/attachment/{{ a }}">&#128206; {{ a.split('/')[-1] }}</a>
      {% endfor %}
    {% else %}
      <span class="none">None</span>
    {% endif %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Add the two routes to `sdoc/web/app.py`**

Append to the end of the file:

```python
@app.get("/email/{email_id}", response_class=HTMLResponse)
def email_detail(request: Request, email_id: str):
    emails = {e["email_id"]: e for e in load_emails()}
    if email_id not in emails:
        raise HTTPException(status_code=404, detail=f"no such email: {email_id}")

    return templates.TemplateResponse(
        request=request,
        name="email.html",
        context={
            "email": emails[email_id],
            "cat": load_categories().get(email_id),
            "categories_list": CATEGORIES,
            "active": None,
        },
    )


@app.get("/attachment/{path:path}", response_class=HTMLResponse)
def attachment(path: str):
    # Path traversal guard: only serve files inside the bundle's attachments/.
    if not path.startswith("attachments/") or ".." in path:
        raise HTTPException(status_code=400, detail="bad attachment path")

    from html import escape

    from sdoc.inbox import read_attachment_text

    try:
        text = read_attachment_text(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"missing file: {path}")

    if not text.strip():
        text = "(this file is empty)"

    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<body style='margin:0;background:#0f1115;color:#e5e7eb'>"
        f"<pre style='white-space:pre-wrap;padding:20px;"
        f"font:13px/1.6 ui-monospace,monospace'>{escape(text)}</pre></body>"
    )
```

Binary attachments (`.pdf`, `.docx`, `.xlsx`) will render as decoded mojibake
here. That is expected and acceptable on Day 1 — Task for Day 2 replaces this
view with the extracted text once `extract/` exists.

- [ ] **Step 3: Verify in the browser**

With the server still running (`--reload` picks up the changes):
- click any subject from the inbox → the email renders with its body and badge
- click a `.txt` attachment → the SI or BL content displays
- visit `http://localhost:8000/email/does_not_exist` → a 404, not a stack trace
- visit `http://localhost:8000/attachment/../../etc/passwd` → a 400

- [ ] **Step 4: Commit**

```bash
git add sdoc/web/
git commit -m "feat: email reader with attachment viewer"
```

---

## Day 1 Done — Definition of Success

- [ ] `python -m pytest -v` — all tests pass
- [ ] `out/categories.json` holds 520 entries
- [ ] `score_cli.py` reports STAGE 1 macro-F1 above 0.85
- [ ] The inbox renders 520 emails with working category filters
- [ ] Clicking an email shows its body and attachments
- [ ] Re-running `python -m sdoc.run_classify` finishes in seconds from cache

**Record your STAGE 1 macro-F1.** Day 2 adds document comparison, which is
worth the other 70% — but classification is now banked and must not regress.

## What Day 2 Covers (not this plan)

`extract/` for txt/pdf/docx/xlsx, `core/normalize.py` and `core/compare.py`,
the six gates, vision for scanned PDFs, and the full `results.json` that
replaces `categories.json`. Then the UI slots fill in on Day 3.
