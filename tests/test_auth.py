import json

import pytest

from sdoc.web import auth

GOOD = "Operator-2026!x"


def test_a_password_is_never_stored_in_the_clear():
    stored = auth.hash_password(GOOD)
    assert GOOD not in stored
    assert stored.startswith("scrypt$")


def test_the_same_password_hashes_differently_every_time():
    """Per-password salt: two people with the same password must not match."""
    a, b = auth.hash_password(GOOD), auth.hash_password(GOOD)
    assert a != b
    assert auth.verify_password(GOOD, a)
    assert auth.verify_password(GOOD, b)


def test_the_wrong_password_is_rejected():
    stored = auth.hash_password(GOOD)
    assert auth.verify_password(GOOD, stored) is True
    assert auth.verify_password("Wrong-2026!xx", stored) is False
    assert auth.verify_password("", stored) is False


def test_a_corrupt_or_missing_hash_fails_closed():
    for junk in ("", "nonsense", "scrypt$only-two", "bcrypt$a$b", None):
        assert auth.verify_password("anything", junk) is False


# --- the password rule the registration screen states --------------------

def test_the_rule_is_the_one_printed_on_the_form():
    assert auth.password_problems(GOOD) == []
    assert auth.password_problems("Sh0rt!") == [f"at least {auth.MIN_PASSWORD} characters"]
    assert auth.password_problems("alllowercaselong") == [
        "an uppercase letter", "a number", "a symbol"]
    assert auth.password_problems("NoDigitsHere!!") == ["a number"]
    assert auth.password_problems("NoSymbols2026x") == ["a symbol"]


def test_nothing_typed_is_missing_everything():
    assert len(auth.password_problems("")) == 4


# --- accounts ------------------------------------------------------------

def test_an_account_can_be_created_and_then_used(tmp_path):
    auth.create_user("Ops@Shipper.com", GOOD, out_dir=tmp_path, name="Aziz T.")
    assert auth.authenticate("ops@shipper.com", GOOD, tmp_path) == "ops@shipper.com"


def test_what_is_stored_about_a_person(tmp_path):
    auth.create_user("ops@shipper.com", GOOD, out_dir=tmp_path,
                     name="Aziz T.", desk=auth.DESKS[0])
    user = auth.get_user("ops@shipper.com", tmp_path)
    assert user["name"] == "Aziz T."
    assert user["desk"] == auth.DESKS[0]
    assert user["created"]


def test_email_case_and_spacing_do_not_create_two_accounts(tmp_path):
    auth.create_user("ops@shipper.com", GOOD, out_dir=tmp_path, name="Aziz T.")
    with pytest.raises(ValueError, match="already exists"):
        auth.create_user("  OPS@Shipper.com  ", GOOD, out_dir=tmp_path, name="Someone")


def test_authentication_fails_for_unknown_email_or_bad_password(tmp_path):
    auth.create_user("ops@shipper.com", GOOD, out_dir=tmp_path, name="Aziz T.")
    assert auth.authenticate("nobody@shipper.com", GOOD, tmp_path) is None
    assert auth.authenticate("ops@shipper.com", "Wrong-2026!xx", tmp_path) is None


def test_the_form_fields_are_all_checked(tmp_path):
    def make(**over):
        args = {"email": "new@shipper.com", "password": GOOD, "out_dir": tmp_path,
                "name": "Aziz T.", "desk": "", "confirm": GOOD}
        args.update(over)
        return auth.create_user(**args)

    with pytest.raises(ValueError, match="name is required"):
        make(name="   ")
    for bad in ("ops", "ops@", "ops@shipper"):
        with pytest.raises(ValueError, match="email address"):
            make(email=bad)
    with pytest.raises(ValueError, match="uppercase"):
        make(password="alllowercaselong", confirm="alllowercaselong")
    with pytest.raises(ValueError, match="do not match"):
        make(confirm=GOOD + "z")
    with pytest.raises(ValueError, match="pick a desk"):
        make(desk="ATLANTIS-XX99")
    assert auth.load_users(tmp_path) == {}      # nothing was half-created


def test_the_stored_file_holds_hashes_not_passwords(tmp_path):
    auth.create_user("ops@shipper.com", GOOD, out_dir=tmp_path, name="Aziz T.")
    raw = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert GOOD not in raw
    assert json.loads(raw)["ops@shipper.com"]["password"].startswith("scrypt$")


# --- how the doors are configured ----------------------------------------

def test_signup_is_open_by_default(monkeypatch):
    """Anyone can make their own account, the way a mail service works."""
    monkeypatch.delenv("SDOC_SIGNUP_CODE", raising=False)
    assert auth.code_required() is False
    assert auth.code_ok("") is True             # nothing to check against


def test_a_code_closes_signup_when_one_is_set(monkeypatch):
    monkeypatch.setenv("SDOC_SIGNUP_CODE", "let-me-in")
    assert auth.code_required() is True
    assert auth.code_ok("let-me-in") is True
    assert auth.code_ok("Let-Me-In") is False
    assert auth.code_ok("") is False


def test_reading_needs_an_account_unless_opened_up(monkeypatch):
    monkeypatch.delenv("SDOC_REQUIRE_LOGIN", raising=False)
    assert auth.require_login() is True
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "0")
    assert auth.require_login() is False


def test_a_broken_users_file_does_not_take_the_app_down(tmp_path):
    (tmp_path / "users.json").write_text("{not json", encoding="utf-8")
    assert auth.load_users(tmp_path) == {}
