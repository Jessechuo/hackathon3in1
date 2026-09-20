import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.web import app as web
from sdoc.web import auth

PASSWORD = "a-good-long-password"
EMAIL = "clerk@shipper.com"
CODE = "let-me-in"


@pytest.fixture
def site(tmp_path, monkeypatch):
    out, mail = tmp_path / "out", tmp_path / "mail"
    out.mkdir()
    monkeypatch.setattr(web, "OUT_DIR", out)
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)
    monkeypatch.setattr(auth, "OUT_DIR", out)
    monkeypatch.setenv("SDOC_SIGNUP_CODE", CODE)
    return TestClient(web.app), out


def test_the_login_page_asks_for_email_and_password(site):
    client, _ = site
    html = client.get("/login").text
    assert 'name="email"' in html and 'name="password"' in html


def test_signing_in_then_out(site):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out)

    r = client.post("/login", data={"email": EMAIL, "password": PASSWORD},
                    follow_redirects=False)
    assert r.status_code == 303
    assert EMAIL in client.get("/").text            # the header names them
    assert "Sign out" in client.get("/").text

    client.post("/logout", follow_redirects=False)
    assert "Sign out" not in client.get("/").text
    assert "Sign in" in client.get("/").text


def test_a_wrong_password_does_not_say_which_half_was_wrong(site):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out)
    html = client.post("/login", data={"email": EMAIL, "password": "nope"}).text
    assert "do not match an account" in html
    for leak in ("no such user", "unknown email", "wrong password"):
        assert leak not in html.lower()


def test_an_unknown_email_gets_the_same_message(site):
    client, _ = site
    html = client.post("/login", data={"email": "ghost@nowhere.com",
                                       "password": PASSWORD}).text
    assert "do not match an account" in html


def test_signing_in_returns_you_where_you_were_going(site):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out)
    r = client.post("/login", data={"email": EMAIL, "password": PASSWORD,
                                    "next": "/dashboard"}, follow_redirects=False)
    assert r.headers["location"] == "/dashboard"


def test_an_offsite_redirect_is_not_followed(site):
    """`next` comes from the URL, so it is attacker-controlled."""
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out)
    r = client.post("/login", data={"email": EMAIL, "password": PASSWORD,
                                    "next": "https://evil.example/steal"},
                    follow_redirects=False)
    assert r.headers["location"] == "/"


def test_registering_creates_the_account_and_signs_you_in(site):
    client, out = site
    r = client.post("/register", data={"email": "new@shipper.com",
                                       "password": PASSWORD, "code": CODE},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/compose"
    assert "new@shipper.com" in auth.load_users(out)
    assert "Sign out" in client.get("/").text


def test_the_wrong_signup_code_creates_nothing(site):
    client, out = site
    html = client.post("/register", data={"email": "new@shipper.com",
                                          "password": PASSWORD,
                                          "code": "guess"}).text
    assert "signup code is not right" in html
    assert auth.load_users(out) == {}


def test_registration_is_closed_when_no_code_is_configured(site, monkeypatch):
    """Open signup plus the ability to send mail is an open relay."""
    client, out = site
    monkeypatch.delenv("SDOC_SIGNUP_CODE", raising=False)
    html = client.post("/register", data={"email": "new@shipper.com",
                                          "password": PASSWORD, "code": ""}).text
    assert "turned off" in html
    assert auth.load_users(out) == {}


def test_a_short_password_is_refused_with_a_readable_reason(site):
    client, out = site
    html = client.post("/register", data={"email": "new@shipper.com",
                                          "password": "short", "code": CODE}).text
    assert "at least 8 characters" in html
    assert auth.load_users(out) == {}


def test_a_duplicate_account_is_refused(site):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out)
    html = client.post("/register", data={"email": EMAIL, "password": PASSWORD,
                                          "code": CODE}).text
    assert "already exists" in html


def test_visiting_login_while_signed_in_just_moves_you_along(site):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out)
    client.post("/login", data={"email": EMAIL, "password": PASSWORD},
                follow_redirects=False)
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 303


def test_every_page_offers_a_way_in_when_signed_out(site):
    client, _ = site
    assert "/login" in client.get("/").text
    assert "/login" in client.get("/dashboard").text


@pytest.mark.parametrize("hostile", [
    "https://evil.example/steal",
    "//evil.example/steal",          # protocol-relative: a leading / is not enough
    "\\evil.example",
    "javascript:alert(1)",
])
def test_no_redirect_target_can_take_you_off_the_site(site, hostile):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out)
    r = client.post("/login", data={"email": EMAIL, "password": PASSWORD,
                                    "next": hostile}, follow_redirects=False)
    assert r.headers["location"] == "/", hostile
