# Demo documents

A matched pair for showing the system working. Attach both to an email, or to
the app's compose form.

- **`SI.txt`** — Shipping Instruction, the customer's stated intent
- **`BL.txt`** — draft Bill of Lading, what the line actually drafted

## What the system should find

**MISMATCH on `container_count`** — the SI says `3 x 40'HC`, the BL says
`5 x 40'HC`. Everything else matches.

That is the only planted difference, so anything else reported is worth
investigating.

## The detail worth pointing at

| | SI says | BL says |
|---|---|---|
| Port of loading | `Port of Loading` | **`Load Port`** |
| Port of discharge | `Port of Discharge` | **`Discharge Port`** |

Different labels, same meaning, and both still match. That is the part a
keyword rule cannot do — the fields are aligned by what they mean, not by the
text of the header. Worth saying out loud during a demo, because it is easy to
miss and it is the whole argument for using a model here at all.

## Two ways to run it

**Receiving** — email both files to the watched address from any mail client,
or from the app's **Send an email** page addressed to that same watched address.
The watcher picks it up within twenty seconds.

It lands in the queue as `mail_NNNN`, classified
`BL_COMPARISON`, with the comparison table showing six matching fields and one
red one.

## Making a variant

Change one value in `BL.txt` and the system should report that field instead.
Useful for proving nothing is memorised: change it in front of whoever is
watching, and the answer follows.
