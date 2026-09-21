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
    # The same seven values in English, each from its own document - so a
    # Chinese SI can be checked against an English BL (巴生港 vs PORT KLANG).
    si_en: ShipmentFields
    bl_en: ShipmentFields


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
