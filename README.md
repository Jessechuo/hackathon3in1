# SDOC — Shipping Document Verification

Reads a shipping operations inbox, classifies each email, and for document-check
requests compares the Shipping Instruction (SI) against the draft Bill of Lading
(BL) to report any discrepancy — escalating to a human when it cannot decide.

Built for the SDOC hackathon: *from email inbox to discrepancy report.*

---

## What it does

For each of 520 emails:

1. **Classify** — `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, or `SPAM`
2. **Extract** — for comparison requests, pull seven fields from both attachments
3. **Compare** — report `OK`, `MISMATCH` (with the exact differing fields), or
   `NEEDS_REVIEW` (with a reason)

The seven compared fields: shipper, consignee, notify party, port of loading,
port of discharge, container count, gross weight (kg).

Claude reads the documents; plain Python decides whether the values match. That
keeps the exact-field-match scoring off a non-deterministic path while the LLM
handles what it is genuinely better at — messy labels, varied layouts, and
telling a real discrepancy apart from a formatting difference.

## Status

| | |
|---|---|
| ✅ Web inbox + email reader | Browse all 520 emails and their attachments |
| ✅ Email classifier | Claude-based, intent-driven rather than keyword matching |
| ✅ Disk-cached LLM client | Re-runs are free and instant |
| ✅ Batch runner + submission builder | All 520 classified, scored output produced |
| 🚧 Document extraction | txt / pdf / docx / xlsx — in progress |
| 🚧 Field comparison + escalation | In progress |
| 🚧 Human review queue | In progress |

Because comparison is not built yet, a submission currently reports every email
as `status: OK` with no defects. That scores the classification stage only.

---

## Requirements

- **Python 3.11+** (developed on 3.13)
- **The dataset** — see below. Not included in this repo.
- **An Anthropic API key** — only needed to run the classifier. The web UI and
  the whole test suite run without one.

## Install

```bash
git clone https://github.com/Jessechuo/hackathon3in1.git
cd hackathon3in1
python -m pip install -r requirements.txt
```

## Get the dataset

The organizers' data is **not** in this repo. Unzip the participant bundle so it
sits next to the code:

```
hackathon3in1/
├── sdoc/
├── tests/
└── sdoc-hackathon-bundle/     ← put it here
    ├── inbox/                 520 email_XXX.json files
    └── attachments/           250 SI/BL files
```

Somewhere else? Point at it instead:

```bash
export SDOC_BUNDLE=/path/to/sdoc-hackathon-bundle     # macOS / Linux / Git Bash
$env:SDOC_BUNDLE="C:\path\to\sdoc-hackathon-bundle"   # PowerShell
```

Check it resolved:

```bash
python -c "from sdoc.inbox import load_emails; print(len(load_emails()), 'emails')"
# 520 emails
```

---

## Run the web UI

No API key needed.

```bash
python -m uvicorn sdoc.web.app:app --reload --port 8000
```

Open **http://localhost:8000**

- **Inbox** — all 520 emails, dense triage grid, category and verification columns
- **Click a subject** — full email, metadata, attachments
- **Click an attachment** — the raw SI or BL content
- `/` search · `J`/`K` navigate · `Enter` open · `Esc` back · theme toggle top-right

Category and verification columns stay empty until the classifier has run; a
notice bar in the UI says so.

> **Port already in use?** `WinError 10013` or `Address already in use` means
> something else has the port. Use another (`--port 8001`), or find the culprit
> with `netstat -ano | findstr :8000` (Windows) / `lsof -i :8000` (macOS/Linux).

## Run the classifier

Needs an API key. Get one at [console.anthropic.com](https://console.anthropic.com)
and add credit — a full run over 520 emails costs roughly **$2**.

```bash
export ANTHROPIC_API_KEY=sk-ant-...          # macOS / Linux / Git Bash
$env:ANTHROPIC_API_KEY="sk-ant-..."          # PowerShell
```

Try it on a handful first:

```bash
python -m sdoc.run_classify --limit 20
```

Then the whole inbox:

```bash
python -m sdoc.run_classify
```

Writes `out/categories.json`. Takes about 4 minutes cold. **Run it again and it
finishes in seconds** — every response is cached on disk under `.cache/`, keyed
by model + prompt + output schema, so nothing is re-billed unless something
actually changed.

Reload the web UI and the category badges are populated.

### Options

```bash
python -m sdoc.run_classify --limit 50       # first 50 emails only
python -m sdoc.run_classify --workers 4      # fewer parallel requests
```

## Score a submission

```bash
python tools/make_submission.py              # out/categories.json -> out/submission.json
```

Then hand `out/submission.json` to the organizers' scorer, or POST it to their
server's `/submit` endpoint. Every one of the 520 ids is always present, even
for emails that failed to classify — a missing key is an invalid submission.

If you have the answer key, `tools/diff_errors.py` lists exactly which emails
were classified wrong so you can go read them:

```bash
python tools/diff_errors.py
python tools/diff_errors.py --ground-truth /path/to/ground_truth.json
```

It is a developer tool, not part of the pipeline. Nothing under `sdoc/` reads
ground truth.

> On Windows the scorer prints block characters and crashes on the default
> console encoding. Prefix it with `PYTHONIOENCODING=utf-8`, or run
> `$env:PYTHONIOENCODING="utf-8"` first in PowerShell.

## Run the tests

```bash
python -m pytest -v
```

22 tests, no API key required, no network. Every LLM call is replaced by a test
double, so the entire pipeline is verifiable offline.

---

## Configuration

Everything lives in [`sdoc/config.py`](sdoc/config.py) — one file, no model name
or path written anywhere else.

| Variable | Default | Purpose |
|---|---|---|
| `SDOC_BUNDLE` | `./sdoc-hackathon-bundle` | Where the dataset lives |
| `SDOC_OUT` | `./out` | Where results are written |
| `SDOC_CACHE` | `./.cache` | Where LLM responses are cached |
| `ANTHROPIC_API_KEY` | — | Required only to run the classifier |

To try a cheaper model, change one line in `sdoc/config.py`:

```python
CLASSIFY_MODEL = "claude-haiku-4-5"    # was claude-opus-5
```

## Layout

```
sdoc/
├── config.py          all paths and model names
├── inbox.py           reads the bundle — knows nothing about AI
├── ai/
│   ├── cache.py       content-addressed disk cache
│   ├── client.py      the only file that imports `anthropic`
│   └── classify.py    email -> category, owns the prompt
├── run_classify.py    CLI: fan classification across the inbox
└── web/               FastAPI + Jinja templates
tools/
├── make_submission.py categories.json -> submission.json
└── diff_errors.py     which emails did we get wrong? (dev tool)
tests/                 mirrors the sdoc/ layout — 22 tests, no API key needed
docs/superpowers/      design spec and implementation plan
design/                UI design system and mockups
```

Dependencies point inward. `ai/` knows Claude but not the web layer; `inbox.py`
knows files but not shipping; comparison logic is pure functions over
dataclasses. Adding a document format means one new file; swapping LLM providers
means one.

## Notes

- **`.cache/` is worth keeping.** It makes re-runs free and doubles as the test
  fixtures. It is gitignored — it is local state, not source.
- **Ground truth is a scoreboard, never a lookup table.** No file under `sdoc/`
  reads it. Use it after scoring to find which emails were wrong, then fix the
  underlying rule — never special-case an individual email.

## License

MIT
