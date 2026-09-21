import pytest
from fastapi.testclient import TestClient

from sdoc.web import app as web
from sdoc.web import i18n


# --- choosing the language -------------------------------------------------

@pytest.mark.parametrize("cookie,accept,want", [
    ("zh", "en-US,en", "zh"),                  # a saved choice wins
    (None, "zh-CN,zh;q=0.9,en;q=0.8", "zh"),
    (None, "ms-MY,ms;q=0.9", "ms"),
    (None, "fr-FR,de", "en"),                 # nothing we have: English
    ("xx", None, "en"),                       # a bad cookie is ignored
])
def test_the_language_is_the_saved_choice_then_the_browsers(cookie, accept, want):
    assert i18n.pick(cookie, accept) == want


def test_t_translates_formats_and_records_what_is_missing(monkeypatch):
    monkeypatch.setattr(i18n, "TABLE", {"{n} emails": {"ms": "{n} e-mel", "zh": "{n} 封邮件"}})
    i18n.MISSES.clear()
    token = i18n.use("zh")
    try:
        assert i18n.t("{n} emails", n=3) == "3 封邮件"
        assert i18n.t("Not in the table") == "Not in the table"     # English, never a key
        assert ("zh", "Not in the table") in i18n.MISSES
    finally:
        i18n.reset(token)
    assert i18n.t("{n} emails", n=3) == "3 emails"                  # back to English


