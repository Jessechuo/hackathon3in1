# SDOC Day 2 — Extraction, Checks and Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every `BL_COMPARISON` email, read the SI and BL attachments, run the escalation checks in the spec's order, compare the seven fields, and write `out/results.json` (for the UI) plus a complete `out/submission.json` (for the scorer) — then show the SI-vs-BL comparison in the web UI.

**Architecture:** Plain-Python readers turn txt/xlsx/docx/pdf into text. One Claude call per email reads both documents together and returns each document's type plus its seven raw field values. Deterministic Python then decides everything else — which check fails first, whether each field matches, and what goes in the submission. The web app renders `results.json`; it never calls the API.

**Tech Stack:** Python 3.13, `anthropic` SDK (`messages.parse` + Pydantic), pdfplumber, openpyxl, python-docx, FastAPI + Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-19-sdoc-verification-design.md` (sections 4–7). Day 1 plan: `docs/superpowers/plans/2026-09-19-sdoc-day1-classify-and-inbox.md`.

## Global Constraints

- **Ask before running anything.** At the start of execution, ask once for approval to run the free local test suite (`python -m pytest`, no network) during TDD. Every paid API run, server start, and git commit/push needs its own yes, stated with the expected cost.
- **Commits:** author `CHUO JESSE <chuojesse@gmail.com>` (repo-local git config is already set). No `Co-Authored-By` line and no Claude attribution anywhere in commit messages.
- **Models come only from `sdoc/config.py`:** `CLASSIFY_MODEL = "claude-haiku-4-5"`, `EXTRACT_MODEL = "claude-opus-5"`. No model id is written anywhere else.
- **No file under `sdoc/` may read `ground_truth.json`.** Checks against the answer key live in `tools/` only.
- **Never edit anything in `sdoc-hackathon-bundle/`.**
- **`submission.json` always has all 520 ids**, each with exactly: `category`, `status`, `review_reason`, `has_defect`, `defect_fields`.
- **`review_reason` is one of exactly four values:** `missing_attachment`, `unreadable`, `wrong_doc_type`, `missing_value`.
- **Check order is fixed:** category → attachments → readable → extract → document type → blank values → compare. The most specific failure is reported first.
- **The extraction prompt must never let one document's value fill in or correct the other's.** Differences between SI and BL are the point.
- **Windows:** in the VS Code terminal, load the key first with `$env:ANTHROPIC_API_KEY = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY","User")`. The organizer scorer needs `PYTHONIOENCODING=utf-8`.
- **Budget:** $20 total, about $1 spent before this plan. Paid steps in this plan: Task 2 re-run (~$0.70), Task 9 sample (~$0.10), Task 9 full run (~$2–4, estimated — measured in Task 9 before committing to it).

## Deliberate deviations from the spec (deadline-driven)

| Spec says | This plan does | Why |
|---|---|---|
| `extract/` package, one file per format | One module, `sdoc/extract.py` | Four readers of ~8 lines each; one file is easier to hold |
| Extract SI and BL separately | **One joint Claude call per email** | Both documents interpreted consistently (multi-line party names, labels); half the calls. The prompt forbids reconciling values |
| Vision on scanned PDFs, then review | **Deferred.** Scans escalate as `unreadable` directly | Those 3 emails escalate either way, so vision changes neither the score nor the reliability axis. Revisit only if time remains |
| Ask Claude about near-miss names | Deterministic canonical match + prefix rule for continued party names | Real defects in this data are wholesale substitutions; deterministic is cheaper and repeatable |
| Separate `ERROR` status | `failed: true` flag in `results.json`; submission maps it to `NEEDS_REVIEW` / `unreadable` | Same behaviour, less plumbing |

---

## File Structure

