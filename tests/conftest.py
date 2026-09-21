"""Defaults for the whole suite.

Two things are on in production and would make tests reach the outside
world or hit a sign-in wall, so they are switched off here. Tests that
care about either behaviour set the variable themselves.
"""
import pytest


@pytest.fixture(autouse=True)
def _test_defaults(monkeypatch):
    # Credentials resolve on their own now that sdoc.config loads .env, so a
    # test starting the app would otherwise begin polling Gmail for real.
    monkeypatch.setenv("SDOC_WATCH", "0")
    # Most tests exercise pages directly; the wall is tested on its own.
    monkeypatch.setenv("SDOC_REQUIRE_LOGIN", "0")
    # A real sending key in a developer's .env would otherwise decide how the
    # app behaves here - whether mail can leave is a thing tests state, not a
    # thing they inherit from whoever is running them.
    for key in ("SDOC_BREVO_KEY", "SDOC_SENDGRID_KEY", "SDOC_GMAIL_CLIENT_ID",
                "SDOC_GMAIL_CLIENT_SECRET", "SDOC_GMAIL_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
