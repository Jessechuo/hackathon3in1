# Malay and Chinese: accepting the mail, and a website in three languages

Date: 2026-09-21. Agreed in chat with the project owner.

## Goals

1. **MailOps accepts emails and SI/BL documents written in Malay or Chinese**
   (or English, or a mix) and sorts and compares them correctly. Nothing is
   translated for its own sake: an email is stored and shown exactly as it
   was written.
2. **The website can be used in English, Malay (BM) or Chinese (中文).**

Out of scope: translating existing emails; re-running the organizers' Docker
scorer (the 520 saved results do not change).

## Part A: accepting Malay and Chinese mail

### Sorting (classify.py)

The classifier reads meaning, not keywords, so it already understands Malay
and Chinese. The prompt gains one instruction: emails may be written in
English, Malay, Chinese or a mix; classify on meaning. Output is unchanged:
the five English category codes and a short English `reason`.

### Reading the documents (extract_pair.py)

Today the extractor returns the seven values exactly as written. It will also
return an **English form** of each value: `si_en` and `bl_en`, the same seven
fields.

Rules for the English form, stated in the prompt:
- Written from that document alone, never from the other document.
- A value already in English is copied exactly, so English documents behave
  exactly as today.
- Otherwise translated or romanised: 巴生港 → PORT KLANG, 三个40尺高柜 →
  3 x 40'HC, 131.3 公吨 → 131,300 KG.
- Null wherever the original is null.

### Comparing (compare.py)

A field **matches if the originals match, or if both English forms match**.
It is a defect only when both comparisons fail. So a Chinese SI against an
English BL (巴生港 vs PORT KLANG) matches, and a real difference
("3 x 20'GP" vs "5 x 20'GP") is still caught. Blank detection stays on the
originals. Results saved before this change have no English forms; the code
treats them as absent. `Row` gains `si_en` and `bl_en` for display.

### Normalising (normalize.py)

Two fixes needed whatever the language of the other document:
- `canon` keeps all letters and digits, not only A–Z/0–9. Today a Chinese
  company name normalises to an empty string and is reported as a blank.
- Tonnes are recognised in Chinese and Malay: 吨, 公吨, 噸, tan.

### Showing it (email.html)

The comparison table shows the original with the English form beside it when
the two differ: 巴生港 (PORT KLANG).

### What does not change

The 520 saved results, `out/submission.json` and the 1.0000 score. Only mail
processed after this change uses the new reading. A document check costs
about $0.028 instead of $0.024.

## Part B: the website in three languages

- **Switch:** a compact language menu (EN / BM / 中文) in the header, and in
  the top bar of the sign-in and register pages. `/lang/<code>` stores the
  choice in a cookie for a year and returns to the same page. It is reachable
  without signing in. With no cookie, the browser's `Accept-Language` decides.
- **Mechanism:** `sdoc/web/i18n.py` holds one table keyed by the English
  sentence, with the Malay and Chinese for each. Templates wrap text in
  `t("...")`; placeholders use `str.format`. A missing translation shows the
  English, never a key. The request's language is held in a context variable
  set by middleware. No new dependency.
- **Scripts:** pages with client-side text (Run checks, Send) receive their
  strings for the current language as a JSON object.
- **Server messages:** sign-up password rules, send errors and form errors go
  through `t()`.
- **Details:** `<html lang>` is `en`, `ms` or `zh-Hans`. Chinese is
  Simplified, as used in Malaysia. Font stacks gain CJK fallbacks (PingFang
  SC, Microsoft YaHei, Noto Sans SC).
- **Not translated:** category and field codes (they match the organizers'
  names, the submission and the scorer), email content, and the AI's short
  notes, which were written once in English when each email was processed.

## Testing

Free, in the test suite:
- Normalising: a Chinese name survives `canon`; 吨 and tan weights convert.
- Comparing: 巴生港 vs PORT KLANG matches through the English forms; a real
  difference is still a defect; the existing English tests pass unchanged.
- Prompts: the classifier mentions the three languages; the extractor asks
  for English forms.
- Website: every page renders in all three languages; no page has text
  without a Malay or Chinese translation (`t()` records misses); `/lang/`
  sets the cookie; `Accept-Language` picks the first-visit language.
- Screenshots of the pages in BM and 中文, desktop and phone.

End to end with the real AI (paid, about 10 cents, run only with the owner's
go-ahead). Six test emails in `demo/multilang/`, run through the same
`ingest()` path the mailbox watcher uses:

| Email | Language | Expected |
|---|---|---|
| Asks for an SI to be prepared from shipment details | Malay | SI_REQUEST |
| Asks for the draft BL to be checked; Chinese SI + matching English BL | Chinese | BL_COMPARISON, OK |
| Same pair, BL has a different container count | Chinese | BL_COMPARISON, MISMATCH (container_count) |
| Asks for a check; Malay SI with weight in tan + matching English BL | Malay | BL_COMPARISON, OK |
| Asks about an invoice | Malay | INVOICE_QUERY |
| A prize scam | Chinese | SPAM |

The same files stay in `demo/multilang/` so they can be sent to the live
inbox during the demo.
