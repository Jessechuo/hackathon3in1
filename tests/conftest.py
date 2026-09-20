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
