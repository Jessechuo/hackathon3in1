# Shipping Document Verification — Design

**Date:** 2026-09-19
**Hackathon:** SDOC — from email inbox to discrepancy report
**Time budget:** 2–3 days
**Deliverable:** `submission.json` for scoring + a live demo

---

## 1. The problem

A shipping operations inbox mixes five kinds of message. For each of 520 emails
the system must:

1. **Classify** it as `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`,
   or `SPAM`.
2. For `BL_COMPARISON` only — compare the Shipping Instruction (SI) against the
   draft Bill of Lading (BL) across seven fields, and report `OK`, `MISMATCH`
   (with the exact differing fields), or `NEEDS_REVIEW` (with a reason).

The SI is the source of truth. The BL is the draft being checked.

**The seven compared fields:** `shipper`, `consignee`, `notify_party`,
`port_of_loading`, `port_of_discharge`, `container_count`, `gross_weight_kg`.

### Scoring

```
final = 0.30 · stage1_macro_F1 + 0.20 · stage3_defect_F1 + 0.50 · end_to_end
```

- End-to-end requires an **exact set match** on `defect_fields`. Partial credit
  does not exist — flagging one of two bad fields scores the same as flagging none.
- Stage 1 is **macro**-F1, so SPAM (40 emails) weighs as much as BL_COMPARISON (220).
- `status` and `review_reason` do **not** enter `final_score`; they are graded on
  a separate reliability axis. They still matter — the brief weights human-in-the-loop
  behaviour explicitly, and the scoreboard "is not the final assessment".

### Dataset facts (verified)

```
520 emails   BL_COMPARISON 220 · SI_REQUEST 125 · INVOICE_QUERY 75 · GENERAL 60 · SPAM 40
             of the 220: 63 OK · 46 MISMATCH · 20 NEEDS_REVIEW · 91 no-attachment
250 files    192 .txt · 28 .pdf · 22 .xlsx · 8 .docx
defects      20 emails with 1 bad field · 26 with 2
escalations  5 each of wrong_doc_type / missing_attachment / unreadable / missing_value
```

Only `BL_COMPARISON` emails ever carry attachments.

---

## 2. Constraints and decisions

| Decision | Choice | Why |
|---|---|---|
| AI integration | Mandatory (organizer requirement) | Load-bearing, not decorative |
| Model | `claude-opus-5` throughout | One model, one code path; fewest bugs on a weekend clock |
| Budget | ~$20 top-up | Measured ~$0.0074/email; disk cache makes re-runs free |
| Web stack | FastAPI + server-rendered HTML | One language, no build step |
| Comparison logic | Deterministic Python, no AI | Protects the exact-match metric from run-to-run variance |

**Core principle: AI reads, code decides.** Claude handles classification,
field extraction, vision, and escalation reasoning. Plain Python decides whether
two values match.

---

## 3. Architecture

```
sdoc/
├── core/                  pure logic · no I/O · no network
│   ├── fields.py          ShipmentFields dataclass, the 7 canonical names
│   ├── normalize.py       weights, counts, names, ports → comparable form
│   └── compare.py         SI vs BL → match / mismatch / cannot-decide
├── extract/               file format → one common shape
│   ├── base.py            DocText dataclass + registry by extension
│   ├── text.py  excel.py  word.py  pdf.py
├── ai/
│   ├── config.py          model names — one place, so routing is a later one-liner
│   ├── client.py          Anthropic client + disk cache + retry
│   ├── classify.py        email → category (+ intent when no attachments)
│   ├── read_doc.py        DocText → ShipmentFields (structured outputs)
│   └── vision.py          scanned page images → ShipmentFields
├── pipeline.py            orchestration: email → EmailResult
├── run_batch.py           CLI → out/submission.json + out/results.json
└── web/
    ├── app.py             FastAPI
    └── templates/         inbox · email reader · report · review queue
```

**Dependencies point inward.** `extract/` knows file formats, not shipping.
`ai/` knows Claude, not the web layer. `core/` knows neither — pure functions over
dataclasses, testable with zero mocks and zero API calls. Only `pipeline.py` sees all three.

### The two carrying interfaces

```python
@dataclass
class DocText:                    # what every extractor returns
    raw_text: str
    pairs: list[tuple[str, str]]  # (label, value) when the format gives structure
    has_text_layer: bool          # False → route to vision
    source_path: str

@dataclass
class ShipmentFields:             # what every reader returns
    shipper: str | None
    consignee: str | None
    notify_party: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    container_count: str | None
    gross_weight_kg: str | None
```

Adding a format = one file in `extract/`. Swapping providers = one file in `ai/`.
Neither touches `core/`.

