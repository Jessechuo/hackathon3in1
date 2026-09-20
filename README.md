# SDOC — Shipping Document Verification

**Live: [hackathon3in1.up.railway.app](https://hackathon3in1.up.railway.app)** ·
send it a real email at **hackathon3in1@gmail.com** and watch it get triaged

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
| ✅ Document reading | txt, xlsx, docx, pdf; scanned or broken files flagged as unreadable |
| ✅ Field comparison + escalation | Claude reads both documents, Python decides; the four review reasons |
| ✅ Comparison report in the UI | SI and BL side by side, status filter, overview dashboard |
| ✅ Human review loop | A reviewer's Mark Verified / Flag Mismatch becomes the final answer in the app: the email leaves the review queue, the report says what the system had said, and `submission.json` stays the system's own answers |
| ✅ Live mailbox | Email `hackathon3in1@gmail.com` and it is classified and compared within 20 seconds |
| ✅ Sending, with the documents checked first | Send from the app and the attachments are compared before the message leaves |
| ✅ Accounts | Sign in to send; reading stays open so nobody is blocked from looking |
| ✅ Deployed | One process serves the UI and polls the mailbox |
| 🚧 Vision for scanned PDFs | Deferred — those emails escalate to a human either way |

Scanned PDFs are not OCR'd yet: they go straight to human review as
`unreadable`, which is also what the brief asks for when a document cannot
be read dependably.

---

## Requirements

- **Python 3.11+** (developed on 3.13)
- **An Anthropic API key** — needed to classify and compare. The web UI and the
  whole test suite run without one.

The dataset is included, so the UI has something to show the moment you start it.

## Install

```bash
git clone https://github.com/Jessechuo/hackathon3in1.git
cd hackathon3in1
python -m pip install -r requirements.txt
```

## The dataset

The organizers' bundle ships with the repo, so a fresh clone has data:

```
hackathon3in1/
├── sdoc/
├── tests/
└── sdoc-hackathon-bundle/
    ├── inbox/                 520 email_XXX.json files
    └── attachments/           250 SI/BL files
```

Check it resolved:

```bash
python -c "from sdoc.inbox import load_emails; print(len(load_emails()), 'emails')"
# 520 emails
```

Keeping it elsewhere? Point at it instead:

```bash
export SDOC_BUNDLE=/path/to/sdoc-hackathon-bundle     # macOS / Linux / Git Bash
$env:SDOC_BUNDLE="C:\path\to\sdoc-hackathon-bundle"   # PowerShell
```

The answer key is **not** here and never will be. `sdoc-hackathon-docker/`
holds `ground_truth.json` and is gitignored; nothing under `sdoc/` reads it.

---

## Run the web UI

No API key needed.

```bash
python -m uvicorn sdoc.web.app:app --reload --port 8000
```

Open **http://localhost:8000**

- **Overview** (`/dashboard`, top icon in the left rail) — total emails,
  mismatches, needs review and human decisions as clickable cards, plus emails
  per category and the most commonly mismatched fields
- **Inbox** — all 520 emails, dense triage grid, category and verification columns
- **Click a subject** — full email, metadata, attachments
- **Click an attachment** — the raw SI or BL content
- **Mark Verified / Flag Mismatch** (document-check emails only) — record a
  person's decision; Flag Mismatch asks which of the seven fields are wrong.
  Decided emails leave the Review queue and appear under **Reviewed**
- **Send an email** (`/compose`, paper-plane icon) — send a real message from the
  watched account, with its attachments checked first. See [Mail in and out](#mail-in-and-out)
- `/` search · `J`/`K` navigate · `Enter` open · `Esc` back · theme toggle top-right

Category and verification columns stay empty until the classifier has run; a
notice bar in the UI says so.

> **Port already in use?** `WinError 10013` or `Address already in use` means
> something else has the port. Use another (`--port 8001`), or find the culprit
> with `netstat -ano | findstr :8000` (Windows) / `lsof -i :8000` (macOS/Linux).

## Run the classifier

Needs an API key. Get one at [console.anthropic.com](https://console.anthropic.com)
and add credit. Classification runs on Claude Haiku, so a full run over 520
emails costs roughly **$0.70**.

Put it in a `.env` file next to the code — gitignored, loaded automatically,
and you never have to export anything again:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Or export it for the current shell only:

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
python -m sdoc.run_classify --only email_119,email_506   # just these emails
python -m sdoc.run_classify --workers 4      # fewer parallel requests
```

`--only` and `--limit` update `out/categories.json` rather than replacing it,
so testing a prompt change on a handful of emails never loses the rest.

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

## Mail in and out

Everything that moves through the app — arriving or leaving — goes through the
same classify-and-compare the graded run uses. There is no second code path.

### Mail arriving

The watcher polls a Gmail inbox over IMAP:

```bash
python -m sdoc.run_watch                   # poll every 20 seconds
python -m sdoc.run_watch --once            # one pass, then stop
python -m sdoc.run_watch --interval 60     # poll once a minute
```

It needs two variables, which live in `.env` or `.env.txt` (both gitignored,
both loaded automatically):

```
SDOC_MAIL_USER=hackathon3in1@gmail.com
SDOC_MAIL_PASSWORD=abcdefghijklmnop
```

Gmail needs an **App Password**, not the account password: turn on 2-Step
Verification, then create one at
[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
and strip the spaces Google displays.

Messages are marked read as they are taken, so nothing is processed — or
billed — twice. IMAP is an outbound connection only, so this needs no domain,
no public URL and no DNS records, and behaves the same on a laptop as on a
server.

### Mail leaving

**Send an email** in the left rail (`/compose`) sends a real message from the
watched account. The attached documents are **checked before it goes out** — a
discrepancy is worth catching before a draft leaves, not after the customer
finds it. The sent message is stored alongside received mail with its own
category and verdict, marked `TO` in the queue.

**Sending needs an account.** Reading the queue does not — anyone with the link
sees everything, which is deliberate: a login wall in front of a demo just
stops people looking. But a message leaves under the shipping desk's own
address, so that needs an identity.

Sign in at `/login`. Create the first account at `/register`, which needs a
one-time signup code:

```
SDOC_SIGNUP_CODE=something-only-you-know
SDOC_SECRET_KEY=a-long-random-string      # or sessions reset on every deploy
```

Both matter. This app runs on a public URL: open signup plus the ability to
send is an open relay wearing a hat — a stranger registers, then mails the
world from your account until Google suspends it. With no code configured,
registration is closed and the form says so.

Passwords are stored as salted scrypt hashes in `out/users.json`, which is
gitignored. Set `SDOC_REQUIRE_LOGIN=1` if you want reading to need an account
too.

> Keep attachment contents above ~50 characters. Below that the reader
> correctly reports "almost no readable text" — the same gate that catches
> scanned PDFs — and the email escalates instead of being compared.

### Where it all lives

Received and sent mail are kept apart from the organizers' data on purpose:

| | |
|---|---|
| `mail/inbox/mail_NNNN.json` | mail received and sent |
| `mail/attachments/` | their files |
| `out/mail_results.json` | their categories and verdicts |

`sdoc-hackathon-bundle/` is never written to, and `out/submission.json` keeps
exactly the 520 graded ids — a stray id there would invalidate the submission.
`mail/` is gitignored; it is local state, like `out/` and `.cache/`.

## Score a submission

`run_pipeline` already writes `out/submission.json`. To score classification
alone, before the comparison has run:

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

218 tests, no API key required, no network. Every LLM call is replaced by a test
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
| `SDOC_MAIL` | `./mail` | Where received mail is stored |
| `ANTHROPIC_API_KEY` | — | Required to run the classifier and the comparison |
| `SDOC_MAIL_USER` | — | Gmail address the watcher polls |
| `SDOC_MAIL_PASSWORD` | — | Gmail App Password for that address |
| `SDOC_SIGNUP_CODE` | — | Code required to create an account; unset means registration is closed |
| `SDOC_SECRET_KEY` | generated | Signs session cookies; unset means sign-ins reset on restart |
| `SDOC_REQUIRE_LOGIN` | `0` | Set to `1` to require an account for reading too |
| `SDOC_WATCH` | `1` | Set to `0` to stop the app polling the mailbox |

The last three are read from `.env` or `.env.txt` if present — both are
gitignored, and `sdoc/config.py` loads them before anything reads the
environment, so nothing has to be exported by hand. A real environment
variable always wins over the file, which is what a deploy needs.

Models are chosen per task in `sdoc/config.py`:

```python
CLASSIFY_MODEL = "claude-haiku-4-5"   # easy, high-volume step
EXTRACT_MODEL  = "claude-opus-5"      # hard step that decides the field-match score
VISION_MODEL   = "claude-opus-5"      # scanned PDFs
```

Cost of a full classification run: ~$3.53 on Opus (measured), ~$0.70 on Haiku
(estimated from pricing — Haiku is 5× cheaper per token).
Changing a model changes the cache key, so the next run re-calls the API.

## Layout

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
├── mail/
│   ├── store.py       writing a received email to disk
│   ├── parse.py       RFC 822 bytes -> sender, subject, body, files
│   ├── send.py        SMTP out, behind a passphrase
│   └── gmail.py       IMAP; the only file that talks to a mail server
├── pipeline.py        the checks, in order -> one decision per email
├── ingest.py          one received email -> classified, compared, saved
├── run_classify.py    CLI: classify the inbox
├── run_pipeline.py    CLI: check the documents
├── run_watch.py       CLI: watch a mailbox
└── web/               FastAPI + Jinja templates
    ├── auth.py        accounts, scrypt hashes, sessions
    └── watcher.py     runs the mailbox poll inside the web process
tools/
├── make_submission.py categories.json -> submission.json
└── diff_errors.py     which emails did we get wrong? (dev tool)
tests/                 mirrors the sdoc/ layout — 218 tests, no API key needed
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
