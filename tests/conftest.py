"""Safety net for the whole suite: no test may reach a real mailbox.

Credentials resolve on their own now that sdoc.config loads .env, so a test
that starts the app through `with TestClient(...)` would otherwise trigger
the lifespan and begin polling Gmail for real. Individual tests that want
the watcher on set SDOC_WATCH themselves.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_live_mail_watch(monkeypatch):
    monkeypatch.setenv("SDOC_WATCH", "0")