| File | Responsibility |
|---|---|
| `sdoc/config.py` | + `PRICES` for the cost line printed after each run |
| `sdoc/ai/client.py` | + per-run usage counting, `usage_summary()`, `max_tokens` parameter, guard against empty structured output |
| `sdoc/ai/classify.py` | + `says_documents_are_attached` field (drives the 0-attachment check) |
| `sdoc/run_classify.py` | writes the new field; prints the cost line |
| `sdoc/core/fields.py` | the seven field names and the `ShipmentFields` model |
| `sdoc/core/normalize.py` | blank detection and per-field canonical forms |
| `sdoc/core/compare.py` | SI vs BL → rows, missing fields, defect fields |
| `sdoc/extract.py` | attachment path → `DocText` (text, or why it can't be read) |
| `sdoc/ai/extract_pair.py` | the joint extraction prompt and call |
| `sdoc/pipeline.py` | the checks in order → one result dict per email; `to_submission()` |
| `sdoc/run_pipeline.py` | CLI → `out/results.json` + `out/submission.json` |
| `sdoc/web/app.py`, `templates/*` | comparison panel, status filter, readable binary attachments |
| `tools/check_attachment_flag.py` | dev check of the new classifier flag against the answer key |
| `tools/diff_errors.py` | + escalation differences |

---

### Task 1: See what every run costs

**Files:**
- Modify: `sdoc/config.py`, `sdoc/ai/client.py`, `sdoc/run_classify.py`
- Test: `tests/ai/test_client.py`

**Interfaces:**
- Consumes: `sdoc.ai.cache.cache_key/cache_get/cache_put`
- Produces:
  - `sdoc.config.PRICES: dict[str, tuple[float, float]]` — USD per 1M tokens (input, output)
  - `sdoc.ai.client.call_structured(prompt: str, schema: type[T], model: str, max_tokens: int = 2048) -> T`
  - `sdoc.ai.client.usage_summary() -> str`
  - `sdoc.ai.client.reset_usage() -> None`

- [ ] **Step 1: Write the failing tests** — append to `tests/ai/test_client.py`:

```python
class FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def test_usage_is_counted_only_for_real_api_calls(monkeypatch):
    client.reset_usage()

    def fake_parse(**kwargs):
        r = FakeParsed(Answer(label="SPAM"))
        r.usage = FakeUsage(1000, 50)
        return r

    monkeypatch.setattr(client, "_parse", fake_parse)
    client.call_structured("p", Answer, "claude-haiku-4-5")
    client.call_structured("p", Answer, "claude-haiku-4-5")   # cache hit: not counted

    s = client.usage_summary()
    assert "1 calls" in s
    assert "1,000 in / 50 out" in s


def test_usage_summary_when_nothing_was_called():
    client.reset_usage()
    assert "0 calls" in client.usage_summary()


def test_empty_structured_output_raises_and_is_not_cached(monkeypatch):
    class Empty:
        parsed_output = None
        stop_reason = "refusal"
        usage = None

    monkeypatch.setattr(client, "_parse", lambda **kw: Empty())
    with pytest.raises(RuntimeError, match="refusal"):
        client.call_structured("q", Answer, "claude-opus-5")
    assert cache.cache_get(cache.cache_key("claude-opus-5", "q", Answer)) is None


def test_max_tokens_is_passed_through(recorder):
    client.call_structured("x", Answer, "claude-opus-5", max_tokens=8000)
    assert recorder[0]["max_tokens"] == 8000
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/ai/test_client.py -v`
Expected: FAIL — `AttributeError: module 'sdoc.ai.client' has no attribute 'reset_usage'`

- [ ] **Step 3: Add prices to `sdoc/config.py`** — append:

```python
# USD per 1M tokens (input, output). Used only to print a cost line after
# each run so spend is visible; Anthropic bills from its own records.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
```

- [ ] **Step 4: Replace `sdoc/ai/client.py`** with:

```python
"""The only file that imports `anthropic`.

Every call is cached on disk, so re-running the pipeline after changing
downstream logic costs nothing and returns instantly. Every call that does
reach the API is counted, so each run can print what it cost.
"""
import logging
import threading
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from sdoc.ai.cache import cache_get, cache_key, cache_put
from sdoc.config import PRICES

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# max_retries covers 429s, 5xx and connection errors with backoff. Raised
# above the default of 2 because this is a long unattended batch job.
_client = anthropic.Anthropic(max_retries=4)

_usage_lock = threading.Lock()
_usage: dict[str, list[int]] = {}      # model -> [calls, input_tokens, output_tokens]


def _parse(**kwargs):
    """Seam for tests to replace. Production path calls the real API."""
    return _client.messages.parse(**kwargs)


def _record(model: str, usage) -> None:
    if usage is None:
        return
    with _usage_lock:
        row = _usage.setdefault(model, [0, 0, 0])
        row[0] += 1
        row[1] += usage.input_tokens
        row[2] += usage.output_tokens


def reset_usage() -> None:
    with _usage_lock:
        _usage.clear()


def usage_summary() -> str:
    """One line describing the API calls made so far in this process."""
    with _usage_lock:
        rows = sorted(_usage.items())
    if not rows:
        return "API usage: 0 calls (everything came from the cache) - $0.00"
    parts, total = [], 0.0
    for model, (calls, tin, tout) in rows:
        pin, pout = PRICES.get(model, (0.0, 0.0))
        cost = tin / 1e6 * pin + tout / 1e6 * pout
        total += cost
        parts.append(f"{model}: {calls} calls, {tin:,} in / {tout:,} out tokens, ~${cost:.2f}")
    return "API usage: " + "; ".join(parts) + f" - total ~${total:.2f}"


def call_structured(prompt: str, schema: type[T], model: str, max_tokens: int = 2048) -> T:
    key = cache_key(model, prompt, schema)

    hit = cache_get(key)
    if hit is not None:
        return schema(**hit)

    try:
        response = _parse(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
    except anthropic.NotFoundError:
        log.error("Unknown model %r - check sdoc/config.py", model)
        raise
    except anthropic.RateLimitError:
        log.error("Rate limited after retries; lower --workers or wait")
        raise
    except anthropic.APIStatusError as e:
        log.error("API returned %s: %s", e.status_code, e)
        raise
    except anthropic.APIConnectionError:
        log.error("Could not reach the API - check your connection")
        raise

    _record(model, getattr(response, "usage", None))

    result = response.parsed_output
    if result is None:
        # Refusal or truncation. Never cache it: a retry might succeed.
        raise RuntimeError(
            f"{model} returned no structured output "
            f"(stop_reason={getattr(response, 'stop_reason', None)!r})"
        )
    cache_put(key, result.model_dump())
    return result
```

- [ ] **Step 5: Print the cost line after classification** — in `sdoc/run_classify.py`, add the import and the last log line of `main()`:

```python
from sdoc.ai.client import usage_summary
```

```python
    log.info(usage_summary())
```

(Place the `log.info(usage_summary())` line as the final statement inside `main()`, after the failures warning.)

- [ ] **Step 6: Run the tests**

Run: `python -m pytest -q`
Expected: all pass (27 at this point)

- [ ] **Step 7: Commit** (ask first)

```bash
git add sdoc/config.py sdoc/ai/client.py sdoc/run_classify.py tests/ai/test_client.py
git commit -m "feat: print API usage and cost after every run"
```

---

### Task 2: Teach the classifier whether documents were promised

The 0-attachment trap: 91 `BL_COMPARISON` emails with no attachments are correctly `OK` ("please send me the draft BL"), and 3 must escalate ("compare the attached" — but nothing came through). Only the body tells them apart, so the classifier answers it in the same call. This changes the classification prompt, so it re-runs all 520 once — the `email_504` rule committed earlier rides along in the same re-run.

**Files:**
- Modify: `sdoc/ai/classify.py`, `sdoc/run_classify.py`, `tests/ai/test_classify.py`, `tests/test_run_classify.py`
- Create: `tools/check_attachment_flag.py`

**Interfaces:**
- Produces: `Classification.says_documents_are_attached: bool`; each entry in `out/categories.json` gains `"says_documents_are_attached": bool | None` (`None` when classification failed)

- [ ] **Step 1: Write the failing test** — append to `tests/ai/test_classify.py`:

```python
def test_prompt_asks_whether_documents_are_said_to_be_attached():
    email = {"from": "a@b.com", "subject": "S", "body": "B", "email_id": "email_001"}
    prompt = classify.build_prompt(email)
    assert "says_documents_are_attached" in prompt
```

And in the same file, change the fake's return in `test_classify_delegates_to_the_client` to:

```python
        return schema(category="SPAM", says_documents_are_attached=False, reason="prize scam")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/ai/test_classify.py -v`
Expected: FAIL — the new prompt test, and the delegate test with a validation error about an unexpected field

- [ ] **Step 3: Add the field and the instruction** — in `sdoc/ai/classify.py`:

```python
class Classification(BaseModel):
    category: Literal["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
    says_documents_are_attached: bool
    reason: str
```

In `PROMPT`, replace the final line `Give the category and a short reason (under 15 words).` with:

```
Also answer says_documents_are_attached: true if the sender says documents
are attached to THIS email, or asks the recipient to compare documents they
have supposedly provided; false if they ask for documents to be sent or
prepared later, or mention no documents at all.

Give the category, says_documents_are_attached, and a short reason (under
15 words).
```

- [ ] **Step 4: Record the field** — in `sdoc/run_classify.py`, `_one()` becomes:

```python
def _one(email: dict) -> tuple[str, dict]:
    eid = email["email_id"]
    try:
        result = classify(email)
        return eid, {
            "category": result.category,
            "says_documents_are_attached": result.says_documents_are_attached,
            "reason": result.reason,
            "error": None,
        }
    except Exception:
        log.warning("classification failed for %s", eid)
        return eid, {
            "category": FALLBACK_CATEGORY,
            "says_documents_are_attached": None,
            "reason": "classification failed",
            "error": traceback.format_exc(),
        }
```

In `tests/test_run_classify.py`, every `Classification(...)` gains `says_documents_are_attached=False`, and `test_classifies_every_email` also asserts:

```python
    assert result["email_001"]["says_documents_are_attached"] is False
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest -q`
Expected: all pass

- [ ] **Step 6: Create `tools/check_attachment_flag.py`**

```python
"""Developer check: is says_documents_are_attached right on the emails where
it matters — BL_COMPARISON emails with no attachments? Also confirms the
email_504 fix. Reads ground truth, so it lives in tools/, never in sdoc/."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdoc.config import OUT_DIR  # noqa: E402
from sdoc.inbox import load_emails  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GT = ROOT / "sdoc-hackathon-docker" / "data_v2" / "ground_truth.json"

cats = json.loads((Path(OUT_DIR) / "categories.json").read_text(encoding="utf-8"))
gt = json.loads(GT.read_text(encoding="utf-8"))

targets = [e["email_id"] for e in load_emails()
           if not e["attachments"] and gt[e["email_id"]]["category"] == "BL_COMPARISON"]
wrong = [eid for eid in targets
         if cats[eid].get("says_documents_are_attached") != (gt[eid]["status"] == "NEEDS_REVIEW")]

print(f"BL_COMPARISON emails with no attachments: {len(targets)}")
print(f"says_documents_are_attached wrong on: {wrong or 'none'}")
print(f"email_504 category: {cats['email_504']['category']}  (should be BL_COMPARISON)")
```

- [ ] **Step 7: Commit** (ask first)

```bash
git add sdoc/ai/classify.py sdoc/run_classify.py tests/ai/test_classify.py tests/test_run_classify.py tools/check_attachment_flag.py
git commit -m "feat: classifier reports whether documents were promised as attached"
```

- [ ] **Step 8: Re-run classification** — **paid, ask first (~$0.70, ~3 min)**

```powershell
python -m sdoc.run_classify --workers 4
python tools/check_attachment_flag.py
```

Expected: 0 failures; the cost line prints; `wrong on: none` (a couple of misses is tolerable — note them); `email_504 category: BL_COMPARISON`.

- [ ] **Step 9: Re-score Stage 1** (free)

```powershell
python tools/make_submission.py
cd sdoc-hackathon-docker\server; $env:PYTHONIOENCODING="utf-8"; python score_cli.py ..\..\out\submission.json; cd ..\..
```

Expected: macro-F1 ≥ 0.999. If it dropped, stop and compare with `python tools/diff_errors.py` before continuing.

---

### Task 3: Field model and normalization

**Files:**
- Create: `sdoc/core/__init__.py` (empty), `sdoc/core/fields.py`, `sdoc/core/normalize.py`, `tests/core/__init__.py` (empty)
- Test: `tests/core/test_normalize.py`

**Interfaces:**
- Produces:
  - `sdoc.core.fields.FIELDS: list[str]` — the seven names, in report order
  - `sdoc.core.fields.ShipmentFields` — Pydantic model, all seven fields `str | None`, all required
  - `sdoc.core.normalize.is_blank(value: str | None) -> bool`
  - `sdoc.core.normalize.canon(value: str) -> str`
  - `sdoc.core.normalize.port_key(value: str) -> str`
  - `sdoc.core.normalize.count_value(value: str) -> int | None`
  - `sdoc.core.normalize.weight_kg(value: str) -> float | None`
  - `sdoc.core.normalize.same_party(a: str, b: str) -> bool`

- [ ] **Step 1: Write the failing tests** — `tests/core/test_normalize.py`:

```python
import pytest

from sdoc.core import normalize as N


@pytest.mark.parametrize("value", [None, "", "   ", "???", "_______", "TBA", "tbc", "N/A", "-", "____"])
def test_placeholders_are_blank(value):
    assert N.is_blank(value)


@pytest.mark.parametrize("value", ["UAB NOVAKOPA", "1 x 40'HC", "21,577 KG", "____MT"])
def test_real_looking_values_are_not_blank(value):
    # "____MT" is not blank text, but weight_kg() finds no number in it,
    # so the comparison still treats it as missing.
    assert not N.is_blank(value)


def test_canon_ignores_case_and_punctuation():
    assert N.canon("Moorim SP Co., Ltd") == N.canon("MOORIM SP CO LTD") == "MOORIM SP CO LTD"


def test_port_key_ignores_codes_but_not_names():
    assert N.port_key("SINGAPORE (SGSIN)") == N.port_key("SINGAPORE")
    # email_013: same UN/LOCODE, different port — a real defect
    assert N.port_key("MOMBASA, KENYA (KEMBA)") != N.port_key("TUTICORIN, INDIA (KEMBA)")


@pytest.mark.parametrize("value,expected", [
    ("1 x 40'HC", 1), ("15 x 20'GP", 15), ("6X40'HC", 6), ("6", 6), ("???", None),
])
def test_count_value(value, expected):
    assert N.count_value(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("21,577 KG", 21577), ("341715", 341715), ("131,322 KG", 131322),
    ("21.5 MT", 21500), ("____MT", None), ("N/A", None),
])
def test_weight_kg(value, expected):
    assert N.weight_kg(value) == expected


def test_same_party_allows_a_name_continued_on_the_next_line():
    assert N.same_party("APRIL FINE PAPER TRADING",
                        "APRIL FINE PAPER TRADING ON BEHALF OF VITAL SOLUTIONS PTE LTD")


def test_same_party_rejects_different_companies():
    assert not N.same_party("EAST BRIGHT FZ-LLC", "UAB NOVAKOPA")
    assert not N.same_party("APRIL", "APRIL FAR EAST (M) SDN BHD")   # prefix too short to trust
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/core/test_normalize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.core'`

- [ ] **Step 3: Create `sdoc/core/fields.py`**

```python
"""The seven compared fields. Pure data: no I/O, no AI."""
from pydantic import BaseModel

FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]


class ShipmentFields(BaseModel):
    """Raw values exactly as written in one document. None = absent/blank."""
    shipper: str | None
    consignee: str | None
    notify_party: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    container_count: str | None
    gross_weight_kg: str | None
```

- [ ] **Step 4: Create `sdoc/core/normalize.py`**

```python
"""Turn raw field values into comparable forms. Pure functions.

The rules are fitted to how values actually appear in the bundle:
counts are "6 x 40'HC", weights "131,058 KG", ports "CALLAO, PERU (PECLL)".
The only irregular values are the deliberate blanks: "N/A", "____MT", "".
"""
import re

_PLACEHOLDER_WORDS = {"TBA", "TBC", "TBD", "N/A", "NA", "NIL", "NONE", "UNKNOWN", "-"}
_PLACEHOLDER_CHARS = re.compile(r"[\s_?\-.*/]+")
_TONNES = re.compile(r"\b(MT|MTS|TONNES?|TONS?)\b")

# A shorter party name only matches a longer one that starts with it when it
# is at least this long — "APRIL" must not match "APRIL FAR EAST ...".
_MIN_PREFIX = 12


def is_blank(value: str | None) -> bool:
    if value is None:
        return True
    s = value.strip().upper()
    return not s or s in _PLACEHOLDER_WORDS or bool(_PLACEHOLDER_CHARS.fullmatch(s))


def canon(value: str) -> str:
    """Uppercase, punctuation to spaces, single-spaced."""
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", value.upper()).split())


def port_key(value: str) -> str:
    """Port name without bracketed codes. Compare names, never codes:
    email_013 keeps the code (KEMBA) while the port itself changes."""
    return canon(re.sub(r"\([^)]*\)", " ", value))


def count_value(value: str) -> int | None:
    m = re.search(r"(\d+)\s*[xX×]", value)
    if m:
        return int(m.group(1))
    m = re.search(r"\d+", value)
    return int(m.group(0)) if m else None


def weight_kg(value: str) -> float | None:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", value)
    if not m:
        return None
    n = float(m.group(0).replace(",", ""))
    if _TONNES.search(value.upper()):
        n *= 1000
    return n


def same_party(a: str, b: str) -> bool:
    ka, kb = canon(a), canon(b)
    if ka == kb:
        return True
    short, long_ = sorted((ka, kb), key=len)
    return len(short) >= _MIN_PREFIX and long_.startswith(short + " ")
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/core/test_normalize.py -v`
Expected: PASS

- [ ] **Step 6: Commit** (ask first)

```bash
git add sdoc/core/ tests/core/
git commit -m "feat: field model and per-field normalization rules"
```

---

### Task 4: Compare SI against BL

**Files:**
- Create: `sdoc/core/compare.py`
- Test: `tests/core/test_compare.py`

**Interfaces:**
- Consumes: `FIELDS`, `ShipmentFields`, everything in `sdoc.core.normalize`
- Produces:
  - `sdoc.core.compare.Row` — dataclass `name: str, si: str | None, bl: str | None, match: bool | None` (`None` = could not compare)
  - `sdoc.core.compare.Comparison` — dataclass `rows: list[Row], missing: list[str], defects: list[str]`, both lists in `FIELDS` order
  - `sdoc.core.compare.compare(si: ShipmentFields, bl: ShipmentFields) -> Comparison`

- [ ] **Step 1: Write the failing tests** — `tests/core/test_compare.py`:

```python
from sdoc.core.compare import compare
from sdoc.core.fields import ShipmentFields


def sf(**over):
    base = dict(
        shipper="APRIL FAR EAST (M) SDN BHD",
        consignee="MOORIM SP CO., LTD",
        notify_party="UAB NOVAKOPA",
        port_of_loading="PORT KLANG (WESTPORT), MALAYSIA (MYPKG)",
        port_of_discharge="CALLAO, PERU (PECLL)",
        container_count="1 x 40'HC",
        gross_weight_kg="21,577 KG",
    )
    base.update(over)
    return ShipmentFields(**base)


def test_identical_documents_have_no_defects():
    c = compare(sf(), sf())
    assert c.defects == [] and c.missing == []
    assert len(c.rows) == 7 and all(r.match for r in c.rows)


def test_formatting_differences_are_not_defects():
    c = compare(sf(), sf(consignee="Moorim SP Co Ltd", gross_weight_kg="21577",
                        port_of_discharge="CALLAO, PERU", container_count="1"))
    assert c.defects == []


def test_email_013_same_port_code_different_port_is_a_defect():
    c = compare(sf(port_of_discharge="MOMBASA, KENYA (KEMBA)"),
                sf(port_of_discharge="TUTICORIN, INDIA (KEMBA)"))
    assert c.defects == ["port_of_discharge"]


def test_email_043_container_count_keeps_raw_values_for_the_report():
    c = compare(sf(container_count="3 x 20'GP"), sf(container_count="5 x 20'GP"))
    assert c.defects == ["container_count"]
    row = next(r for r in c.rows if r.name == "container_count")
    assert (row.si, row.bl, row.match) == ("3 x 20'GP", "5 x 20'GP", False)


def test_defects_are_reported_in_field_order():
    c = compare(sf(), sf(gross_weight_kg="99,999 KG", shipper="SOMEONE ELSE LTD"))
    assert c.defects == ["shipper", "gross_weight_kg"]


def test_blank_value_is_missing_not_a_defect():
    c = compare(sf(gross_weight_kg="N/A", container_count=""), sf())
    assert c.missing == ["container_count", "gross_weight_kg"]
    assert c.defects == []
    assert next(r for r in c.rows if r.name == "container_count").match is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/core/test_compare.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.core.compare'`

- [ ] **Step 3: Create `sdoc/core/compare.py`**

```python
"""SI vs BL, field by field. Deterministic: the LLM reads the values,
this code decides whether they match."""
from dataclasses import dataclass

from sdoc.core import normalize as N
from sdoc.core.fields import FIELDS, ShipmentFields

PARTIES = {"shipper", "consignee", "notify_party"}
PORTS = {"port_of_loading", "port_of_discharge"}


@dataclass
class Row:
    name: str
    si: str | None
    bl: str | None
    match: bool | None          # None = one side blank, could not compare


@dataclass
class Comparison:
    rows: list[Row]
    missing: list[str]
    defects: list[str]


def _key(name: str, value: str | None):
    if N.is_blank(value):
        return None
    if name in PARTIES:
        return N.canon(value) or None
    if name in PORTS:
        return N.port_key(value) or None
    if name == "container_count":
        return N.count_value(value)
    return N.weight_kg(value)


def _equal(name: str, si: str, bl: str, ksi, kbl) -> bool:
    if name in PARTIES:
        return N.same_party(si, bl)
    if name == "gross_weight_kg":
        return abs(ksi - kbl) < 0.5
    return ksi == kbl


def compare(si: ShipmentFields, bl: ShipmentFields) -> Comparison:
    rows, missing, defects = [], [], []
    for name in FIELDS:
        a, b = getattr(si, name), getattr(bl, name)
        ka, kb = _key(name, a), _key(name, b)
        if ka is None or kb is None:
            missing.append(name)
            rows.append(Row(name, a, b, None))
            continue
        ok = _equal(name, a, b, ka, kb)
        rows.append(Row(name, a, b, ok))
        if not ok:
            defects.append(name)
    return Comparison(rows, missing, defects)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/core/ -v`
Expected: PASS

- [ ] **Step 5: Commit** (ask first)

```bash
git add sdoc/core/compare.py tests/core/test_compare.py
git commit -m "feat: deterministic SI vs BL field comparison"
```

---

### Task 5: Read every attachment format

**Files:**
- Create: `sdoc/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `sdoc.inbox.read_attachment_bytes(rel_path: str) -> bytes`
- Produces:
  - `sdoc.extract.DocText` — dataclass `path: str, text: str, readable: bool, problem: str | None = None`
  - `sdoc.extract.read_document(rel_path: str) -> DocText` — never raises; unreadable files come back with `readable=False` and a human-readable `problem`

- [ ] **Step 1: Write the failing tests** — `tests/test_extract.py` (golden tests against the real bundle):

```python
import pytest

from sdoc.extract import read_document


def test_txt_is_read():
    d = read_document("attachments/email_001_SI.txt")
    assert d.readable and "SHIPPING INSTRUCTION" in d.text


def test_xlsx_cells_are_read_as_lines():
    d = read_document("attachments/email_005_SI.xlsx")
    assert d.readable and "15 x 20'GP" in d.text and "341715" in d.text


def test_docx_is_read():
    d = read_document("attachments/email_055_BL.docx")
    assert d.readable and "BILL OF LADING" in d.text.upper()


def test_text_pdf_is_read():
    d = read_document("attachments/email_059_SI.pdf")
    assert d.readable and "131,322 KG" in d.text


def test_scanned_pdf_is_unreadable():
    d = read_document("attachments/email_512_SI.pdf")
    assert not d.readable and "scanned" in d.problem


@pytest.mark.parametrize("path", ["attachments/email_511_BL.pdf", "attachments/email_515_BL.pdf"])
def test_broken_pdf_is_unreadable(path):
    d = read_document(path)
    assert not d.readable and d.problem


def test_missing_file_is_unreadable_not_an_exception():
    d = read_document("attachments/does_not_exist.txt")
    assert not d.readable and d.problem == "file not found"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sdoc.extract'`

- [ ] **Step 3: Create `sdoc/extract.py`**

```python
"""Attachment -> text. Knows file formats, nothing about shipping.

Never raises: a file that cannot be read comes back readable=False with a
problem a human reviewer can act on. That is what feeds the `unreadable`
escalation.
"""
import io
from dataclasses import dataclass
from pathlib import Path

from sdoc.inbox import read_attachment_bytes

# Below this many characters a document has no usable text. For a PDF that
# means an image-only scan with no text layer.
MIN_TEXT = 50


@dataclass
class DocText:
    path: str
    text: str
    readable: bool
    problem: str | None = None


def _txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _pdf(data: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _docx(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    lines = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            # merged cells repeat their text; keep one copy
            kept = [c for i, c in enumerate(cells) if c and (i == 0 or c != cells[i - 1])]
            if kept:
                lines.append(" | ".join(kept))
    return "\n".join(lines)


def _xlsx(data: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append(" | ".join(cells))
    wb.close()
    return "\n".join(lines)


_READERS = {".txt": _txt, ".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx}


def read_document(rel_path: str) -> DocText:
    try:
        data = read_attachment_bytes(rel_path)
    except FileNotFoundError:
        return DocText(rel_path, "", False, "file not found")
    if not data.strip():
        return DocText(rel_path, "", False, "file is empty")

    suffix = Path(rel_path).suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        return DocText(rel_path, "", False, f"unsupported file type {suffix}")
    try:
        text = reader(data)
    except Exception as e:
        return DocText(rel_path, "", False,
                       f"file is corrupt or cannot be opened ({type(e).__name__})")

    if len(text.strip()) < MIN_TEXT:
        if suffix == ".pdf":
            return DocText(rel_path, text, False, "no text layer - looks like a scanned image")
        return DocText(rel_path, text, False, "almost no readable text")
    return DocText(rel_path, text, True)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_extract.py -v`
Expected: PASS. If `test_docx_is_read` fails on content, print `read_document("attachments/email_055_BL.docx").text` and adjust the assertion to what the file actually says — do not weaken the other tests.

- [ ] **Step 5: Commit** (ask first)

```bash
git add sdoc/extract.py tests/test_extract.py
git commit -m "feat: read txt, xlsx, docx and pdf attachments, flag unreadable ones"
```

---

### Task 6: Joint SI + BL extraction with Claude

**Files:**
- Create: `sdoc/ai/extract_pair.py`
- Test: `tests/ai/test_extract_pair.py`

**Interfaces:**
- Consumes: `call_structured(prompt, schema, model, max_tokens)`, `EXTRACT_MODEL`, `ShipmentFields`, `FIELDS`
- Produces:
  - `sdoc.ai.extract_pair.DocType = Literal["SHIPPING_INSTRUCTION", "BILL_OF_LADING", "OTHER"]`
  - `sdoc.ai.extract_pair.PairExtraction` — `si_doc_type: DocType, bl_doc_type: DocType, si: ShipmentFields, bl: ShipmentFields`
  - `sdoc.ai.extract_pair.build_prompt(si_text: str, bl_text: str) -> str`
  - `sdoc.ai.extract_pair.extract_pair(si_text: str, bl_text: str) -> PairExtraction`

- [ ] **Step 1: Write the failing tests** — `tests/ai/test_extract_pair.py`:

```python
from sdoc.ai import extract_pair as X
from sdoc.config import EXTRACT_MODEL
from sdoc.core.fields import FIELDS


def test_prompt_contains_both_documents_in_order():
    p = X.build_prompt("SI BODY TEXT", "BL BODY TEXT")
    assert "DOCUMENT A" in p and "DOCUMENT B" in p
    assert p.index("SI BODY TEXT") < p.index("BL BODY TEXT")


def test_prompt_forbids_reconciling_the_two_documents():
    assert "never fill in or correct one document" in X.build_prompt("a", "b").lower()


def test_prompt_treats_a_bl_instruction_as_an_si():
    # SI PDFs are titled "BILL OF LADING INSTRUCTION"; SI xlsx say "BL INSTRUCTION"
    assert "bill of lading instruction" in X.build_prompt("a", "b").lower()


def test_braces_in_document_text_survive():
    assert "{weird} {{text}}" in X.build_prompt("{weird} {{text}}", "b")


def test_extract_pair_uses_the_extract_model_with_room_to_think(monkeypatch):
    seen = {}

    def fake(prompt, schema, model, max_tokens=2048):
        seen.update(model=model, max_tokens=max_tokens)
        empty = {f: None for f in FIELDS}
        return schema(si_doc_type="SHIPPING_INSTRUCTION", bl_doc_type="BILL_OF_LADING",
                      si=empty, bl=empty)

    monkeypatch.setattr(X, "call_structured", fake)
    r = X.extract_pair("si", "bl")
    assert seen["model"] == EXTRACT_MODEL
    assert seen["max_tokens"] >= 8000
    assert r.bl_doc_type == "BILL_OF_LADING"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/ai/test_extract_pair.py -v`
Expected: FAIL — `ImportError: cannot import name 'extract_pair'`

- [ ] **Step 3: Create `sdoc/ai/extract_pair.py`**

```python
"""Read an SI and a draft BL together and return each one's type and its
seven raw field values. Deciding whether they match is NOT done here."""
from typing import Literal

from pydantic import BaseModel

from sdoc.ai.client import call_structured
from sdoc.config import EXTRACT_MODEL
from sdoc.core.fields import ShipmentFields

DocType = Literal["SHIPPING_INSTRUCTION", "BILL_OF_LADING", "OTHER"]

# Opus thinks by default and thinking tokens count against max_tokens, so
# leave room well beyond the ~400 tokens of JSON the answer needs.
MAX_TOKENS = 8000


class PairExtraction(BaseModel):
    si_doc_type: DocType
    bl_doc_type: DocType
    si: ShipmentFields
    bl: ShipmentFields


PROMPT = """You are reading two shipping documents for a document-verification check.
DOCUMENT A was attached as the Shipping Instruction (SI).
DOCUMENT B was attached as the draft Bill of Lading (BL).

1. Say what each document actually is:
   SHIPPING_INSTRUCTION  a shipping instruction or SI. A "Bill of Lading
                         Instruction" or "BL Instruction" is also an SI: it
                         is the shipper's instructions for the BL.
   BILL_OF_LADING        a bill of lading or draft BL.
   OTHER                 anything else: commercial invoice, packing list,
                         certificate of origin, and so on.

2. From EACH document separately, extract these seven fields:
   shipper, consignee, notify_party   the company name only, as written.
                                      Include continuation lines that are
                                      part of the name (for example
                                      "ON BEHALF OF ..."); exclude street
                                      address, phone and email.
   port_of_loading, port_of_discharge the port as written, including
                                      country and code if shown.
   container_count                    as written, e.g. "6 x 40'HC".
   gross_weight_kg                    the TOTAL gross weight as written,
                                      e.g. "131,322 KG" (not a per-container
                                      row).

Labels differ between documents ("Port of Loading", "POL", "Load Port";
"Consignee", "To the Order of"). Match fields by meaning, not by label.

Rules:
- Copy each value exactly as it appears in THAT document. Never fill in or
  correct one document's value using the other document. The two documents
  are expected to disagree sometimes; finding those disagreements is the
  whole purpose of this check.
- If a field is absent, blank, or a placeholder such as ???, ____, TBA, TBC
  or N/A, return null for it.
- For a document of type OTHER, still extract whatever fields it has and
  return null for the rest.

DOCUMENT A (attached as the SI):
<<<
{si}
>>>

DOCUMENT B (attached as the BL):
<<<
{bl}
>>>"""


def build_prompt(si_text: str, bl_text: str) -> str:
    return PROMPT.format(si=si_text, bl=bl_text)


def extract_pair(si_text: str, bl_text: str) -> PairExtraction:
    return call_structured(build_prompt(si_text, bl_text), PairExtraction,
                           EXTRACT_MODEL, max_tokens=MAX_TOKENS)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/ai/ -v`
Expected: PASS

- [ ] **Step 5: Commit** (ask first)

```bash
git add sdoc/ai/extract_pair.py tests/ai/test_extract_pair.py
git commit -m "feat: joint SI and BL field extraction with Claude"
```

---

### Task 7: The checks, in order

**Files:**
- Create: `sdoc/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `read_document`, `DocText`, `extract_pair`, `PairExtraction`, `compare`, `ShipmentFields`
- Produces:
  - `sdoc.pipeline.base_result(cls: dict) -> dict` — keys: `category, reason, status, review_reason, has_defect, defect_fields, fields, note, error, failed`
  - `sdoc.pipeline.process(email: dict, cls: dict) -> dict` — `cls` is one entry of `categories.json`
  - `sdoc.pipeline.to_submission(results: dict, all_ids: list[str]) -> dict`

- [ ] **Step 1: Write the failing tests** — `tests/test_pipeline.py`:

```python
import pytest

from sdoc import pipeline
from sdoc.ai.extract_pair import PairExtraction
from sdoc.core.fields import ShipmentFields
from sdoc.extract import DocText


def fields(**over):
    base = dict(
        shipper="APRIL FAR EAST (M) SDN BHD", consignee="MOORIM SP CO., LTD",
        notify_party="UAB NOVAKOPA", port_of_loading="PORT KLANG (WESTPORT), MALAYSIA (MYPKG)",
        port_of_discharge="CALLAO, PERU (PECLL)", container_count="1 x 40'HC",
        gross_weight_kg="21,577 KG",
    )
    base.update(over)
    return ShipmentFields(**base)


BL = {"category": "BL_COMPARISON", "reason": "check", "says_documents_are_attached": True}
TWO = {"email_id": "email_900",
       "attachments": ["attachments/email_900_SI.txt", "attachments/email_900_BL.txt"]}


@pytest.fixture
def readable(monkeypatch):
    monkeypatch.setattr(pipeline, "read_document", lambda p: DocText(p, "some text " * 20, True))


def use_pair(monkeypatch, si=None, bl=None, si_type="SHIPPING_INSTRUCTION", bl_type="BILL_OF_LADING"):
    pair = PairExtraction(si_doc_type=si_type, bl_doc_type=bl_type,
                          si=si or fields(), bl=bl or fields())
    monkeypatch.setattr(pipeline, "extract_pair", lambda s, b: pair)


def test_other_categories_pass_through():
    r = pipeline.process({"email_id": "e", "attachments": []}, {"category": "SPAM", "reason": "scam"})
    assert (r["category"], r["status"], r["review_reason"], r["defect_fields"]) == ("SPAM", "OK", None, [])


def test_no_attachments_and_none_promised_is_ok():
    r = pipeline.process({"email_id": "e", "attachments": []}, {**BL, "says_documents_are_attached": False})
    assert (r["status"], r["review_reason"]) == ("OK", None)


def test_no_attachments_but_promised_is_missing_attachment():
    r = pipeline.process({"email_id": "e", "attachments": []}, BL)
    assert (r["status"], r["review_reason"]) == ("NEEDS_REVIEW", "missing_attachment")


def test_only_one_attachment_is_missing_attachment():
    r = pipeline.process({"email_id": "e", "attachments": ["attachments/e_SI.txt"]}, BL)
    assert r["review_reason"] == "missing_attachment" and "draft BL" in r["note"]


def test_unreadable_file_escalates(monkeypatch):
    monkeypatch.setattr(pipeline, "read_document",
                        lambda p: DocText(p, "", False, "file is empty") if p.endswith("_BL.txt")
                        else DocText(p, "x" * 80, True))
    r = pipeline.process(TWO, BL)
    assert r["review_reason"] == "unreadable" and "file is empty" in r["note"]


def test_wrong_document_type_is_reported_before_blank_values(monkeypatch, readable):
    use_pair(monkeypatch, bl_type="OTHER",
             bl=fields(port_of_loading=None, port_of_discharge=None,
                       container_count=None, gross_weight_kg=None))
    r = pipeline.process(TWO, BL)
    assert r["review_reason"] == "wrong_doc_type"
    assert r["note"].startswith("The file attached as the BL is a different kind of document")


def test_blank_value_escalates_as_missing_value(monkeypatch, readable):
    use_pair(monkeypatch, si=fields(gross_weight_kg="____MT"))
    r = pipeline.process(TWO, BL)
    assert r["review_reason"] == "missing_value" and "gross_weight_kg" in r["note"]


def test_mismatch_reports_exact_fields(monkeypatch, readable):
    use_pair(monkeypatch, bl=fields(consignee="UAB NOVAKOPA", notify_party="EAST BRIGHT FZ-LLC"))
    r = pipeline.process(TWO, BL)
    assert (r["status"], r["has_defect"]) == ("MISMATCH", True)
    assert r["defect_fields"] == ["consignee", "notify_party"]
    assert {f["name"] for f in r["fields"] if f["match"] is False} == {"consignee", "notify_party"}


def test_everything_matching_is_ok(monkeypatch, readable):
    use_pair(monkeypatch, bl=fields(consignee="MOORIM SP CO LTD", gross_weight_kg="21577"))
    r = pipeline.process(TWO, BL)
    assert r["status"] == "OK" and r["note"] == "No mismatch detected." and len(r["fields"]) == 7


def test_submission_has_every_id_and_only_scored_keys():
    results = {"email_001": {"category": "BL_COMPARISON", "status": "MISMATCH", "review_reason": None,
                             "has_defect": True, "defect_fields": ["consignee"], "fields": [], "note": "x"}}
    sub = pipeline.to_submission(results, ["email_001", "email_002"])
    assert set(sub) == {"email_001", "email_002"}
    assert sub["email_001"] == {"category": "BL_COMPARISON", "status": "MISMATCH", "review_reason": None,
                                "has_defect": True, "defect_fields": ["consignee"]}
    assert sub["email_002"]["category"] == "GENERAL"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ImportError: cannot import name 'pipeline'`

- [ ] **Step 3: Create `sdoc/pipeline.py`**

```python
"""One email in, one decision out. The checks run in a fixed order and the
first one that fails decides the review reason — the most specific failure
is always reported, never a symptom of it (spec, section 4)."""
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
        if cls.get("says_documents_are_attached"):
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
    result = compare(pair.si, pair.bl)
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
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Commit** (ask first)

```bash
git add sdoc/pipeline.py tests/test_pipeline.py
git commit -m "feat: escalation checks in spec order, and submission from results"
```

---

### Task 8: The pipeline runner

**Files:**
- Create: `sdoc/run_pipeline.py`
- Test: `tests/test_run_pipeline.py`

**Interfaces:**
- Consumes: `process`, `base_result`, `to_submission`, `usage_summary`, `load_emails`, `OUT_DIR`
- Produces:
  - `sdoc.run_pipeline.run_one(email: dict, cls: dict) -> tuple[str, dict]` — never raises
  - `sdoc.run_pipeline.run(emails: list[dict], categories: dict, previous: dict, workers: int = 4) -> dict`
  - CLI: `python -m sdoc.run_pipeline [--only id,id] [--limit N] [--workers N]` → `out/results.json`, `out/submission.json`

- [ ] **Step 1: Write the failing tests** — `tests/test_run_pipeline.py`:

```python
from sdoc import run_pipeline


def test_a_crash_becomes_a_review_case_not_a_missing_email(monkeypatch):
    def boom(email, cls):
        raise RuntimeError("api down")

    monkeypatch.setattr(run_pipeline, "process", boom)
    eid, r = run_pipeline.run_one({"email_id": "email_009"},
                                  {"category": "BL_COMPARISON", "reason": "x"})
    assert eid == "email_009"
    assert (r["status"], r["review_reason"], r["failed"]) == ("NEEDS_REVIEW", "unreadable", True)
    assert "api down" in r["error"]


def test_run_keeps_earlier_results_for_emails_not_in_this_run(monkeypatch):
    monkeypatch.setattr(run_pipeline, "process",
                        lambda e, c: {"category": c["category"], "status": "OK"})
    previous = {"email_001": {"category": "BL_COMPARISON", "status": "MISMATCH"}}
    out = run_pipeline.run([{"email_id": "email_002"}], {"email_002": {"category": "SPAM"}},
                           previous, workers=1)
    assert out["email_001"]["status"] == "MISMATCH"
    assert out["email_002"]["category"] == "SPAM"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_run_pipeline.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_pipeline'`

- [ ] **Step 3: Create `sdoc/run_pipeline.py`**

```python
"""Run the comparison checks over the inbox.

Reads out/categories.json (run `python -m sdoc.run_classify` first) and
writes out/results.json for the UI and out/submission.json for the scorer.
"""
import argparse
import json
import logging
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sdoc.ai.client import usage_summary
from sdoc.config import OUT_DIR
from sdoc.inbox import load_emails
from sdoc.pipeline import base_result, process, to_submission

log = logging.getLogger(__name__)


def run_one(email: dict, cls: dict) -> tuple[str, dict]:
    eid = email["email_id"]
    try:
        return eid, process(email, cls)
    except Exception:
        log.warning("processing failed for %s", eid)
        r = base_result(cls)
        r.update(status="NEEDS_REVIEW", review_reason="unreadable", failed=True,
                 note="Processing failed before a decision was reached - see the error.",
                 error=traceback.format_exc())
        return eid, r


def run(emails: list[dict], categories: dict, previous: dict, workers: int = 4) -> dict:
    results = dict(previous)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for eid, r in pool.map(lambda e: run_one(e, categories.get(e["email_id"], {})), emails):
            results[eid] = r
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", help="comma-separated email ids, e.g. email_004,email_013")
    ap.add_argument("--limit", type=int, help="only the first N emails")
    ap.add_argument("--workers", type=int, default=4, help="parallel requests (default 4)")
    args = ap.parse_args()

    out = Path(OUT_DIR)
    cats_path = out / "categories.json"
    if not cats_path.exists():
        raise SystemExit(f"{cats_path} not found. Run `python -m sdoc.run_classify` first.")
    categories = json.loads(cats_path.read_text(encoding="utf-8"))

    emails = load_emails()
    all_ids = [e["email_id"] for e in emails]
    todo = emails
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        todo = [e for e in emails if e["email_id"] in wanted]
    elif args.limit:
        todo = emails[: args.limit]

    # Partial runs update the previous results rather than wiping them.
    results_path = out / "results.json"
    previous = {}
    if (args.only or args.limit) and results_path.exists():
        previous = json.loads(results_path.read_text(encoding="utf-8"))

    log.info("processing %d emails with %d workers", len(todo), args.workers)
    results = run(todo, categories, previous, args.workers)
    for eid in all_ids:
        if eid not in results:
            results[eid] = {**base_result(categories.get(eid, {})), "note": "Not processed yet."}

    ordered = {eid: results[eid] for eid in all_ids}
    out.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
    (out / "submission.json").write_text(json.dumps(to_submission(ordered, all_ids), indent=2),
                                         encoding="utf-8")

    bl = [r for r in ordered.values() if r["category"] == "BL_COMPARISON"]
    log.info("wrote %s and submission.json (%d ids)", results_path, len(ordered))
    log.info("BL_COMPARISON status: %s", dict(Counter(r["status"] for r in bl)))
    log.info("review reasons: %s", dict(Counter(r["review_reason"] for r in bl if r["review_reason"])))
    failed = sum(1 for r in ordered.values() if r.get("failed"))
    if failed:
        log.warning("%d emails failed during processing - see 'error' in results.json", failed)
    log.info(usage_summary())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest -q`
Expected: all pass

- [ ] **Step 5: Check the CLI starts** (free, no API: `--help` only)

Run: `python -m sdoc.run_pipeline --help`
Expected: usage text listing `--only`, `--limit`, `--workers`

- [ ] **Step 6: Commit** (ask first)

```bash
git add sdoc/run_pipeline.py tests/test_run_pipeline.py
git commit -m "feat: pipeline runner writing results.json and submission.json"
```

---

### Task 9: Measure, run, score

**Files:**
- Modify: `tools/diff_errors.py`

- [ ] **Step 1: Teach the diff tool about escalations** — in `tools/diff_errors.py`, after the `DEFECT FIELDS WRONG` block and before the final `if not wrong_category ...`, add:

```python
    wrong_review = []
    for eid, truth in gt.items():
        mine = sub.get(eid, {})
        want = (truth.get("status"), truth.get("review_reason"))
        got = (mine.get("status"), mine.get("review_reason"))
        if "NEEDS_REVIEW" in (want[0], got[0]) and want != got:
            wrong_review.append((eid, got, want))

    print(f"\nESCALATION WRONG: {len(wrong_review)}")
    for eid, got, want in wrong_review[: args.limit]:
        print(f"  {eid}  said {got} actual {want}")
```

and change the final condition to `if not wrong_category and not wrong_fields and not wrong_review:`.

- [ ] **Step 2: Measure on 5 known emails** — **paid, ask first (~$0.10)**

```powershell
python -m sdoc.run_pipeline --only email_001,email_004,email_013,email_043,email_059
```

Expected, from the data: 001 → OK, 004 → MISMATCH `consignee, notify_party`, 013 → MISMATCH `port_of_discharge`, 043 → MISMATCH `container_count`, 059 (PDF pair) → OK. Read the printed cost line and multiply by 119/5 (the BL emails with two readable attachments) for the full-run cost. **Report both numbers to the user before Step 3.**

- [ ] **Step 3: Full run** — **paid, ask first, quoting the measured estimate from Step 2**

```powershell
python -m sdoc.run_pipeline
```

- [ ] **Step 4: Score and diff** (free)

```powershell
cd sdoc-hackathon-docker\server; $env:PYTHONIOENCODING="utf-8"; python score_cli.py ..\..\out\submission.json; cd ..\..
python tools/diff_errors.py
```

Target: end-to-end ≥ 0.9, stage-3 defect F1 ≥ 0.9, escalation recall 20/20 with high precision. For every wrong email, open its two attachments and decide: extraction problem (fix the Task 6 prompt — costs a re-run) or normalization problem (fix Task 3/4 rules — free, re-run is from cache). Fix the rule, never the email. Add a failing test to `tests/core/` for every normalization fix.

- [ ] **Step 5: Commit** (ask first)

```bash
git add tools/diff_errors.py
git commit -m "feat: diff tool reports escalation differences"
```

---

### Task 10: Show the comparison in the UI

**Files:**
- Modify: `sdoc/web/app.py`, `sdoc/web/templates/base.html`, `sdoc/web/templates/inbox.html`, `sdoc/web/templates/email.html`, `requirements.txt`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `results.json` entries as produced by Task 7 (`fields` rows have `name, si, bl, match`); `sdoc.extract.read_document`
- Produces: route `GET /?status=OK|MISMATCH|NEEDS_REVIEW`; comparison panel on `/email/{id}`

- [ ] **Step 1: Add `httpx` to `requirements.txt`** (FastAPI's TestClient needs it) and install it:

```
httpx>=0.27
```

Run: `python -m pip install httpx`

- [ ] **Step 2: Write the failing tests** — `tests/test_web.py`:

```python
import json

import pytest
from fastapi.testclient import TestClient

from sdoc.web import app as web


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUT_DIR", tmp_path)

    def write(data):
        (tmp_path / "results.json").write_text(json.dumps(data), encoding="utf-8")

    return TestClient(web.app), write


def test_detail_page_shows_si_and_bl_side_by_side(site):
    client, write = site
    write({"email_043": {
        "category": "BL_COMPARISON", "reason": "x", "status": "MISMATCH", "review_reason": None,
        "has_defect": True, "defect_fields": ["container_count"], "note": None,
        "fields": [{"name": "container_count", "si": "3 x 20'GP", "bl": "5 x 20'GP", "match": False}],
    }})
    html = client.get("/email/email_043").text
    assert "3 x 20&#39;GP" in html and "5 x 20&#39;GP" in html
    assert "cmp-table" in html


def test_verification_status_only_shown_for_bl_emails(site):
    client, write = site
    write({"email_002": {"category": "INVOICE_QUERY", "reason": "x", "status": "OK"}})
    html = client.get("/").text
    row = html.split('data-id="email_002"')[1].split("</tr>")[0]
    assert 'class="status' not in row


def test_status_filter_shows_only_that_status(site):
    client, write = site
    write({"email_001": {"category": "BL_COMPARISON", "status": "OK"},
           "email_004": {"category": "BL_COMPARISON", "status": "MISMATCH"}})
    html = client.get("/?status=MISMATCH").text
    assert 'data-id="email_004"' in html and 'data-id="email_001"' not in html
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest tests/test_web.py -v`
Expected: FAIL — no `cmp-table`, status dot on the invoice row, status filter ignored

- [ ] **Step 4: Update `sdoc/web/app.py`**

Replace the import `from sdoc.inbox import load_emails, read_attachment_text` with:

```python
from sdoc.extract import read_document
from sdoc.inbox import load_emails
```

Add after `DECISIONS = {...}`:

```python
STATUSES = ["OK", "MISMATCH", "NEEDS_REVIEW"]
```

Replace `_shell` with:

```python
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
```

Replace the `inbox` route with:

```python
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
        context={"emails": emails, "total": len(all_emails), **_shell(results, category, status)},
    )
```

In the `attachment` route, replace the `try: text = read_attachment_text(path) ... if not text.strip(): ...` block with:

```python
    doc = read_document(path)
    if doc.problem == "file not found":
        raise HTTPException(status_code=404, detail=f"missing file: {path}")
    text = doc.text if doc.readable else f"(This file cannot be read: {doc.problem}.)"
```

and delete the now-stale comment about binary formats decoding to mojibake.

- [ ] **Step 5: Status filter in `sdoc/web/templates/base.html`** — replace the whole status block (from `<span class="fbtn" aria-disabled="true" title="Available once comparison has run">Status: All</span>` through its `{% endfor %}`) with:

```html
    {% if has_comparison %}
      <a class="fbtn" href="/" aria-pressed="{{ 'true' if not active_status else 'false' }}">Status: All</a>
      {% for s in statuses %}
        <a class="fbtn" href="/?status={{ s }}" aria-pressed="{{ 'true' if active_status == s else 'false' }}">
          <span class="status {{ s }}"></span>{{ 'REVIEW' if s == 'NEEDS_REVIEW' else s }}
        </a>
      {% endfor %}
    {% else %}
      <span class="fbtn" aria-disabled="true" title="Available once comparison has run">Status: All</span>
      {% for s in statuses %}
        <span class="fbtn" aria-disabled="true" title="Available once comparison has run">
          <span class="status {{ s }}"></span>{{ 'REVIEW' if s == 'NEEDS_REVIEW' else s }}
        </span>
      {% endfor %}
    {% endif %}
```

- [ ] **Step 6: Verification column only for BL rows** — in `sdoc/web/templates/inbox.html`, change the verification cell condition from `{% if r.get('status') %}` to:

```html
          {% if r.get('category') == 'BL_COMPARISON' and r.get('status') and r.get('note') != 'Not processed yet.' %}
```

- [ ] **Step 7: Comparison panel in `sdoc/web/templates/email.html`**

Add to the `<style>` block:

```css
  .cmp { margin-top:var(--lg); background:var(--l1); border:1px solid var(--border); border-radius:var(--r-ctl); overflow:hidden; }
  .cmp-head { display:flex; align-items:center; gap:var(--md); flex-wrap:wrap;
              padding:var(--lg) var(--xl); border-bottom:1px solid var(--border); }
  .cmp-head .t { display:inline-flex; align-items:center; gap:var(--md); color:var(--primary); font-size:14px; font-weight:600; }
  .cmp-head .rr { font-family:var(--mono); font-size:11px; color:var(--review); }
  .cmp-note { margin:0; padding:var(--md) var(--xl); color:var(--fg-muted); font-size:13px; }
  .cmp-table { width:100%; border-collapse:collapse; }
  .cmp-table th { text-align:left; font-size:11px; font-weight:600; letter-spacing:.05em; text-transform:uppercase;
                  color:var(--fg-subtle); padding:var(--sm) var(--xl); background:var(--l2); border-top:1px solid var(--border); }
  .cmp-table td { padding:var(--sm) var(--xl); border-top:1px solid var(--border);
                  font-family:var(--mono); font-size:12px; overflow-wrap:anywhere; }
  .cmp-table td.fn { font-family:var(--sans); color:var(--fg-muted); white-space:nowrap; }
  .cmp-table td.mk { width:40px; text-align:center; font-family:var(--sans); font-weight:700; }
  .cmp-table tr.bad td { background:rgba(220,38,38,.12); }
  .cmp-table tr.bad td.mk { color:var(--mismatch); }
  .cmp-table tr.miss td { background:rgba(217,119,6,.10); }
  .cmp-table tr.ok td.mk { color:var(--ok); }
  .cmp-muted { margin-top:var(--lg); color:var(--fg-subtle); font-size:12px; }
```

Replace the reserved placeholder `<div class="report"> ... </div>` with:

```html
  {% if cat and cat.get('category') == 'BL_COMPARISON' and 'fields' in cat %}
  <section class="cmp" aria-label="Comparison report">
    <div class="cmp-head">
      <span class="t"><svg class="ico"><use href="#i-diff"/></svg> Comparison report</span>
      <span class="status {{ cat.status }}">{{ 'REVIEW' if cat.status == 'NEEDS_REVIEW' else cat.status }}</span>
      {% if cat.get('review_reason') %}<span class="rr">{{ cat.review_reason }}</span>{% endif %}
    </div>
    {% if cat.get('note') %}<p class="cmp-note">{{ cat.note }}</p>{% endif %}
    {% if cat.fields %}
    <table class="cmp-table">
      <thead><tr><th>Field</th><th>SI (reference)</th><th>BL (draft)</th><th></th></tr></thead>
      <tbody>
      {% for f in cat.fields %}
        {% set state = 'bad' if f.match is sameas false else ('miss' if f.match is none else 'ok') %}
        <tr class="{{ state }}">
          <td class="fn">{{ f.name }}</td>
          <td>{{ f.si if f.si is not none else '(blank)' }}</td>
          <td>{{ f.bl if f.bl is not none else '(blank)' }}</td>
          <td class="mk" title="{{ {'bad': 'differs', 'miss': 'blank', 'ok': 'matches'}[state] }}">{{ {'bad': '✗', 'miss': '?', 'ok': '✓'}[state] }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
    {% endif %}
  </section>
  {% elif cat and cat.get('category') and cat.get('category') != 'BL_COMPARISON' %}
  <p class="cmp-muted">Not a document-check request, so no SI vs BL comparison is needed.</p>
  {% else %}
  <div class="report">
    <span class="t"><svg class="ico"><use href="#i-diff"/></svg> Comparison report</span>
    <div class="s">Appears here once the pipeline has run</div>
  </div>
  {% endif %}
```

In the toolbar, change the status condition from `{% if cat.get('status') %}` to `{% if cat.get('category') == 'BL_COMPARISON' and cat.get('status') %}`.

- [ ] **Step 8: Run the tests**

Run: `python -m pytest -q`
Expected: all pass

- [ ] **Step 9: Look at it** — **ask first** (starts a local server; free)

Run: `python -m uvicorn sdoc.web.app:app --port 8000` and check `/email/email_043` (container count row red, `SI: 3 x 20'GP / BL: 5 x 20'GP`), `/email/email_504` (REVIEW, `wrong_doc_type`), `/email/email_001` ("No mismatch detected."), `/?status=MISMATCH`, and a PDF attachment link (real text now, not mojibake). Stop the server afterwards and confirm the port is free.

- [ ] **Step 10: Commit** (ask first)

```bash
git add requirements.txt sdoc/web/ tests/test_web.py
git commit -m "feat: SI vs BL comparison panel, status filter, readable attachments"
```

---

### Task 11: README and push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`**

In the Status table, replace the three 🚧 rows with:

```markdown
| ✅ Document reading | txt, xlsx, docx, pdf; scanned or broken files flagged as unreadable |
| ✅ Field comparison + escalation | Claude reads both documents, Python decides; the four review reasons |
| ✅ Comparison report in the UI | SI and BL side by side, status filter, Mark Verified / Flag Mismatch |
| 🚧 Vision for scanned PDFs | Deferred — those emails escalate to a human either way |
```

Replace the paragraph starting `Because comparison is not built yet` with:

```markdown
Scanned PDFs are not OCR'd yet: they go straight to human review as
`unreadable`, which is also what the brief asks for when a document cannot
be read dependably.
```

After the `### Options` block of "Run the classifier", add:

````markdown
## Run the comparison

Needs `out/categories.json` from the classifier. Document extraction runs on
Claude Opus, one call per document-check email (about 120 calls).

```bash
python -m sdoc.run_pipeline --only email_004,email_013   # a couple first
python -m sdoc.run_pipeline                              # everything
```

Writes `out/results.json` (the full report the web UI shows) and
`out/submission.json` (the five scored keys for all 520 emails). Every run
ends with a line showing API calls made and their approximate cost; re-runs
come from the cache and cost nothing.

If an email fails during processing it is kept, marked `NEEDS_REVIEW`, and
its error is stored in `results.json`. Retry just that email with
`python -m sdoc.run_pipeline --only email_123` — the rest of the results
are kept.
````

In "Score a submission", replace the `make_submission.py` code block and the sentence after it with:

````markdown
`run_pipeline` already writes `out/submission.json`. To score classification
alone, before the comparison has run:

```bash
python tools/make_submission.py              # out/categories.json -> out/submission.json
```
````

In "Layout", replace the `sdoc/` tree with:

```
sdoc/
├── config.py          all paths, model names and prices
├── inbox.py           reads the bundle — knows nothing about AI
├── extract.py         txt / xlsx / docx / pdf -> text, or why it can't be read
├── core/
│   ├── fields.py      the seven compared fields
│   ├── normalize.py   blanks, weights, counts, ports, party names
│   └── compare.py     SI vs BL, field by field — no AI
├── ai/
│   ├── cache.py       content-addressed disk cache
│   ├── client.py      the only file that imports `anthropic`; counts cost
│   ├── classify.py    email -> category, owns the prompt
│   └── extract_pair.py SI + BL -> document types and raw field values
├── pipeline.py        the checks, in order -> one decision per email
├── run_classify.py    CLI: classify the inbox
├── run_pipeline.py    CLI: check the documents
└── web/               FastAPI + Jinja templates
```

Update the two test-count mentions ("22 tests") to the number `python -m pytest -q` prints.

- [ ] **Step 2: Commit and push** — **ask first**

```bash
git add README.md
git commit -m "docs: README for the comparison pipeline"
git push origin main
```

Confirm on GitHub that every new commit is authored `CHUO JESSE` with no co-author line.

---

## Paid steps at a glance

| Task | Command | Cost |
|---|---|---|
| 2 | `python -m sdoc.run_classify --workers 4` | ~$0.70 |
| 9 | `python -m sdoc.run_pipeline --only …5 ids…` | ~$0.10 |
| 9 | `python -m sdoc.run_pipeline` | measured in the step above; estimate $2–4 |
| 9 | each extraction-prompt fix + re-run | same as the full run |

Normalization fixes (Tasks 3–4) cost nothing to re-run: the extraction answers come from the cache.
