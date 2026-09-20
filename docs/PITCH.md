# SDOC — pitch kit

Everything needed to present this: a spoken script, a demo running order, the
numbers, and answers to the questions judges actually ask.

- **Live:** https://hackathon3in1.up.railway.app
- **Code:** https://github.com/Jessechuo/hackathon3in1
- **Mailbox:** hackathon3in1@gmail.com

---

## The three-minute script

> **The problem.** A shipping line's documentation desk gets hundreds of emails
> a day. Buried in them is one job that has to be done perfectly: someone
> attaches a Shipping Instruction and a draft Bill of Lading, and a human reads
> both, line by line, checking seven fields match. Shipper, consignee, notify
> party, load port, discharge port, container count, gross weight.
>
> Miss one, and a wrong Bill of Lading goes out. That means amendment fees,
> cargo stuck at the port, and a customs problem that costs far more than the
> five minutes it would have taken to catch.
>
> **What we built.** SDOC reads the inbox, works out what each email is asking
> for, and for the ones that are document checks, it compares the two documents
> and reports the discrepancy — or says it cannot tell, and hands it to a person.
>
> **The design decision that matters.** AI reads, code decides. Claude extracts
> the values from the documents, because that is what it is genuinely better at
> — the SI says "Port of Loading", the BL says "Load Port", and it matches them
> by meaning. But the decision about whether two values match is plain Python.
> So the scored comparison never rides on a non-deterministic path. Run it
> twice, get the same answer twice.
>
> **The results.** All 520 emails classified correctly. 46 defects found, none
> missed, none invented. And 20 emails it refused to guess at — a missing
> attachment, a scanned page it could not read, the wrong kind of document
> entirely. Each escalated with a specific reason, and not one false alarm.
>
> That last number is the one I would care about if this were my desk. A tool
> that is confidently wrong is worse than no tool. This one knows the edge of
> what it knows.
>
> **The demo.** This is not a script that ran over a fixed dataset once. It is
> connected to a real mailbox right now. [*send the email*] I have just emailed
> it an SI and a draft BL where the container count differs — three versus five.
> Twenty seconds. There it is: mismatch, container count, three against five.
> Every other field matched, including the two ports that were labelled
> differently in each document.
>
> Nothing about that answer was looked up. That email did not exist a minute ago.
>
> **What it costs.** Two and a half cents per document check. At two thousand
> emails a day that is about five hundred dollars a month, against roughly nine
> people doing it by hand. The whole project cost under six dollars to build.

---

## Demo running order

Rehearse this. It is four minutes and it never needs the terminal.

| # | Do | Say |
|---|---|---|
| 1 | Open the live URL, sign in | "This is the operations desk's queue." |
| 2 | **Overview** — the cards | "520 emails. 46 mismatches. 20 it would not guess at." |
| 3 | Click **Mismatches** | "Every one of these has a named field that differs." |
| 4 | Open one | "SI on the left, BL on the right. Container count is red. Everything else matched." |
| 5 | Filter **Review** | "These are the ones it refused to answer, each with a reason." |
| 6 | Open one, hit **Mark Verified** | "A person's decision becomes the final answer. The report keeps what the system had said." |
| 7 | **Send the live email from a phone** | "Nothing here is hard-coded." |
| 8 | Refresh, open the new row | "Twenty seconds. Mismatch on container count." |

**Have a fallback.** If the venue's wifi misbehaves, step 7 dies. Open the app's
**Send an email** page instead — same pipeline, no network round trip to Gmail.

---

## The numbers

| | |
|---|---|
| Emails classified | **520 / 520** |
| Stage 1 macro F1 | **1.000** |
| Stage 3 defect F1 | **1.000** (precision 1.000, recall 1.000) |
| End-to-end | **46 / 46** |
| Escalations | **20**, each with a reason, **zero false alarms** |
| Final local score | **1.0000** |
| Tests | 229, no API key, no network |

**Category mix** — BL_COMPARISON 220 (42%), SI_REQUEST 125 (24%),
INVOICE_QUERY 75 (14%), GENERAL 60 (12%), SPAM 40 (8%).

**Escalation reasons** — 5 each of `wrong_doc_type`, `missing_attachment`,
`unreadable`, `missing_value`.

**Cost, measured not estimated**

| | |
|---|---|
| Classify one email (Haiku) | **$0.0013** |
| Check one document pair (Opus) | **$0.024** |
| Whole 520-email run | **~$3.30** |
| Entire project, start to finish | **~$5.70** |
| At 2,000 emails/day | **~$504/month** |

*The monthly figure assumes the same 42% document-check rate as this dataset,
22 working days, and no caching. Re-runs are free — every response is cached on
disk, keyed by model, prompt and schema.*

**The human comparison:** 846 checks a day at five minutes each is about 70
hours, roughly nine people. State the five-minute assumption out loud; a judge
who works in logistics will have their own number and will respect you for
naming yours.

---

## Say this before you are asked

**"The 1.0000 is not a held-out score."** It was scored against the same answer
key used to find the errors. Every fix was a general rule — never a special
case for an individual email — and no file under `sdoc/` can read the ground
truth. But it is not a clean test-set result, and saying so first is worth more
than being caught not saying it.

---

## Questions you will get

**"How do I know it is not just memorising the dataset?"**
Email it something new from your own phone. That is the entire answer, and it is
why the live mailbox is worth more than any slide.

**"What happens when it is wrong?"**
It escalates rather than guesses — 20 times here, with a specific reason each
time and no false alarms. And a reviewer's decision overrides it: Mark Verified
or Flag Mismatch updates the report and the email leaves the queue.

**"Why Claude and not a cheaper model?"**
Both. Classification is high-volume and easy, so it runs on Haiku at $0.0013 an
email. Document extraction decides the score, so it runs on Opus. One line in
`config.py` chooses each; nothing else in the codebase names a model.

**"Why not just use regex or keyword rules?"**
Because the SI says "Port of Loading" and the BL says "Load Port", and the next
customer's template says something else again. Rules break on the fourth format.
But note what the LLM is *not* doing: it never decides whether two values match.
That is Python.

**"What does not work yet?"**
Scanned PDFs with no text layer. They are detected and escalated as `unreadable`
rather than guessed at, which is what the brief asks for — but OCR would turn
those 5 escalations into answers.

**"Could this run on our mailbox on Monday?"**
The connector is already IMAP, so it is a credential change, not a rebuild. What
would need real work is storage — accounts and results are files today, which is
fine for one desk and not for a company.

---

## If you only remember three lines

1. **AI reads, code decides.** The LLM extracts; Python judges. The scored
   comparison is deterministic.
2. **It knows when it does not know.** 20 escalations, each with a reason, zero
   false alarms.
3. **Email it right now.** Nothing is hard-coded, and that is provable in twenty
   seconds.
