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


# Counts written as words, before a measure word: 三个 / 十二个 (Chinese),
# dua kontena (Malay). Chinese has no spaces, so no word boundary there.
_ZH_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
_ZH_COUNT = re.compile(r"([一二两三四五六七八九十]+)\s*(?:个|只|支|柜|箱|[xX×])")
_MS_NUMBERS = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6,
               "tujuh": 7, "lapan": 8, "sembilan": 9, "sepuluh": 10}
_MS_COUNT = re.compile(r"\b(" + "|".join(_MS_NUMBERS) + r")\b\s*(?:\(\d+\)\s*)?(?:kontena|unit|buah|[xX×])",
                       re.IGNORECASE)
# A container SIZE - 40', 40尺, 40 kaki, 40ft - is never the count.
_SIZE = re.compile(r"\d+\s*(?:['’′]|尺|呎|ft\b|feet\b|foot\b|kaki\b)", re.IGNORECASE)


def _zh_number(s: str) -> int | None:
    """一 to 九十九: 三 = 3, 十二 = 12, 二十 = 20."""
    if "十" not in s:
        return _ZH_DIGITS.get(s)
    tens, _, ones = s.partition("十")
    return (_ZH_DIGITS.get(tens, 1) if tens else 1) * 10 + (_ZH_DIGITS.get(ones, 0) if ones else 0)


def count_value(value: str) -> int | None:
    """How many containers. "3 x 40'HC" = 3, and so are 三个40尺高柜 and
    tiga kontena 40 kaki - there the first number written is the 40, the
    container size, which read as the count hid a 3-versus-5 difference."""
    m = re.search(r"(\d+)\s*[xX×]", value)
    if m:
        return int(m.group(1))
    m = _ZH_COUNT.search(value)
    if m:
        return _zh_number(m.group(1))
    m = _MS_COUNT.search(value)
    if m:
        return _MS_NUMBERS[m.group(1).lower()]
    m = re.search(r"\d+", _SIZE.sub(" ", value))
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