`pipeline.py` returns one `EmailResult` per email — category, status,
review_reason, has_defect, defect_fields, the seven compared rows, and an
optional error traceback. Its serialized shape is section 6.

---

## 4. Decision logic

Six gates, in this order. **Order is not negotiable** — each gate assumes the
previous passed, and the most specific failure must be reported first.

```
GATE 1  category?          not BL_COMPARISON → done, status = OK          (300)
GATE 2  attachments?       2 → continue
                           1 → NEEDS_REVIEW · missing_attachment
                           0 → ask Claude the intent:
                                 "send me the BL"      → OK                (91)
                                 "compare the attached" → NEEDS_REVIEW      (3)
GATE 3  readable?          empty/corrupt      → NEEDS_REVIEW · unreadable
                           no text layer      → vision, then review anyway
GATE 4  right doc type?    invoice/PL/COO     → NEEDS_REVIEW · wrong_doc_type
GATE 5  fields present?    blank/???/TBA/N/A  → NEEDS_REVIEW · missing_value
GATE 6  compare            all match → OK  |  any differ → MISMATCH + fields
```

### Why the order matters

A `wrong_doc_type` case (a Commercial Invoice where a BL was expected) has no
ports, no container count, no gross weight — so it would *also* trip Gate 5.
Checking Gate 5 first reports `missing_value`, which is the wrong reason and the
wrong evidence for the human reviewer. Gate 4 must come first.

### Gate 2 is the main trap

91 zero-attachment emails are correctly `OK`; 3 are `NEEDS_REVIEW`. Identical
attachment count — only the body distinguishes them:

| Body | Meaning | Verdict |
|---|---|---|
| "Please assist to **send** the draft BL for checking" | nothing was due yet | `OK` |
| "Please **compare** the SI and draft BL (attachments dropped)" | documents promised, missing | `NEEDS_REVIEW` |

A `if not attachments: escalate` rule produces 91 false escalations. Ask Claude
whether the sender expects documents to be attached already.

### Gate 3 — deliberate choice on scanned PDFs

3 emails are image-only PDFs. Decision: **run vision, extract, compare — and
still route to review** marked `unreadable`, with the OCR text as evidence.

Rationale: a legal shipping document OCR'd from a scan is inherently
lower-confidence, and a real operations team would want confirmation before the
BL is finalised. This demonstrates the vision capability *and* escalates
correctly, matching the brief's "send the case for review with the source
evidence and reason".

### Gate 6 — normalization

| Field | Rule | Example |
|---|---|---|
| `gross_weight_kg` | strip commas + units → number | `"21,577 KG"` = `"21577"` |
| `container_count` | leading integer | `"6 x 40'HC"` = `"6"` |
| names & ports | uppercase, collapse spaces, strip trailing punctuation | `"MOORIM SP CO., LTD"` → `MOORIM SP CO LTD` |

**Trap — do not compare on port codes.** `email_013`:

```
SI  port_of_discharge:  MOMBASA, KENYA (KEMBA)
BL  port_of_discharge:  TUTICORIN, INDIA (KEMBA)   ← same code, real defect
```

Compare the full normalized string.

**Near-miss escalation:** when two values differ after normalization but are
close, ask Claude whether they are the same entity written differently or
genuinely different parties. This is the brief's "distinguish a real discrepancy
from a reading or formatting issue". Rare in this dataset — real defects are
wholesale substitutions — but correct, and it demos well.

### Why classification cannot be keyword matching

```
Emails whose body contains "draft BL":   BL_COMPARISON 185 · SI_REQUEST 125 (all of them)
SI_REQUEST subjects containing "BL":     12
```

The phrase has zero discriminative power. What separates the categories is
**direction of request** — "make me a BL from this" vs "check this BL against
this SI" — which is a meaning question, not a word-presence question.

---

## 5. Data flow and failure handling

```
bundle/ → run_batch.py → out/results.json  → web/app.py  → browser
                       → out/submission.json → score_cli.py → score
```

`submission.json` is derived *from* `results.json` by dropping everything the
scorer doesn't need, so the two cannot drift apart.

### Disk cache

Key = `sha256(model | prompt | output_schema)`. Hit → return, $0, instant.

- Re-runs after logic changes cost nothing (prompts unchanged).
- A crash at email 347 doesn't lose the first 346 calls.
- The cache doubles as test fixtures — tests run offline, CI needs no key.

Hashing the schema means changing a Pydantic model correctly invalidates stale
entries that would no longer parse.

### Three layers of error handling

1. **Transient API failures** — `max_retries=4`; catch typed exceptions
   most-specific-first (`NotFoundError` → `RateLimitError` → `APIStatusError` →
   `APIConnectionError`). A single broad `except` loses the retryable/fatal distinction.
