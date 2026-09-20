import json

import pytest

from sdoc.web import auth


def test_a_password_is_never_stored_in_the_clear():
    stored = auth.hash_password("correct horse battery")
    assert "correct horse battery" not in stored
    assert stored.startswith("scrypt$")


def test_the_same_password_hashes_differently_every_time():
    """Per-password salt: two people with the same password must not match."""
    a, b = auth.hash_password("same-password"), auth.hash_password("same-password")
    assert a != b
    assert auth.verify_password("same-password", a)
    assert auth.verify_password("same-password", b)


def test_the_wrong_password_is_rejected():
    stored = auth.hash_password("right-password")
    assert auth.verify_password("right-password", stored) is True
    assert auth.verify_password("wrong-password", stored) is False
    assert auth.verify_password("", stored) is False


def test_a_corrupt_or_missing_hash_fails_closed():
    for junk in ("", "nonsense", "scrypt$only-two", "bcrypt$a$b", None):
        assert auth.verify_password("anything", junk) is False


def test_an_account_can_be_created_and_then_used(tmp_path):
    auth.create_user("Ops@Shipper.com", "hunter2-and-more", out_dir=tmp_path)
    assert auth.authenticate("ops@shipper.com", "hunter2-and-more", tmp_path) == "ops@shipper.com"


def test_email_case_and_spacing_do_not_create_two_accounts(tmp_path):
    auth.create_user("ops@shipper.com", "hunter2-and-more", out_dir=tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        auth.create_user("  OPS@Shipper.com  ", "another-password", out_dir=tmp_path)


def test_authentication_fails_for_unknown_email_or_bad_password(tmp_path):
    auth.create_user("ops@shipper.com", "hunter2-and-more", out_dir=tmp_path)
    assert auth.authenticate("nobody@shipper.com", "hunter2-and-more", tmp_path) is None
    assert auth.authenticate("ops@shipper.com", "wrong", tmp_path) is None


def test_short_passwords_and_bad_emails_are_refused(tmp_path):
    with pytest.raises(ValueError, match="at least"):
        auth.create_user("ops@shipper.com", "short", out_dir=tmp_path)
    for bad in ("ops", "ops@", "ops@shipper"):
        with pytest.raises(ValueError, match="email address"):
            auth.create_user(bad, "long-enough-password", out_dir=tmp_path)


def test_the_stored_file_holds_hashes_not_passwords(tmp_path):
    auth.create_user("ops@shipper.com", "hunter2-and-more", out_dir=tmp_path)
    raw = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert "hunter2-and-more" not in raw
    assert json.loads(raw)["ops@shipper.com"]["password"].startswith("scrypt$")


def test_signup_is_closed_unless_a_code_is_configured(monkeypatch):
    """Open signup plus the ability to send mail is an open relay."""
    monkeypatch.delenv("SDOC_SIGNUP_CODE", raising=False)
    assert auth.signup_open() is False
    assert auth.code_ok("") is False
    assert auth.code_ok("guess") is False


def test_only_the_configured_signup_code_is_accepted(monkeypatch):
    monkeypatch.setenv("SDOC_SIGNUP_CODE", "let-me-in")
    assert auth.signup_open() is True
    assert auth.code_ok("let-me-in") is True
    assert auth.code_ok("Let-Me-In") is False


def test_reading_is_open_unless_explicitly_closed(monkeypatch):
    monkeypatch.delenv("SDOC_REQUIRE_LOGIN", raising=False)
    assert auth.require_login() is False
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "1")
    assert auth.require_login() is True


def test_a_broken_users_file_does_not_take_the_app_down(tmp_path):
    (tmp_path / "users.json").write_text("{not json", encoding="utf-8")
    assert auth.load_users(tmp_path) == {}
