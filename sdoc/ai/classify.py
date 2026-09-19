"""Email -> one of five categories. Owns the classification prompt."""
from typing import Literal

from pydantic import BaseModel

from sdoc.ai.client import call_structured
from sdoc.config import CLASSIFY_MODEL

CATEGORIES = ["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]


class Classification(BaseModel):
    category: Literal["BL_COMPARISON", "SI_REQUEST", "INVOICE_QUERY", "GENERAL", "SPAM"]
    reason: str


PROMPT = """You are triaging a shipping operations inbox.

Classify this email into exactly one category.

BL_COMPARISON  Someone is asking for a draft Bill of Lading to be CHECKED or
               COMPARED against a Shipping Instruction, or asking for the draft
               BL to be sent so it can be checked. This stays BL_COMPARISON
               even when the attached files are the wrong type (e.g. a packing
               list instead of the BL) or are missing: the request is still a
               check, and the attachment problem is handled later.
SI_REQUEST     Someone is PROVIDING shipment details and asking that a Shipping
               Instruction or a draft BL be PREPARED from them.
INVOICE_QUERY  About invoices, billing, GR postings, local charges, D&D,
               freight amounts, or cancelling an invoice.
GENERAL        Operational updates, berthing reports, outstanding-BL lists,
               automated notifications, reminders, HR or company announcements.
SPAM           Marketing, phishing, prize scams, unsolicited offers.

Important: subject lines are unreliable and often misleading. Almost every
email in this inbox mentions "SI" or "draft BL" somewhere, so those phrases
carry no information. Decide on INTENT - what is the sender asking the
recipient to DO next?

  "make me a BL from these details"   -> SI_REQUEST
  "check this BL against the SI"      -> BL_COMPARISON
  "send me the draft BL for checking" -> BL_COMPARISON
  "confirm the BL is in order" (wrong file attached) -> BL_COMPARISON

From: {sender}
Subject: {subject}
Body:
{body}

Give the category and a short reason (under 15 words)."""


def build_prompt(email: dict) -> str:
    return PROMPT.format(
        sender=email["from"],
        subject=email["subject"],
        body=email["body"],
    )


def classify(email: dict) -> Classification:
    return call_structured(build_prompt(email), Classification, CLASSIFY_MODEL)
