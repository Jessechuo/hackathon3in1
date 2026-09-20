import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.web import app as web
from sdoc.web import auth

PASSWORD = "Operator-2026!x"
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
    monkeypatch.delenv("SDOC_SIGNUP_CODE", raising=False)
    return TestClient(web.app), out


def register(client, **over):
    data = {"name": "New Clerk", "email": "new@shipper.com", "password": PASSWORD,
            "confirm": PASSWORD, "acknowledge": "1"}
    data.update(over)
    return client.post("/register", data=data, follow_redirects=False)


# --- the sign-in wall ----------------------------------------------------

def test_the_queue_is_behind_the_sign_in(site, monkeypatch):
    client, _ = site
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "1")
    for path in ("/", "/dashboard", "/compose", "/email/email_043"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303, path
        assert r.headers["location"].startswith("/login?next="), path


def test_the_sign_in_screens_are_always_reachable(site, monkeypatch):
    client, _ = site
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "1")
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200


def test_signing_in_takes_you_to_the_page_you_asked_for(site, monkeypatch):
    client, out = site
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "1")
    auth.create_user(EMAIL, PASSWORD, out_dir=out, name="Test Clerk")

    r = client.get("/dashboard", follow_redirects=False)
    assert r.headers["location"] == "/login?next=/dashboard"

    r = client.post("/login", data={"email": EMAIL, "password": PASSWORD,
                                    "next": "/dashboard"}, follow_redirects=False)
    assert r.headers["location"] == "/dashboard"
    assert client.get("/dashboard").status_code == 200


def test_reading_can_be_opened_up_instead(site, monkeypatch):
    client, _ = site
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "0")
    assert client.get("/").status_code == 200


# --- signing in ----------------------------------------------------------

def test_the_login_screen_carries_the_design_it_was_built_from(site):
    client, _ = site
    html = client.get("/login").text
    for mark in ("SECURE_AUTH // PORT:443", "OPS_GATEWAY", "RESTRICTED ACCESS",
                 "Sign in to Terminal", "Operator onboarding",
                 "MSC.428(98) COMPLIANT SYSTEM"):
        assert mark in html, mark
    assert 'name="email"' in html and 'name="password"' in html


def test_signing_in_then_out(site):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out, name="Test Clerk")

    r = client.post("/login", data={"email": EMAIL, "password": PASSWORD},
                    follow_redirects=False)
    assert r.status_code == 303
    assert EMAIL in client.get("/").text            # the header names them
    assert "Sign out" in client.get("/").text

    client.post("/logout", follow_redirects=False)
    assert "Sign out" not in client.get("/").text


def test_a_wrong_password_does_not_say_which_half_was_wrong(site):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out, name="Test Clerk")
    r = client.post("/login", data={"email": EMAIL, "password": "Nope-2026!xx"})
    assert r.status_code == 401
    assert "do not match an account" in r.text
    for leak in ("no such user", "unknown email", "wrong password"):
        assert leak not in r.text.lower()


def test_an_unknown_email_gets_the_same_message(site):
    client, _ = site
    r = client.post("/login", data={"email": "ghost@nowhere.com", "password": PASSWORD})
    assert r.status_code == 401
    assert "do not match an account" in r.text


def test_visiting_login_while_signed_in_just_moves_you_along(site):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out, name="Test Clerk")
    client.post("/login", data={"email": EMAIL, "password": PASSWORD},
                follow_redirects=False)
    assert client.get("/login", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("hostile", [
    "https://evil.example/steal",
    "//evil.example/steal",          # protocol-relative: a leading / is not enough
    "\\\\evil.example",
    "javascript:alert(1)",
])
def test_no_redirect_target_can_take_you_off_the_site(site, hostile):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out, name="Test Clerk")
    r = client.post("/login", data={"email": EMAIL, "password": PASSWORD,
                                    "next": hostile}, follow_redirects=False)
    assert r.headers["location"] == "/", hostile


# --- registering ---------------------------------------------------------

def test_the_registration_screen_carries_the_design_it_was_built_from(site):
    client, _ = site
    html = client.get("/register").text
    for mark in ("Request Terminal Access / Register", "SEC-LVL-2",
                 "Full legal name", "Corporate logistics email",
                 "Desk / region queue assignment", "FED-STD-0027",
                 "Register &amp; Request Access", "AUTH-SRV: ACTIVE"):
        assert mark in html, mark
    for desk in auth.DESKS:
        assert desk in html


def test_anyone_can_create_their_own_account(site):
    client, out = site
    r = register(client)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "new@shipper.com" in auth.load_users(out)
    assert "Sign out" in client.get("/").text       # and they are signed straight in


def test_signup_is_open_by_default(site):
    client, _ = site
    assert 'name="code"' not in client.get("/register").text


def test_a_code_can_be_required_for_a_deployment_that_wants_that(site, monkeypatch):
    client, out = site
    monkeypatch.setenv("SDOC_SIGNUP_CODE", CODE)
    assert 'name="code"' in client.get("/register").text
    r = register(client, code="guess")
    assert r.status_code == 400 and "access code is not right" in r.text
    assert auth.load_users(out) == {}
    assert register(client, code=CODE).status_code == 303


def test_a_weak_password_is_refused_with_the_rule_the_form_states(site):
    client, out = site
    r = register(client, password="alllowercase", confirm="alllowercase")
    assert "an uppercase letter" in r.text and "a number" in r.text
    assert auth.load_users(out) == {}


def test_mismatched_passwords_are_refused(site):
    client, out = site
    r = register(client, confirm=PASSWORD + "z")
    assert "do not match" in r.text
    assert auth.load_users(out) == {}


def test_the_audit_acknowledgement_is_required(site):
    client, out = site
    r = register(client, acknowledge="")
    assert "acknowledge" in r.text.lower()
    assert auth.load_users(out) == {}


def test_a_name_is_required(site):
    client, out = site
    r = register(client, name="   ")
    assert "name is required" in r.text
    assert auth.load_users(out) == {}


def test_the_desk_assignment_is_stored(site):
    client, out = site
    register(client, desk=auth.DESKS[0])
    assert auth.get_user("new@shipper.com", out)["desk"] == auth.DESKS[0]


def test_a_made_up_desk_is_refused(site):
    client, out = site
    r = register(client, desk="ATLANTIS-XX99")
    assert "pick a desk" in r.text
    assert auth.load_users(out) == {}


def test_a_duplicate_account_is_refused(site):
    client, out = site
    auth.create_user(EMAIL, PASSWORD, out_dir=out, name="Test Clerk")
    r = register(client, email=EMAIL)
    assert "already exists" in r.text


def test_what_a_person_typed_survives_a_rejected_form(site):
    """Retyping a long form because one field was wrong is miserable."""
    client, _ = site
    r = register(client, name="Aziz T.", email="aziz@line.com", acknowledge="")
    assert "Aziz T." in r.text and "aziz@line.com" in r.text
