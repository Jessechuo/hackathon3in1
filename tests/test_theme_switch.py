"""Theme switching must repaint in one frame.

Hover fades (transition on background/colour) also fired when the theme
flipped, so tiles, buttons and inbox rows lagged ~80ms behind the page
background: a visible two-step 'flash'. The toggle now suspends every
transition for the switch itself.
"""
import pytest
from fastapi.testclient import TestClient

from sdoc.web import app as web


@pytest.fixture
def html(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "OUT_DIR", tmp_path)
    return TestClient(web.app).get("/dashboard").text


def test_a_rule_suspends_all_transitions_while_switching(html):
    flat = " ".join(html.split())
    assert ".theme-switching *" in flat
    assert "transition:none !important" in flat


def test_the_toggle_uses_it_and_flushes_before_re_enabling(html):
    script = html[html.index('getElementById("theme-toggle")'):]
    assert 'classList.add("theme-switching")' in script
    assert "offsetHeight" in script              # force the repaint while transitions are off
    assert 'classList.remove("theme-switching")' in script


def test_an_os_theme_change_is_handled_the_same_way(html):
    assert "prefers-color-scheme: dark)').addEventListener" in html or \
           'prefers-color-scheme: dark)").addEventListener' in html
