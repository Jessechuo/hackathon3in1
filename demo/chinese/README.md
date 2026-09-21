# A Chinese email to send to the live inbox

An email written entirely in Chinese, with a Chinese SI and a Chinese draft
BL. MailOps keeps it as written, sorts it as a document check, and compares
the two documents field by field.

The two documents match except for one deliberate difference - the SI says
**三个**40尺高柜 (3 containers), the BL **五个**40尺高柜 (5 containers) - so the
result to expect is:

**BL_COMPARISON · MISMATCH · container_count**

Every other field matches, even where the labels differ (发货人 on the SI,
托运人 on the BL): fields are matched by meaning, not by label.

## Sending it

From any mail account, send to **hackathon3in1@gmail.com**:

- **Subject:** `请核对提单草稿 - 订单 7788`
- **Body:** paste in the text of `email.txt`
- **Attachments:** `SI.txt` and `BL.txt` (keep the names - the letters SI and
  BL in them are how the two documents are told apart)

Within about half a minute it appears at the top of the Triage Queue. Open it
to see the comparison table: container_count is flagged, and each Chinese
value has its English form underneath.

For an **OK** result, and a Chinese SI checked against an English BL, use
`demo/multilang/`: `zh_check.txt` as the body with `zh_SI.txt` and `en_BL.txt`
attached (subject `请核对提单草稿 - 订单 5521`).
