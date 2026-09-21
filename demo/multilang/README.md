# Malay and Chinese test emails

Six emails that show MailOps accepting mail written in Malay and Chinese as it
is - nothing is translated - and still sorting and comparing it correctly.
`cases.json` lists each one and the result expected.

| Email | Language | Attachments | Expected |
|---|---|---|---|
| `ms_si_request.txt` - asks for an SI to be prepared | Malay | none | SI_REQUEST |
| `zh_check.txt` - asks for the draft BL to be checked | Chinese | `zh_SI.txt` + `en_BL.txt` | BL_COMPARISON, OK |
| `zh_check.txt` - the same request | Chinese | `zh_SI.txt` + `wrong_BL.txt` | BL_COMPARISON, MISMATCH (container_count) |
| `ms_check.txt` - asks for a check | Malay | `ms_SI.txt` + `ms_en_BL.txt` | BL_COMPARISON, OK |
| `ms_invoice.txt` - a local-charges invoice question | Malay | none | INVOICE_QUERY |
| `zh_spam.txt` - a prize scam | Chinese | none | SPAM |

The SIs are in Chinese and Malay and the BLs in English, the usual mix: the
shipper writes the SI, the shipping line issues the BL. The pairs differ in
language only - 巴生港 is PORT KLANG, Singapura is SINGAPORE, 三个40尺高柜 is
3 x 40'HC, 61.25 公吨 and 38.5 tan metrik are 61,250 and 38,500 KG - except
`wrong_BL.txt`, which carries 5 containers instead of 3.

**Run them through the real pipeline** (about 10 cents of API credit, in
throwaway folders):

    python tools/multilang_check.py

**Or send one to the live inbox:** email it to the MailOps address with the
subject from `cases.json`, the body file pasted in, and its attachments.