2. **Per-email isolation** — any unhandled exception yields an `EmailResult`
   with `status=NEEDS_REVIEW`, `review_reason=unreadable`, and the traceback
   retained for the UI. **The submission must contain all 520 keys**; a crash
   that drops emails is an invalid submission.
3. **Visible failures + retry** — the brief requires it.

### `NEEDS_REVIEW` vs `ERROR`

| | Meaning | Whose fault |
|---|---|---|
| `NEEDS_REVIEW` | system worked and **decided** it can't judge | nobody's — correct behaviour |
| `ERROR` | system **broke** | ours |

Track both internally and show them differently in the UI. `submission.json` has
no `ERROR` status, so an errored email degrades to `NEEDS_REVIEW` — the honest
mapping. Internal state is deliberately richer than the submission schema.

### Throughput

`ThreadPoolExecutor(max_workers=8)` → cold run ~5 minutes instead of ~35. Every
run after that is seconds, from cache. Dev flags: `--limit 50`, `--only email_043`.

Production would use the Batch API (half price, built for this) — a pitch line,
not weekend work.

---

## 6. Output formats

**`submission.json`** — exactly the five scored keys:

```json
"email_043": {
  "category": "BL_COMPARISON",
  "status": "MISMATCH",
  "review_reason": null,
  "has_defect": true,
  "defect_fields": ["container_count"]
}
```

**`results.json`** — all seven rows with both raw values, kept even when they match:

```json
"email_043": {
  "category": "BL_COMPARISON",
  "status": "MISMATCH",
  "fields": [
    {"name": "shipper",         "si": "ASIA PACIFIC…", "bl": "ASIA PACIFIC…", "match": true},
    {"name": "container_count", "si": "3 x 20'GP",     "bl": "5 x 20'GP",     "match": false}
  ],
  "error": null
}
```

Matching rows are retained because a reviewer needs to see that all seven were
checked, not only the one that failed. Raw values are stored, not normalized
ones — the normalized number decides, the original text is what a human reads.

The report renders only the differing rows (`container_count  SI: 3 / BL: 5`),
and `"No mismatch detected."` when all seven agree — the brief's exact wording.

---

## 7. Testing

`final_score` mixes three metrics and cannot tell you which stage is broken.
Read the stage breakdown the scorer already produces, then use a per-email diff
against `ground_truth.json` to turn "stage 3 is bad" into "these 14 emails are wrong."

| Layer | Approach | Why |
|---|---|---|
| `core/normalize.py`, `compare.py` | **TDD** | Pure functions, milliseconds, no key. Bugs here are silent — `"21,577 KG"` vs `21577` quietly costs points with no error. |
| `extract/` | Golden tests on real bundle files | `email_005_SI.xlsx` must yield container count `15` |
| `ai/` | Replay from the disk cache | Offline, no key |
| `pipeline.py` | One end-to-end on 50 emails | Assert 50 keys out, valid schema |
| `web/` | None | Not worth the hours |

**Integrity rule:** `ground_truth.json` is a scoreboard, never a lookup table.
No pipeline code may read it. Human error-analysis after scoring is intended and
expected; per-email tuning that memorizes this dataset is not — fix the
underlying rule, not the individual case.

---

## 8. Build sequence

```
DAY 1 am   email browser from the bundle alone (inbox list, reader,
           attachment viewer). Time-boxed to ~3 hrs. Leave empty holes for
           the category badge, status colour, and report panel.
DAY 1 pm   core/ + extract/text.py + ai/classify.py + the disk cache.
           Run on 50 emails. Get a first score on the board, however bad.
DAY 2      extract/excel.py, word.py, pdf.py + gates 2-5 + vision.
           Full 520 run → score → error-diff → fix → repeat.
           This is where the score is actually made.
DAY 3      Fill the UI holes: badges, discrepancy report, review queue.
           Pitch, cost analysis slide, rehearse the demo.
```

The email browser is built first because it needs only the bundle, and because
day-2 debugging requires reading individual emails and their attachments anyway.

After day 1 there is always a system that runs and scores — never a half-system.

---

## 9. Pitch notes

- **Cost economics.** $0.0074/email. At 2,000 emails/day: $261/month on a tiered
  setup, against roughly 5 FTE of manual checking. The AI is 1–4% of the labour
  it assists.
- **Production routing.** Haiku for high-volume classification, Opus for
  low-volume hard extraction — ~40% cheaper with no accuracy loss, because the
  downgraded step was never the hard part.
- **Reliability.** The system distinguishes "I cannot decide this" from "I
  crashed", and escalates the former with evidence and a reason.