def test_the_switch_saves_the_choice_and_returns_to_the_page():
    client = TestClient(web.app)
    r = client.get("/lang/zh?next=/tests", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/tests"
    assert "mailops-lang=zh" in r.headers["set-cookie"]
    assert client.get("/lang/xx", follow_redirects=False).status_code == 404
    assert client.get("/lang/ms?next=//evil.com", follow_redirects=False).headers["location"] == "/"


def test_the_switch_works_before_signing_in(monkeypatch):
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "1")
    r = TestClient(web.app).get("/lang/ms?next=/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_the_page_declares_its_language():
    client = TestClient(web.app)
    assert '<html lang="en">' in client.get("/tests").text
    client.cookies.set("mailops-lang", "zh")
    assert '<html lang="zh-Hans">' in client.get("/tests").text
    assert '<html lang="zh-Hans" ' in client.get("/login").text     # it also carries data-theme


def test_the_switch_sits_beside_the_mailops_logo():
    client = TestClient(web.app)
    app_page = client.get("/").text
    header = app_page.split('<header class="app"', 1)[1]
    after_brand = header.split("</a>", 1)[1].lstrip()          # the brand link comes first
    assert after_brand.startswith('<nav class="langs"')
    head_right = app_page.split('<div class="head-right">', 1)[1].split("</div>\n</header>", 1)[0]
    assert 'class="langs"' not in head_right                    # and only there
    mark = client.get("/login").text.split('<div class="mark">', 1)[1].split("</div>", 1)[0]
    assert "MailOps" in mark and '<nav class="langs"' in mark


def test_every_page_offers_the_three_languages_and_marks_the_current_one():
    client = TestClient(web.app)
    client.cookies.set("mailops-lang", "ms")
    for path in ("/", "/tests", "/login", "/register"):
        html = client.get(path).text
        nav = html.split('<nav class="langs"', 1)[1].split("</nav>", 1)[0]
        assert 'href="/lang/en?next=' in nav and 'href="/lang/zh?next=' in nav, path
        assert '<a aria-current="true" href="/lang/ms?next=' in nav, path
        assert ">BM<" in nav and ">中文<" in nav, path


# --- nothing left in English -----------------------------------------------

import json  # noqa: E402
import re  # noqa: E402

# Regions that hold data, not interface text: never compared.
_SKIP = re.compile(
    r"<(style|script|code|pre|kbd)\b.*?</\1>"
    r"|<(\w+)\b[^>]*\btranslate=\"no\"[^>]*>.*?</\2>", re.S)
# A word of English prose: "Overview", "total", "Sender:". Codes are not
# prose - SPAM and OK are uppercase, container_count and email_004 carry an
# underscore, addresses an @ - and neither is the brand, MailOps.
_PROSE = re.compile(r"\(?[A-Za-z][a-z]{2,}[,.:;!?)…]*")
_ATTRS = re.compile(r'\s(?:placeholder|title|aria-label|alt)="([^"]*)"')


def _visible(html: str) -> set[str]:
    body = _SKIP.sub(" ", html)
    chunks = [" ".join(c.split()) for c in re.split(r"<[^>]+>", body)]
    chunks += [" ".join(a.split()) for a in _ATTRS.findall(body)]
    return {c for c in chunks if any(_PROSE.fullmatch(w) for w in c.split())}


def untranslated(html_en: str, html_other: str) -> list[str]:
    """English prose that reads the same in the other language: text nobody
    wrapped in t(). Elements holding data carry translate="no" and are
    skipped - keep those elements leaf-level (no same-tag nesting inside)."""
    return sorted(_visible(html_en) & _visible(html_other))


RESULTS = {
    "email_001": {"category": "BL_COMPARISON", "reason": "x", "status": "OK", "review_reason": None,
                  "has_defect": False, "defect_fields": [], "note": "No mismatch detected.", "fields": []},
    "email_004": {"category": "BL_COMPARISON", "reason": "Sender asks for a check", "status": "MISMATCH",
                  "review_reason": None, "has_defect": True, "defect_fields": ["container_count"], "note": None,
                  "fields": [{"name": "container_count", "si": "3 x 20'GP", "bl": "5 x 20'GP", "match": False}]},
    "email_002": {"category": "INVOICE_QUERY", "reason": "About an invoice", "status": "OK"},
}


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUT_DIR", tmp_path)
    (tmp_path / "results.json").write_text(json.dumps(RESULTS), encoding="utf-8")
    return TestClient(web.app)


def render(client, path, lang):
    client.cookies.set("mailops-lang", lang)
    return client.get(path).text


@pytest.mark.parametrize("path", ["/", "/?category=BL_COMPARISON&status=MISMATCH",
                                  "/dashboard", "/email/email_004", "/email/email_002"])
@pytest.mark.parametrize("lang", ["ms", "zh"])
def test_the_queue_overview_and_email_pages_are_fully_translated(site, path, lang):
    i18n.MISSES.clear()
    en, other = render(site, path, "en"), render(site, path, lang)
    assert untranslated(en, other) == []
    assert {m for m in i18n.MISSES if m[0] == lang} == set()


@pytest.mark.parametrize("path", ["/compose", "/tests"])
@pytest.mark.parametrize("lang", ["ms", "zh"])
def test_send_and_test_results_are_fully_translated(site, path, lang):
    i18n.MISSES.clear()
    en, other = render(site, path, "en"), render(site, path, lang)
    assert untranslated(en, other) == []
    assert {m for m in i18n.MISSES if m[0] == lang} == set()


@pytest.mark.parametrize("path", ["/login", "/register"])
@pytest.mark.parametrize("lang", ["ms", "zh"])
def test_sign_in_and_register_are_fully_translated(path, lang):
    client = TestClient(web.app)
    i18n.MISSES.clear()
    en, other = render(client, path, "en"), render(client, path, lang)
    assert untranslated(en, other) == []
    assert {m for m in i18n.MISSES if m[0] == lang} == set()


def test_account_errors_come_back_in_the_page_language(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUT_DIR", tmp_path)
    client = TestClient(web.app)
    client.cookies.set("mailops-lang", "zh")
    i18n.MISSES.clear()
    # acknowledge is ticked: the route checks it before the password, and
    # this test is about the password message.
    html = client.post("/register", data={"name": "A", "email": "a@b.co", "desk": "",
                                          "password": "short", "confirm": "short",
                                          "acknowledge": "1"}).text
    assert {m for m in i18n.MISSES if m[0] == "zh"} == set()
    assert "密码" in html and "password needs" not in html.lower()


@pytest.mark.parametrize("lang", ["en", "ms", "zh"])
def test_no_page_shows_markup_as_text(site, lang, monkeypatch):
    """A bold word inside a translated sentence once came out as the text
    "From <b>hackathon3in1@gmail.com</b>" - the tags on screen."""
    from sdoc.mail import send as snd
    monkeypatch.setattr(snd, "_REACHABLE", False)       # the "host blocks mail" notice too
    for path in ("/", "/dashboard", "/email/email_004", "/compose", "/tests", "/login", "/register"):
        html = render(site, path, lang)
        for escaped in ("&lt;b&gt;", "&lt;/b&gt;", "&lt;a ", "&lt;code&gt;"):
            assert escaped not in html, (path, escaped)


def test_the_run_checks_script_gets_its_sentences_in_the_page_language(site):
    html = render(site, "/tests", "zh")
    # base.html's panel script has its own table; find the Run checks one.
    tables = [json.loads(part.split(";\n", 1)[0]) for part in html.split("var T = ")[1:]]
    strings = next(s for s in tables if "All checks passed" in s)
    assert strings["All checks passed"] != "All checks passed"
    assert "{total}" in strings["{total} of {expected} graded emails"]   # placeholders survive for the script


# --- every sentence in the code has both translations ----------------------
# The page tests only see what their fixtures render. Singular and plural
# variants, a sent email, a reviewer's decision, an error - those appear in
# the code but not on those pages, so the code itself is read as well.

from pathlib import Path  # noqa: E402

WEB = Path(web.__file__).parent
SOURCES = sorted(WEB.glob("templates/*.html")) + [WEB / "app.py", WEB / "auth.py"]
_CALL = re.compile(r"(?<![\w.])(?:i18n\.)?(?:t|js_strings)\(")
_LITERAL = re.compile(r"""(["'])((?:\\.|(?!\1).)*?)\1""", re.S)
# Sentences chosen at run time from a table rather than written in a t() call.
DYNAMIC = {*web.KINDS.values(), *web.UNREADABLE, "File"}


def _keys(source: str) -> set[str]:
    """The sentences passed to t() or js_strings(). A literal used as a
    value (name="..."), a comparison (state == 'bad'), an index
    (email['from']) or part of a concatenation (... ~ ".json") is data
    going into a sentence, not a sentence."""
    keys = set()
    for m in _CALL.finditer(source):
        depth, i = 1, m.end()
        while depth and i < len(source):
            depth += (source[i] == "(") - (source[i] == ")")
            i += 1
        args = source[m.end():i - 1]
        for lit in _LITERAL.finditer(args):
            before, after = args[:lit.start()].rstrip(), args[lit.end():].lstrip()
            if before.endswith(("=", "[", "~")) or after.startswith(("]", "~", "==", "!=")):
                continue
            if lit.group(2).strip():
                keys.add(lit.group(2).replace("\\'", "'").replace('\\"', '"'))
    return keys


def sentences_in_the_code() -> set[str]:
    found = set(DYNAMIC)
    for path in SOURCES:
        found |= _keys(path.read_text(encoding="utf-8"))
    return found


def test_every_sentence_in_the_code_has_malay_and_chinese():
    missing = {s: [lang for lang in ("ms", "zh") if not (i18n.TABLE.get(s) or {}).get(lang)]
               for s in sentences_in_the_code()}
    assert {s: langs for s, langs in missing.items() if langs} == {}


def test_the_translation_table_has_no_leftovers():
    """A sentence reworded in a template leaves its old translation behind."""
    assert sorted(set(i18n.TABLE) - sentences_in_the_code()) == []


def test_placeholders_match_in_every_translation():
    """A translation that drops {n} shows a sentence with the number missing."""
    field = re.compile(r"\{(\w*)\}")
    wrong = {s: lang for s, row in i18n.TABLE.items() for lang, text in row.items()
             if sorted(field.findall(text)) != sorted(field.findall(s))}
    assert wrong == {}
