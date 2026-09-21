"""Turn raw field values into comparable forms. Pure functions.

The rules are fitted to how values actually appear in the bundle:
counts are "6 x 40'HC", weights "131,058 KG", ports "CALLAO, PERU (PECLL)".
The only irregular values are the deliberate blanks: "N/A", "____MT", "".
"""
import re

_PLACEHOLDER_WORDS = {"TBA", "TBC", "TBD", "N/A", "NA", "NIL", "NONE", "UNKNOWN", "-"}
_PLACEHOLDER_CHARS = re.compile(r"[\s_?\-.*/]+")
# Tonnes as written in English, Malay ("tan", "tan metrik") and Chinese.
# The Chinese units are matched without word boundaries: Chinese has no
# spaces, so \b never falls around them.
_TONNES = re.compile(r"\b(MT|MTS|TONNES?|TONS?|TAN)\b|吨|公吨|噸")

# A shorter party name only matches a longer one that starts with it when it
# is at least this long — "APRIL" must not match "APRIL FAR EAST ...".
_MIN_PREFIX = 12


def is_blank(value: str | None) -> bool:
    if value is None:
        return True
    s = value.strip().upper()
    return not s or s in _PLACEHOLDER_WORDS or bool(_PLACEHOLDER_CHARS.fullmatch(s))


def canon(value: str) -> str:
    """Uppercase, punctuation to spaces, single-spaced.

    Letters of every script are kept: an A-Z-only version erased Chinese
    names entirely and reported them as blanks."""
    return " ".join(re.sub(r"[\W_]+", " ", value.upper()).split())


def port_key(value: str) -> str:
    """Port name without bracketed codes. Compare names, never codes:
    email_013 keeps the code (KEMBA) while the port itself changes."""
    return canon(re.sub(r"\([^)]*\)", " ", value))


def count_value(value: str) -> int | None:
    m = re.search(r"(\d+)\s*[xX×]", value)
    if m:
        return int(m.group(1))
    m = re.search(r"\d+", value)
    return int(m.group(0)) if m else None


def weight_kg(value: str) -> float | None:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", value)
    if not m:
        return None
    n = float(m.group(0).replace(",", ""))
    if _TONNES.search(value.upper()):
        n *= 1000
    return n


def same_party(a: str, b: str) -> bool:
    ka, kb = canon(a), canon(b)
    if ka == kb:
        return True
    short, long_ = sorted((ka, kb), key=len)
    return len(short) >= _MIN_PREFIX and long_.startswith(short + " ")
