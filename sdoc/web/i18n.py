"""The website in English, Malay and Chinese.

One table, keyed by the English sentence as it appears in the templates, so
a template stays readable and a sentence with no translation yet shows in
English rather than as a key. Emails, category and field codes, and the
AI's notes are data and are never translated.
"""
import contextvars
import json
from pathlib import Path

LANGS = {"en": "EN", "ms": "BM", "zh": "中文"}          # code -> label on the switch
HTML_LANG = {"en": "en", "ms": "ms", "zh": "zh-Hans"}
DEFAULT = "en"
COOKIE = "mailops-lang"
TABLE: dict[str, dict[str, str]] = json.loads(
    (Path(__file__).parent / "translations.json").read_text(encoding="utf-8"))

_current = contextvars.ContextVar("mailops_lang", default=DEFAULT)
# Sentences asked for in Malay or Chinese with no translation. The tests
# render every page in both and require this to stay empty.
MISSES: set[tuple[str, str]] = set()


def pick(cookie: str | None, accept_language: str | None) -> str:
    """The saved choice, else the browser's first language we have, else English."""
    if cookie in LANGS:
        return cookie
    for part in (accept_language or "").split(","):
        base = part.split(";")[0].strip().lower().split("-")[0]
        if base in LANGS:
            return base
    return DEFAULT


def use(lang: str) -> contextvars.Token:
    return _current.set(lang if lang in LANGS else DEFAULT)


def reset(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> str:
    return _current.get()


def t(text: str, **values) -> str:
    lang = _current.get()
    out = text
    if lang != DEFAULT:
        entry = TABLE.get(text) or {}
        if entry.get(lang):
            out = entry[lang]
        else:
            MISSES.add((lang, text))
    return out.format(**values) if values else out


def strings(*texts: str) -> dict[str, str]:
    """For page scripts: each sentence in the current language, with any
    {placeholders} left for the script to fill."""
    return {s: t(s) for s in texts}
