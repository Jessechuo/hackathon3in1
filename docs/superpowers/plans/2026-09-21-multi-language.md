# Malay and Chinese Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MailOps accepts emails and SI/BL documents written in Malay or Chinese (or mixed with English) and sorts and compares them correctly, and the website can be used in English, Malay or Chinese.

**Architecture:** Mail side: the classifier prompt names the three languages; the document extractor also returns an English form of every value, and the deterministic comparison treats a field as matching when the originals match or the English forms match. Website side: one translation table keyed by the English sentence, a `t()` function read from a per-request context variable, a `/lang/<code>` switch stored in a cookie, and tests that render every page in Malay and Chinese and fail on any untranslated text.

**Tech Stack:** Python 3.13, FastAPI, Jinja2, pydantic, Anthropic structured outputs, pytest, stdlib only for i18n.

**Spec:** `docs/superpowers/specs/2026-09-21-multi-language-design.md`

## Global Constraints

- `out/submission.json`, `out/score.json` and the 520 saved results are never changed. The organizers' Docker scorer is not re-run.
- Nothing is translated for its own sake: emails are stored and shown as written.
- Never translated on the website: category codes (`BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, `SPAM`), status codes (`OK`, `MISMATCH`, `REVIEW`), the seven field names, email content, and the AI's stored notes (`reason`, pipeline `note`, `send_error`). Elements that show such data carry `translate="no"`.
- Languages: `en` (default), `ms` shown as **BM**, `zh` shown as **中文**, Simplified characters. `<html lang>`: `en`, `ms`, `zh-Hans`.
- Cookie `mailops-lang`, one year. No new dependencies.
- The test suite never calls the Anthropic API. Paid calls happen only in Task 11 and only with the owner's go-ahead.
- Running `python -m pytest` needs no approval. Starting servers, opening a browser, committing and pushing need the owner's go-ahead.
- No per-task commits: one commit at the end (Task 12) after the owner's go-ahead, author CHUO JESSE, no co-author lines. The spec and this plan go in that commit.

## File Map

| File | Change |
|---|---|
| `sdoc/core/normalize.py` | `canon` keeps all letters; tonnes in Chinese and Malay |
| `sdoc/core/compare.py` | `compare(si, bl, si_en=None, bl_en=None)`; `Row.si_en`, `Row.bl_en` |
| `sdoc/ai/extract_pair.py` | `PairExtraction.si_en`, `.bl_en`; English-form rules in the prompt |
| `sdoc/pipeline.py` | pass the English forms to `compare` |
| `sdoc/ai/classify.py` | prompt names the three languages |
| `sdoc/web/i18n.py` (new) | languages, `pick`, `use`, `t`, `strings`, `MISSES` |
| `sdoc/web/translations.json` (new) | `{"English sentence": {"ms": "...", "zh": "..."}}` |
| `sdoc/web/app.py` | language middleware, `/lang/<code>`, Jinja globals, translated server messages |
| `sdoc/web/auth.py` | translated account errors |
| `sdoc/web/templates/*.html` | `t()` around visible text; `translate="no"` on data; language switch |
| `demo/multilang/*` (new) | six test emails and their documents, `cases.json` |
| `tools/multilang_check.py` (new) | runs the six emails through the real pipeline |
| `tests/core/…`, `tests/test_*.py` | tests per task (paths below) |

---

### Task 1: Normalising keeps Chinese letters and reads tonnes in Chinese and Malay

**Files:**
- Modify: `sdoc/core/normalize.py:9-27`
- Test: `tests/test_normalize_languages.py` (new)

**Interfaces:**
- Produces: `canon(value) -> str` unchanged signature, now Unicode-aware; `weight_kg` recognises 吨, 公吨, 噸, TAN.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from sdoc.core import normalize as N


def test_a_chinese_company_name_is_not_a_blank():
    """canon kept only A-Z and 0-9, so a Chinese name became "" - and the
    comparison reported the field as missing."""
    assert N.canon("马来西亚纸业有限公司") == "马来西亚纸业有限公司"
    assert N.canon("巴生港, 马来西亚 (MYPKG)") == "巴生港 马来西亚 MYPKG"


def test_english_values_normalise_exactly_as_before():
    assert N.canon("Asia Pacific Paperboard Trading Pte. Ltd.") == "ASIA PACIFIC PAPERBOARD TRADING PTE LTD"
    assert N.port_key("CALLAO, PERU (PECLL)") == "CALLAO PERU"


def test_tonnes_are_read_in_chinese_and_malay():
    # approx: 13.1 * 1000 is 13100.000000000002 in floating point
    assert N.weight_kg("131.322 公吨") == pytest.approx(131322)
    assert N.weight_kg("13.1 吨") == pytest.approx(13100)
    assert N.weight_kg("131.322 tan metrik") == pytest.approx(131322)
    assert N.weight_kg("131,322 KG") == 131322      # unchanged
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_normalize_languages.py -v`
Expected: the Chinese `canon` test and the tonnes test FAIL.

- [ ] **Step 3: Implement**

In `sdoc/core/normalize.py`, replace `_TONNES` and `canon`:

```python
# Tonnes as written in English, Malay ("tan", "tan metrik") and Chinese.
# The Chinese units are matched without word boundaries: Chinese has no
# spaces, so \b never falls around them.
_TONNES = re.compile(r"\b(MT|MTS|TONNES?|TONS?|TAN)\b|吨|公吨|噸")


def canon(value: str) -> str:
    """Uppercase, punctuation to spaces, single-spaced.

    Letters of every script are kept: an A-Z-only version erased Chinese
    names entirely and reported them as blanks."""
    return " ".join(re.sub(r"[\W_]+", " ", value.upper()).split())
```

- [ ] **Step 4: Run the new tests and the whole suite**

Run: `python -m pytest tests/test_normalize_languages.py -v` then `python -m pytest -q`
Expected: all pass. The existing English normalisation and comparison tests are unchanged.

---

### Task 2: A field matches when the originals match or the English forms match

**Files:**
- Modify: `sdoc/core/compare.py`
- Test: `tests/test_compare_languages.py` (new)

**Interfaces:**
- Consumes: `normalize.canon`, `port_key`, `count_value`, `weight_kg` (Task 1).
- Produces: `compare(si: ShipmentFields, bl: ShipmentFields, si_en: ShipmentFields | None = None, bl_en: ShipmentFields | None = None) -> Comparison`; `Row(name, si, bl, match, si_en=None, bl_en=None)`.

- [ ] **Step 1: Write the failing tests**

```python
from sdoc.core.compare import compare
from sdoc.core.fields import FIELDS, ShipmentFields


def fields(**kw):
    base = dict(shipper="MALAYSIA PAPER SDN BHD", consignee="HANOI TRADING CO", notify_party="SAME AS CONSIGNEE",
                port_of_loading="PORT KLANG, MALAYSIA", port_of_discharge="HAIPHONG, VIETNAM",
                container_count="3 x 40'HC", gross_weight_kg="61,250 KG")
    base.update(kw)
    return ShipmentFields(**base)


def test_a_chinese_si_and_an_english_bl_match_through_the_english_forms():
    si = fields(port_of_loading="巴生港, 马来西亚", container_count="三个40尺高柜", gross_weight_kg="61.25 公吨")
    bl = fields()
    result = compare(si, bl, si_en=fields(), bl_en=fields())
    assert result.defects == [] and result.missing == []
    row = next(r for r in result.rows if r.name == "port_of_loading")
    assert row.si == "巴生港, 马来西亚" and row.si_en == "PORT KLANG, MALAYSIA" and row.match is True


def test_a_real_difference_is_still_a_defect_in_both_forms():
    si = fields(container_count="三个40尺高柜")
    bl = fields(container_count="5 x 40'HC")
    result = compare(si, bl, si_en=fields(container_count="3 x 40'HC"), bl_en=fields(container_count="5 x 40'HC"))
    assert result.defects == ["container_count"]


def test_without_english_forms_the_comparison_is_exactly_as_before():
    """Results saved before this change have no English forms."""
    result = compare(fields(container_count="3 x 40'HC"), fields(container_count="5 x 40'HC"))
    assert result.defects == ["container_count"]
    assert all(r.si_en is None and r.bl_en is None for r in result.rows)


def test_blank_is_decided_on_the_original():
    """An English form cannot invent a value the document does not have."""
    si = fields(gross_weight_kg="____ KG")
    result = compare(si, fields(), si_en=fields(), bl_en=fields())
    assert result.missing == ["gross_weight_kg"]


def test_two_chinese_documents_compare_as_written():
    si = fields(shipper="马来西亚纸业有限公司")
    bl = fields(shipper="马来西亚纸业有限公司")
    assert compare(si, bl).defects == []
    assert compare(si, fields(shipper="越南纸业有限公司")).defects == ["shipper"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_compare_languages.py -v`
Expected: FAIL — `compare()` takes 2 positional arguments; `Row` has no `si_en`.

- [ ] **Step 3: Implement** — replace the bottom of `sdoc/core/compare.py` from `@dataclass class Row` onward:

```python
@dataclass
class Row:
    name: str
    si: str | None
    bl: str | None
    match: bool | None          # None = one side blank, could not compare
    si_en: str | None = None    # the English form, when the AI gave one
    bl_en: str | None = None


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


def _same(name: str, a: str | None, b: str | None) -> bool:
    ka, kb = _key(name, a), _key(name, b)
    return ka is not None and kb is not None and _equal(name, a, b, ka, kb)


def compare(si: ShipmentFields, bl: ShipmentFields,
            si_en: ShipmentFields | None = None,
            bl_en: ShipmentFields | None = None) -> Comparison:
    """A field matches if the values match as written, or - when the
    documents are in different languages - if their English forms match.
    It is a defect only when both fail. Blank is decided on the original:
    an English form cannot invent a value the document does not have."""
    rows, missing, defects = [], [], []
    for name in FIELDS:
        a, b = getattr(si, name), getattr(bl, name)
        a_en = getattr(si_en, name) if si_en else None
        b_en = getattr(bl_en, name) if bl_en else None
        if _key(name, a) is None or _key(name, b) is None:
            missing.append(name)
            rows.append(Row(name, a, b, None, a_en, b_en))
            continue
        ok = _same(name, a, b) or _same(name, a_en, b_en)
        rows.append(Row(name, a, b, ok, a_en, b_en))
        if not ok:
            defects.append(name)
    return Comparison(rows, missing, defects)
```

- [ ] **Step 4: Run the new tests and the whole suite**

Run: `python -m pytest tests/test_compare_languages.py -v` then `python -m pytest -q`
Expected: all pass.

---

### Task 3: The extractor returns an English form of every value

**Files:**
- Modify: `sdoc/ai/extract_pair.py`, `sdoc/pipeline.py:82`
- Test: `tests/test_extract_languages.py` (new); modify the helper in `tests/test_pipeline.py:31`

**Interfaces:**
- Consumes: `compare(si, bl, si_en, bl_en)` (Task 2).
- Produces: `PairExtraction(si_doc_type, bl_doc_type, si, bl, si_en, bl_en)` — `si_en`/`bl_en` are required `ShipmentFields` (required so the structured output always fills them).

- [ ] **Step 1: Write the failing tests**

```python
from sdoc.ai import extract_pair as X
from sdoc.core.fields import ShipmentFields
from sdoc import pipeline


def test_the_prompt_asks_for_an_english_form_from_each_document_alone():
    p = X.build_prompt("SI TEXT", "BL TEXT")
    assert "si_en" in p and "bl_en" in p
    assert "already in English" in p and "copy it exactly" in p
    assert "never from the other document" in p


def test_the_schema_requires_the_english_forms():
    required = X.PairExtraction.model_json_schema()["required"]
    assert "si_en" in required and "bl_en" in required


def test_the_pipeline_compares_with_the_english_forms(monkeypatch, tmp_path):
    full = dict(shipper="A SDN BHD", consignee="B CO", notify_party="B CO", port_of_loading="PORT KLANG",
                port_of_discharge="HAIPHONG", container_count="3 x 40'HC", gross_weight_kg="61,250 KG")
    si = ShipmentFields(**{**full, "port_of_loading": "巴生港"})
    bl = ShipmentFields(**full)
    pair = X.PairExtraction(si_doc_type="SHIPPING_INSTRUCTION", bl_doc_type="BILL_OF_LADING",
                            si=si, bl=bl, si_en=ShipmentFields(**full), bl_en=ShipmentFields(**full))
    monkeypatch.setattr(pipeline, "extract_pair", lambda a, b: pair)
    doc = type("Doc", (), {"readable": True, "text": "x", "path": "p", "problem": None})
    monkeypatch.setattr(pipeline, "read_document", lambda path: doc)
    r = pipeline.process({"attachments": ["x_SI.txt", "x_BL.txt"]},
                         {"category": "BL_COMPARISON", "reason": "check"})
    assert r["status"] == "OK"
    pol = next(f for f in r["fields"] if f["name"] == "port_of_loading")
    assert pol["si"] == "巴生港" and pol["si_en"] == "PORT KLANG"
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_extract_languages.py -v`
Expected: FAIL — no `si_en` in prompt or schema.

- [ ] **Step 3: Implement**

In `sdoc/ai/extract_pair.py`, add to `PairExtraction`:

```python
class PairExtraction(BaseModel):
    si_doc_type: DocType
    bl_doc_type: DocType
    si: ShipmentFields
    bl: ShipmentFields
    # The same seven values in English, each from its own document - so a
    # Chinese SI can be checked against an English BL (巴生港 vs PORT KLANG).
    si_en: ShipmentFields
    bl_en: ShipmentFields
```

In `PROMPT`, insert this block after the `Labels differ between documents …` paragraph:

```
The documents may be written in English, Malay or Chinese, or a mix.

3. Also give si_en and bl_en: the same seven fields in English, for comparing
   documents written in different languages.
   - Write each from its own document only - never from the other document.
   - If a value is already in English, copy it exactly, character for
     character, even if it looks misspelled.
   - Otherwise translate or romanise it as it would appear on an English
     shipping document: 巴生港 -> PORT KLANG, 三个40尺高柜 -> 3 x 40'HC,
     61.25 公吨 -> 61,250 KG, Pelabuhan Klang -> PORT KLANG.
   - Null wherever the original value is null.
```

In `sdoc/pipeline.py` line 82:

```python
    result = compare(pair.si, pair.bl, pair.si_en, pair.bl_en)
```

In `tests/test_pipeline.py` line 31, the helper builds `PairExtraction(...)`; add `si_en=si, bl_en=bl` (the same objects as `si` and `bl`) to that call so the English documents in those tests keep behaving as before.

- [ ] **Step 4: Run the new tests and the whole suite**

Run: `python -m pytest tests/test_extract_languages.py tests/test_pipeline.py -v` then `python -m pytest -q`
Expected: all pass.

---

### Task 4: The classifier is told emails may be in Malay or Chinese

**Files:**
- Modify: `sdoc/ai/classify.py:41-44`
- Test: `tests/test_classify_languages.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from sdoc.ai.classify import build_prompt


def test_the_classifier_reads_malay_and_chinese_on_meaning():
    p = build_prompt({"from": "a@b.my", "subject": "Draf BL", "body": "Sila semak draf BL", "attachments": []})
    assert "English, Malay or Chinese" in p
    assert "Sila semak draf BL" in p          # the email goes in as written, untranslated
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_classify_languages.py -v` → FAIL.

- [ ] **Step 3: Implement** — in `PROMPT`, after the paragraph ending `what is the sender asking the recipient to DO next?`, add:

```
Emails may be written in English, Malay or Chinese, or mix them. Classify on
meaning whatever the language: "Sila sediakan SI" (Malay) and "请制作提单"
(Chinese) are requests to prepare documents; "Sila semak draf BL" and
"请核对提单草稿" ask for a check. The categories and the reason stay in English.
```

- [ ] **Step 4: Run** — `python -m pytest -q` → all pass.

---

### Task 5: The comparison table shows the English beside a non-English value

**Files:**
- Modify: `sdoc/web/templates/email.html` (the `cmp-table` rows)
- Test: `tests/test_web.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_a_non_english_value_shows_its_english_form(site):
    client, write = site
    write({"email_043": {
        "category": "BL_COMPARISON", "reason": "x", "status": "OK", "review_reason": None,
        "has_defect": False, "defect_fields": [], "note": None,
        "fields": [{"name": "port_of_loading", "si": "巴生港", "bl": "PORT KLANG", "match": True,
                    "si_en": "PORT KLANG", "bl_en": "PORT KLANG"}],
    }})
    html = client.get("/email/email_043").text
    assert '巴生港<span class="en">PORT KLANG</span>' in html
    assert 'PORT KLANG<span class="en">' not in html        # English already: nothing added
```

- [ ] **Step 2: Run** — `python -m pytest tests/test_web.py -k english_form -v` → FAIL.

- [ ] **Step 3: Implement** — in `email.html` replace the SI and BL cells:

```html
          <td class="si" data-l="SI" translate="no">{{ f.si if f.si is not none else '(blank)' }}
            {%- if f.si_en and f.si_en != f.si %}<span class="en">{{ f.si_en }}</span>{% endif %}</td>
          <td class="bl" data-l="BL" translate="no">{{ f.bl if f.bl is not none else '(blank)' }}
            {%- if f.bl_en and f.bl_en != f.bl %}<span class="en">{{ f.bl_en }}</span>{% endif %}</td>
```

and add to the `<style>` block:

```css
  /* The English form under a value written in another language. */
  .cmp-table td .en { display:block; margin-top:2px; font-size:11px; color:var(--fg-subtle); }
```

- [ ] **Step 4: Run** — `python -m pytest -q` → all pass.

---

### Task 6: The i18n core — languages, `t()`, the switch route, `<html lang>`

**Files:**
- Create: `sdoc/web/i18n.py`, `sdoc/web/translations.json`
- Modify: `sdoc/web/app.py` (middleware after `sign_in_wall`, `OPEN` check, `/lang` route, Jinja globals), `sdoc/web/templates/base.html` and `_terminal.html` (`<html lang>`, font stacks)
- Test: `tests/test_i18n.py` (new)

**Interfaces:**
- Produces: `i18n.LANGS: dict[str, str]` (`{"en": "EN", "ms": "BM", "zh": "中文"}`), `i18n.HTML_LANG`, `i18n.COOKIE = "mailops-lang"`, `i18n.pick(cookie, accept_language) -> str`, `i18n.use(lang) -> Token`, `i18n.reset(token)`, `i18n.current() -> str`, `i18n.t(text, **values) -> str`, `i18n.strings(*texts) -> dict[str, str]`, `i18n.MISSES: set[tuple[str, str]]`. Jinja globals: `t`, `lang` (call as `lang()`), `LANGS`, `HTML_LANG`, `js_strings`.

- [ ] **Step 1: Write the failing tests** (`tests/test_i18n.py`)

```python
import pytest
from fastapi.testclient import TestClient

from sdoc.web import app as web
from sdoc.web import i18n


@pytest.mark.parametrize("cookie,accept,want", [
    ("zh", "en-US,en", "zh"),                  # a saved choice wins
    (None, "zh-CN,zh;q=0.9,en;q=0.8", "zh"),
    (None, "ms-MY,ms;q=0.9", "ms"),
    (None, "fr-FR,de", "en"),                 # nothing we have: English
    ("xx", None, "en"),                       # a bad cookie is ignored
])
def test_the_language_is_the_saved_choice_then_the_browsers(cookie, accept, want):
    assert i18n.pick(cookie, accept) == want


def test_t_translates_formats_and_records_what_is_missing(monkeypatch):
    monkeypatch.setattr(i18n, "TABLE", {"{n} emails": {"ms": "{n} e-mel", "zh": "{n} 封邮件"}})
    i18n.MISSES.clear()
    token = i18n.use("zh")
    try:
        assert i18n.t("{n} emails", n=3) == "3 封邮件"
        assert i18n.t("Not in the table") == "Not in the table"     # English, never a key
        assert ("zh", "Not in the table") in i18n.MISSES
    finally:
        i18n.reset(token)
    assert i18n.t("{n} emails", n=3) == "3 emails"                  # back to English


def test_the_switch_saves_the_choice_and_returns_to_the_page():
    client = TestClient(web.app)
    r = client.get("/lang/zh?next=/tests", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/tests"
    assert "mailops-lang=zh" in r.headers["set-cookie"]
    assert client.get("/lang/xx", follow_redirects=False).status_code == 404
    assert client.get("/lang/ms?next=//evil.com", follow_redirects=False).headers["location"] == "/"


def test_the_switch_works_before_signing_in(monkeypatch):
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "1")
    r = TestClient(web.app).get("/lang/ms?next=/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_the_page_declares_its_language():
    client = TestClient(web.app)
    assert '<html lang="en">' in client.get("/tests").text
    client.cookies.set("mailops-lang", "zh")
    assert '<html lang="zh-Hans">' in client.get("/tests").text
    assert '<html lang="zh-Hans">' in client.get("/login").text
```

- [ ] **Step 2: Run** — `python -m pytest tests/test_i18n.py -v` → FAIL (no module `i18n`).

- [ ] **Step 3: Implement `sdoc/web/i18n.py`**

```python
"""The website in English, Malay and Chinese.

One table, keyed by the English sentence as it appears in the templates, so
a template stays readable and a sentence with no translation yet shows in
English rather than as a key. Emails, category and field codes, and the
AI's notes are data and are never translated.
"""
import contextvars
import json
from pathlib import Path

LANGS = {"en": "EN", "ms": "BM", "zh": "中文"}          # code -> label on the switch
HTML_LANG = {"en": "en", "ms": "ms", "zh": "zh-Hans"}
DEFAULT = "en"
COOKIE = "mailops-lang"
TABLE: dict[str, dict[str, str]] = json.loads(
    (Path(__file__).parent / "translations.json").read_text(encoding="utf-8"))

_current = contextvars.ContextVar("mailops_lang", default=DEFAULT)
# Sentences asked for in Malay or Chinese with no translation. The tests
# render every page in both and require this to stay empty.
MISSES: set[tuple[str, str]] = set()


def pick(cookie: str | None, accept_language: str | None) -> str:
    """The saved choice, else the browser's first language we have, else English."""
    if cookie in LANGS:
        return cookie
    for part in (accept_language or "").split(","):
        base = part.split(";")[0].strip().lower().split("-")[0]
        if base in LANGS:
            return base
    return DEFAULT


def use(lang: str) -> contextvars.Token:
    return _current.set(lang if lang in LANGS else DEFAULT)


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> str:
    return _current.get()


def t(text: str, **values) -> str:
    lang = _current.get()
    out = text
    if lang != DEFAULT:
        entry = TABLE.get(text) or {}
        if entry.get(lang):
            out = entry[lang]
        else:
            MISSES.add((lang, text))
    return out.format(**values) if values else out


def strings(*texts: str) -> dict[str, str]:
    """For page scripts: each sentence in the current language, with any
    {placeholders} left for the script to fill."""
    return {s: t(s) for s in texts}
```

`sdoc/web/translations.json` starts as `{}`.

- [ ] **Step 4: Wire it into `sdoc/web/app.py`**

Import: `from sdoc.web import auth, checks, i18n, watcher`.

In `sign_in_wall`, extend the condition:

```python
    if (auth.require_login() and path not in OPEN_PATHS
            and not path.startswith("/lang/")
            and not auth.current_user(request)):
```

Directly after `sign_in_wall`, add:

```python
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
    if code not in i18n.LANGS:
        raise HTTPException(status_code=404, detail="unknown language")
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(i18n.COOKIE, code, max_age=365 * 24 * 3600, samesite="lax")
    return response
```

After `templates = Jinja2Templates(...)`:

```python
templates.env.globals.update(t=i18n.t, lang=i18n.current, LANGS=i18n.LANGS,
                             HTML_LANG=i18n.HTML_LANG, js_strings=i18n.strings)
```

- [ ] **Step 5: `<html lang>` and fonts** — in `base.html` and `_terminal.html` change `<html lang="en">` to `<html lang="{{ HTML_LANG[lang()] }}">`. In `base.html` `:root` append CJK fallbacks:

```css
  --sans:"Fira Sans",ui-sans-serif,system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,"PingFang SC","Microsoft YaHei",monospace;
```

Apply the same two fallbacks to the font variables in `_terminal.html`.

- [ ] **Step 6: Run** — `python -m pytest tests/test_i18n.py -v` then `python -m pytest -q` → all pass.

---

### Task 7: The language switch in the header and on the sign-in pages

**Files:**
- Modify: `sdoc/web/templates/base.html` (`.head-right`, CSS), `sdoc/web/templates/_terminal.html` (`.status-right`, CSS)
- Test: `tests/test_i18n.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_every_page_offers_the_three_languages_and_marks_the_current_one():
    client = TestClient(web.app)
    client.cookies.set("mailops-lang", "ms")
    for path in ("/", "/tests", "/login"):
        html = client.get(path).text
        nav = html.split('<nav class="langs"', 1)[1].split("</nav>", 1)[0]
        assert 'href="/lang/en?next=' in nav and 'href="/lang/zh?next=' in nav
        assert '<a aria-current="true" href="/lang/ms?next=' in nav
        assert ">BM<" in nav and ">中文<" in nav
```

- [ ] **Step 2: Run** — FAIL (no `nav.langs`).

- [ ] **Step 3: Implement.** In `base.html`, inside `.head-right` before the theme toggle's `<span class="vr"></span>`:

```html
    {% set here = request.url.path ~ ('?' ~ request.url.query if request.url.query else '') %}
    <nav class="langs" aria-label="{{ t('Language') }}">
      {%- for code, label in LANGS.items() %}
      <a {% if code == lang() %}aria-current="true" {% endif %}href="/lang/{{ code }}?next={{ here|urlencode }}" lang="{{ HTML_LANG[code] }}">{{ label }}</a>
      {%- endfor %}
    </nav>
```

CSS in `base.html` (near `.iconbtn`):

```css
/* Language: three short links, the current one filled. Links, not a menu:
   one tap, no script, and each is labelled in its own language. */
.langs { display:inline-flex; border:1px solid var(--border-strong); border-radius:var(--r-ctl); overflow:hidden; }
.langs a { height:26px; padding:0 7px; display:inline-flex; align-items:center;
           font-size:11px; font-weight:600; color:var(--fg-muted); }
.langs a + a { border-left:1px solid var(--border-strong); }
.langs a:hover { background:var(--l2); color:var(--fg); }
.langs a[aria-current="true"] { background:var(--primary); color:var(--on-primary); }
```

In `_terminal.html`, put the same `<nav class="langs">` block first inside `.status-right`, and the same CSS (the terminal page defines its own `--border-strong`, `--primary`, `--on-primary`, `--l2`, `--fg` tokens; reuse them).

Add the `Language` sentence to `translations.json`: `"Language": {"ms": "Bahasa", "zh": "语言"}`.

- [ ] **Step 4: Run** — `python -m pytest -q` → all pass. Check the phone header still fits: Task 12's screenshots.

---

### Task 8: Translate the app shell, Triage Queue, Overview and email view

**Files:**
- Modify: `sdoc/web/templates/base.html`, `inbox.html`, `dashboard.html`, `email.html`, `sdoc/web/translations.json`
- Test: `tests/test_i18n.py` (append: the untranslated-text check and page tests)

**Interfaces:**
- Consumes: `t`, `js_strings`, `MISSES` (Task 6).
- Produces: `untranslated(html_en: str, html_other: str) -> list[str]` in `tests/test_i18n.py`, reused by Tasks 9 and 10.

- [ ] **Step 1: Write the check and the failing page tests** (append to `tests/test_i18n.py`)

```python
import json
import re

# Regions that hold data, not interface text: never compared.
_SKIP = re.compile(
    r"<(style|script|code|pre|kbd)\b.*?</\1>"
    r"|<(\w+)\b[^>]*\btranslate=\"no\"[^>]*>.*?</\2>", re.S)
# A word of English prose: "Overview", "total", "Sender:". Codes are not
# prose - SPAM and OK are uppercase, container_count and email_004 carry an
# underscore, addresses an @ - and neither is the brand, MailOps.
_PROSE = re.compile(r"\(?[A-Za-z][a-z]{2,}[,.:;!?)…]*")
_ATTRS = re.compile(r'\s(?:placeholder|title|aria-label|alt)="([^"]*)"')


def _visible(html: str) -> set[str]:
    body = _SKIP.sub(" ", html)
    chunks = [" ".join(c.split()) for c in re.split(r"<[^>]+>", body)]
    chunks += [" ".join(a.split()) for a in _ATTRS.findall(body)]
    return {c for c in chunks if any(_PROSE.fullmatch(w) for w in c.split())}


def untranslated(html_en: str, html_other: str) -> list[str]:
    """English prose that reads the same in the other language: text nobody
    wrapped in t(). Elements holding data carry translate="no" and are
    skipped - keep those elements leaf-level (no same-tag nesting inside)."""
    return sorted(_visible(html_en) & _visible(html_other))


RESULTS = {
    "email_001": {"category": "BL_COMPARISON", "reason": "x", "status": "OK", "review_reason": None,
                  "has_defect": False, "defect_fields": [], "note": "No mismatch detected.", "fields": []},
    "email_004": {"category": "BL_COMPARISON", "reason": "Sender asks for a check", "status": "MISMATCH",
                  "review_reason": None, "has_defect": True, "defect_fields": ["container_count"], "note": None,
                  "fields": [{"name": "container_count", "si": "3 x 20'GP", "bl": "5 x 20'GP", "match": False}]},
    "email_002": {"category": "INVOICE_QUERY", "reason": "About an invoice", "status": "OK"},
}


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUT_DIR", tmp_path)
    (tmp_path / "results.json").write_text(json.dumps(RESULTS), encoding="utf-8")
    return TestClient(web.app)


def render(client, path, lang):
    client.cookies.set("mailops-lang", lang)
    return client.get(path).text


@pytest.mark.parametrize("path", ["/", "/?category=BL_COMPARISON&status=MISMATCH",
                                  "/dashboard", "/email/email_004", "/email/email_002"])
@pytest.mark.parametrize("lang", ["ms", "zh"])
def test_the_queue_overview_and_email_pages_are_fully_translated(site, path, lang):
    i18n.MISSES.clear()
    en, other = render(site, path, "en"), render(site, path, lang)
    assert untranslated(en, other) == []
    assert {m for m in i18n.MISSES if m[0] == lang} == set()
```

- [ ] **Step 2: Run** — `python -m pytest tests/test_i18n.py -k fully_translated -v` → FAIL, listing every English sentence on those pages.

- [ ] **Step 3: Implement — work through the failure list page by page:**
  - Wrap every visible sentence and every `placeholder`/`title`/`aria-label`/`alt` in `{{ t("…") }}`. Numbers go in placeholders: `{{ t("{n} of {total}", n=position, total=total) }}`. Singular and plural are separate English sentences: `t("{n} email")` / `t("{n} emails")`.
  - Mark data `translate="no"`: inbox `td.subject` and `td.from`; the email page `h1`, `.meta`, `.why`, `.cmp-note`, file names `.nm`; dashboard bar labels are codes (single tokens, not flagged) — leave them.
  - Leave codes as they are: category and status chips, field names.
  - Scripts in `base.html` (`Expand panel` / `Collapse panel`) and `email.html` (`save failed`): emit `var T = {{ js_strings("Expand panel", "Collapse panel")|tojson }};` and use `T["Expand panel"]`.
  - Add every sentence to `translations.json` with Malay (`ms`) and Simplified Chinese (`zh`). Keep the operational tone of the English; shipping terms stay recognisable to Malaysian staff (SI, BL, draft BL stay as written; "Shipping Instruction" / "Bill of Lading" may stay English in Malay).
- [ ] **Step 4: Run** — `python -m pytest tests/test_i18n.py -v` then `python -m pytest -q` → all pass.

---

### Task 9: Translate the Send and Test results pages, scripts included

**Files:**
- Modify: `sdoc/web/templates/compose.html`, `tests.html`, `sdoc/web/app.py` (`compose_submit` error details), `sdoc/web/translations.json`
- Test: `tests/test_i18n.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("lang", ["ms", "zh"])
@pytest.mark.parametrize("path", ["/compose", "/tests"])
def test_send_and_test_results_are_fully_translated(site, path, lang):
    i18n.MISSES.clear()
    en, other = render(site, path, "en"), render(site, path, lang)
    assert untranslated(en, other) == []
    assert {m for m in i18n.MISSES if m[0] == lang} == set()


def test_the_run_checks_script_gets_its_sentences_in_the_page_language(site):
    html = render(site, "/tests", "zh")
    # base.html's panel script has its own T; find the Run checks one.
    tables = [json.loads(part.split(";\n", 1)[0]) for part in html.split("var T = ")[1:]]
    strings = next(s for s in tables if "All checks passed" in s)
    assert strings["All checks passed"] != "All checks passed"
    assert "{n}" in strings["{n} of {total} finished"]        # placeholders survive for the script
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement.**
  - Wrap page text as in Task 8. The results section (hero, tiles, panels, caveat, reviewer note) is server-rendered: wrap it too.
  - In `tests.html`'s script, replace every English literal with a lookup through `T`, and every concatenated sentence with a placeholder sentence filled by a helper:

```javascript
  var T = {{ js_strings(
    "Run live checks", "Running…", "Run again", "checking…", "starting the test suite…",
    "{n} of {total} finished", "{n} of {total} passed", "{n} of {total} passed in {s} s",
    "{total} of {expected} graded emails", "{n} missing", "{n} that are not graded emails",
    "({n} from the live mailbox)", "{n} invalid, e.g. {problem}", "every field valid",
    "no live mail mixed in", "no saved scorer output - run the scorer locally to produce out/score.json",
    "the saved {pct}% score belongs to this submission: same emails, categories and escalations",
    "the saved score is from a different submission ({which} differ) - re-run the scorer",
    "Running the checks…", "Live on this server. Each square below is one test, lit as it passes.",
    "One square per test, lit the moment it passes on the server", "could not run",
    "The checks could not run", "The server stopped the run.", "the run did not finish",
    "All checks passed", "Some checks failed", "Ran on this server at {time}.",
    "The test suite took {s} seconds.", "Every square is a test that passed",
    "Red squares are tests that failed", "{n} / {total} passed", "Test {n}: {state}",
    "passed", "failed", "skipped",
    "Accuracy is the organizers' scorer's result. It needs the answer key, which is deliberately not on this server - what ran here proves the saved score belongs to this submission.",
    "These results are from a run that finished seconds ago; a fresh one can start in {s}s.",
    "Not started: {reason}.", "the server refused", "Could not reach the server - try again."
  )|tojson }};
  function tr(s, vars) {
    var out = T[s] || s;
    for (var k in vars || {}) out = out.split("{" + k + "}").join(vars[k]);
    return out;
  }
```

    Rewrite each place the script builds a sentence to call `tr(...)` with these keys (for example `step("tests", "active", tr("{n} of {total} finished", {n: run.lit, total: total || "…"}))`). Every key used must be in the `js_strings` list and in `translations.json`.
  - `compose.html`'s script hints (`… is over N MB`, `… files can be attached`): same pattern with their own `T`.
  - In `compose_submit`, wrap each `HTTPException` detail: `detail=i18n.t("Not an email address: {to}", to=to)`, `i18n.t("A subject is required")`, `i18n.t("At most {n} attachments", n=MAX_ATTACHMENTS)`, `i18n.t("{name} is too large (limit {mb} MB)", name=f.filename, mb=…)`, `i18n.t("Sign in to send mail")`. Update any test that asserts these exact English strings to the new sentence case.
- [ ] **Step 4: Run** — `python -m pytest -q` → all pass.

---

### Task 10: Translate sign-in, register, and the account messages

**Files:**
- Modify: `sdoc/web/templates/_terminal.html`, `login.html`, `register.html`, `sdoc/web/auth.py:106-152`, `sdoc/web/app.py` (login/register `error=` strings), `sdoc/web/translations.json`
- Test: `tests/test_i18n.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("lang", ["ms", "zh"])
@pytest.mark.parametrize("path", ["/login", "/register"])
def test_sign_in_and_register_are_fully_translated(path, lang):
    client = TestClient(web.app)
    i18n.MISSES.clear()
    en, other = render(client, path, "en"), render(client, path, lang)
    assert untranslated(en, other) == []
    assert {m for m in i18n.MISSES if m[0] == lang} == set()


def test_account_errors_come_back_in_the_page_language(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUT_DIR", tmp_path)
    client = TestClient(web.app)
    client.cookies.set("mailops-lang", "zh")
    i18n.MISSES.clear()
    # Also send the audit-policy checkbox under the name register.html gives
    # it: the route checks that before the password, and this test is about
    # the password message.
    html = client.post("/register", data={"name": "A", "email": "a@b.co", "desk": "",
                                          "password": "short", "confirm": "short"}).text
    assert {m for m in i18n.MISSES if m[0] == "zh"} == set()
    assert "password needs" not in html.lower()
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement.**
  - Wrap page text in the three templates as in Task 8. The decorative codes on the sign-in design (`SECURE_AUTH // PORT:443`, `OPS_GATEWAY`, `LOC_ID: ROTTERDAM-EU04`, `12H TTL`) are uppercase codes and stay; sentences around them are translated.
  - `register.html` / `login.html` scripts (`Passwords match`, `Passwords do not match yet`, `Show password`, `Hide password`): `var T = {{ js_strings(...)|tojson }}` as in Task 8.
  - `auth.py`: import `from sdoc.web.i18n import t`; `password_problems` returns `t("at least {n} characters", n=MIN_PASSWORD)`, `t("an uppercase letter")`, `t("a number")`, `t("a symbol")`; `create_user` raises `ValueError(t("Your name is required."))`, `t("That does not look like an email address.")`, `t("The password needs {items}.", items=", ".join(problems))`, `t("The two passwords do not match.")`, `t("Pick a desk from the list.")`, `t("An account with that email already exists.")`.
  - `app.py`: `error=i18n.t("That email and password do not match an account.")`, `i18n.t("That access code is not right.")`, `i18n.t("You need to acknowledge the audit logging policy.")`.
  - Update existing tests that assert the old lowercase English messages to the new sentences.
- [ ] **Step 4: Run** — `python -m pytest -q` → all pass, including every Task 8–10 page test in both languages.

---

### Task 11: Six Malay and Chinese test emails, run through the real pipeline

**Files:**
- Create: `demo/multilang/cases.json`, the email bodies and documents listed below, `demo/multilang/README.md`, `tools/multilang_check.py`
- Test: `tests/test_multilang_demo.py` (new, free: checks the files are consistent — no API)

- [ ] **Step 1: Write the demo files.** Bodies are written the way a real Malaysian shipper or clerk would write them; documents follow the layout of `demo/SI.txt` / `demo/BL.txt` (labels and values), in the stated language.

| id | body file | language | attachments | expect |
|---|---|---|---|---|
| ms_si_request | `ms_si_request.txt` | Malay: asks for an SI to be prepared, shipment details in the body | none | SI_REQUEST, OK |
| zh_check_ok | `zh_check.txt` | Chinese: asks for the draft BL to be checked against the SI | `zh_SI.txt` (Chinese labels and values: 巴生港, 三个40尺高柜, 61.25 公吨), `en_BL.txt` (English, same shipment) | BL_COMPARISON, OK |
| zh_check_mismatch | `zh_check.txt` | same | `zh_SI.txt`, `wrong_BL.txt` (English, 5 x 40'HC) | BL_COMPARISON, MISMATCH, [container_count] |
| ms_check_ok | `ms_check.txt` | Malay: asks for a check | `ms_SI.txt` (Malay labels: Pengirim, Pelabuhan Muat; weight in "tan metrik"), `ms_en_BL.txt` (English, same shipment) | BL_COMPARISON, OK |
| ms_invoice | `ms_invoice.txt` | Malay: question about an invoice / local charges | none | INVOICE_QUERY, OK |
| zh_spam | `zh_spam.txt` | Chinese: prize scam | none | SPAM, OK |

File names keep `_SI.` / `_BL.` so the pipeline assigns them (`wrong_BL.txt`, not `en_BL_wrong.txt`). `cases.json`:

```json
[
  {"id": "ms_si_request", "from": "kerani@kilangkertas.com.my", "subject": "Permohonan SI - PO 7781",
   "body": "ms_si_request.txt", "attachments": [], "expect": {"category": "SI_REQUEST", "status": "OK"}},
  {"id": "zh_check_ok", "from": "docs@huaxinpaper.com.my", "subject": "请核对提单草稿 - 订单 5521",
   "body": "zh_check.txt", "attachments": ["zh_SI.txt", "en_BL.txt"],
   "expect": {"category": "BL_COMPARISON", "status": "OK"}},
  {"id": "zh_check_mismatch", "from": "docs@huaxinpaper.com.my", "subject": "请核对提单草稿 - 订单 5521",
   "body": "zh_check.txt", "attachments": ["zh_SI.txt", "wrong_BL.txt"],
   "expect": {"category": "BL_COMPARISON", "status": "MISMATCH", "defect_fields": ["container_count"]}},
  {"id": "ms_check_ok", "from": "operasi@kertasutara.com.my", "subject": "Sila semak draf BL - PO 6620",
   "body": "ms_check.txt", "attachments": ["ms_SI.txt", "ms_en_BL.txt"],
   "expect": {"category": "BL_COMPARISON", "status": "OK"}},
  {"id": "ms_invoice", "from": "akaun@kilangkertas.com.my", "subject": "Pertanyaan invois caj tempatan",
   "body": "ms_invoice.txt", "attachments": [], "expect": {"category": "INVOICE_QUERY", "status": "OK"}},
  {"id": "zh_spam", "from": "prize@lucky-draw.top", "subject": "恭喜您中奖了！",
   "body": "zh_spam.txt", "attachments": [], "expect": {"category": "SPAM", "status": "OK"}}
]
```

- [ ] **Step 2: A free consistency test** (`tests/test_multilang_demo.py`)

```python
import json
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "demo" / "multilang"


def test_every_demo_case_points_at_real_files_the_pipeline_can_assign():
    cases = json.loads((DEMO / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 6
    for c in cases:
        assert (DEMO / c["body"]).exists(), c["id"]
        for name in c["attachments"]:
            assert (DEMO / name).exists(), name
        if c["attachments"]:
            assert any("_SI." in n.upper() for n in c["attachments"])
            assert any("_BL." in n.upper() for n in c["attachments"])


def test_the_mismatch_pair_differs_only_in_the_container_count():
    ok, wrong = (DEMO / "en_BL.txt").read_text(encoding="utf-8"), (DEMO / "wrong_BL.txt").read_text(encoding="utf-8")
    diff = [(a, b) for a, b in zip(ok.splitlines(), wrong.splitlines()) if a != b]
    assert len(diff) == 1 and "40'HC" in diff[0][1]
```

- [ ] **Step 3: The paid runner** (`tools/multilang_check.py`)

```python
"""Run the Malay and Chinese demo emails through the real pipeline - the
same ingest() the mailbox watcher uses - and say whether each came out as
expected. Costs about 10 cents of API credit. Uses throwaway folders, so
nothing lands in the real mail/ or out/.

    python tools/multilang_check.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "multilang"
SCRATCH = Path(tempfile.mkdtemp(prefix="mailops-multilang-"))
os.environ["SDOC_MAIL"] = str(SCRATCH / "mail")
os.environ["SDOC_OUT"] = str(SCRATCH / "out")
os.environ["SDOC_CACHE"] = str(SCRATCH / "cache")      # a real call, not a cached answer
sys.path.insert(0, str(ROOT))

from sdoc.ingest import ingest            # noqa: E402  (after the folders are set)
from sdoc.mail.store import save_email    # noqa: E402


def main() -> int:
    cases = json.loads((DEMO / "cases.json").read_text(encoding="utf-8"))
    failures = 0
    for c in cases:
        files = [(n, (DEMO / n).read_bytes()) for n in c["attachments"]]
        body = (DEMO / c["body"]).read_text(encoding="utf-8")
        email = save_email(c["from"], c["subject"], body, files, root=SCRATCH / "mail")
        r = ingest(email, SCRATCH / "out")
        want = c["expect"]
        got_fields = sorted(r.get("defect_fields") or [])
        ok = (r["category"] == want["category"] and r["status"] == want["status"]
              and got_fields == sorted(want.get("defect_fields", [])))
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {c['id']:<18} {r['category']:<14} {r['status']:<12} "
              f"{','.join(got_fields) or '-':<16} {r.get('reason', '')}")
        if r.get("fields"):
            for f in r["fields"]:
                print(f"      {f['name']:<18} {str(f['si']):<28} {str(f['bl']):<28} en: {f.get('si_en')} | {f.get('bl_en')}")
    print(f"\n{len(cases) - failures} of {len(cases)} as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the free test** — `python -m pytest tests/test_multilang_demo.py -v` → PASS.
- [ ] **Step 5: With the owner's go-ahead only** — `python tools/multilang_check.py` → expect `6 of 6 as expected`. If a case fails, read the printed fields and reason, fix the cause (prompt wording, normalisation), add a free test for it, and re-run only after asking again.

---

### Task 12: Look at it, then ship

- [ ] **Step 1 (owner's go-ahead):** start a local server with the watcher and API key off, on a throwaway copy of `out/`. Screenshot in BM and 中文, desktop 1366×860 and phone 390×844: Triage Queue, Overview, an email with a comparison, Send, Test results (after a run), sign-in, register. Check the phone header fits the language switch, and no page scrolls sideways. Close the browser and stop the server.
- [ ] **Step 2:** `python -m pytest -q` → all pass.
- [ ] **Step 3 (owner's go-ahead):** one commit as CHUO JESSE (no co-author lines) with the code, tests, demo files, spec and this plan; push; wait for Railway; check the live site in BM and 中文.
