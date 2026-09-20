import json

import pytest
from fastapi.testclient import TestClient

from sdoc import inbox
from sdoc.mail import store
from sdoc.web import app as web


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Three patches, one per module that resolves a directory at call time:
    the app's output dir, the app's mail dir, and the loader's mail dir."""
    out, mail = tmp_path / "out", tmp_path / "mail"
    out.mkdir()
    monkeypatch.setattr(web, "OUT_DIR", out)
    monkeypatch.setattr(web, "MAIL_DIR", mail)
    monkeypatch.setattr(inbox, "MAIL_DIR", mail)
    return TestClient(web.app), out, mail


def test_a_received_email_appears_in_the_inbox(site):
    client, out, mail = site
    store.save_email("captain@line.com", "Please check BL", "body", [], root=mail)
    html = client.get("/").text
    assert 'data-id="mail_0001"' in html
    assert "Please check BL" in html


def test_its_verdict_comes_from_mail_results(site):
    client, out, mail = site
    store.save_email("a@b.com", "s", "b", [], root=mail)
    (out / "mail_results.json").write_text(json.dumps({
        "mail_0001": {"category": "BL_COMPARISON", "status": "MISMATCH",
                      "has_defect": True, "defect_fields": ["shipper"], "fields": []}}),
        encoding="utf-8")
    assert web.load_results()["mail_0001"]["status"] == "MISMATCH"
    assert 'data-id="mail_0001"' in client.get("/?status=MISMATCH").text


def test_bundle_results_and_mail_results_live_side_by_side(site):
    client, out, mail = site
    (out / "results.json").write_text(
        json.dumps({"email_001": {"category": "SPAM", "status": "OK"}}), encoding="utf-8")
    (out / "mail_results.json").write_text(
        json.dumps({"mail_0001": {"category": "SPAM", "status": "OK"}}), encoding="utf-8")
    results = web.load_results()
    assert "email_001" in results and "mail_0001" in results


def test_the_detail_page_opens_for_a_received_email(site):
    client, out, mail = site
    store.save_email("a@b.com", "Draft BL attached", "Please compare.", [], root=mail)
    r = client.get("/email/mail_0001")
    assert r.status_code == 200
    assert "Draft BL attached" in r.text


def test_a_received_attachment_can_be_opened(site):
    client, out, mail = site
    # Over MIN_TEXT: a shorter file is correctly reported as unreadable.
    store.save_email("a@b.com", "s", "b",
                     [("SI.txt", b"SHIPPER: ACME LOGISTICS PTE LTD\n"
                                 b"CONSIGNEE: NORDIC IMPORTS AB\n"
                                 b"POL: SINGAPORE\nPOD: HAMBURG\n")],
                     root=mail)
    r = client.get("/attachment/mail/attachments/mail_0001__SI.txt")
    assert r.status_code == 200
    assert "ACME LOGISTICS" in r.text


def test_a_path_outside_the_two_attachment_folders_is_refused(site):
    client, _, _ = site
    for bad in ("/attachment/mail/../secrets.txt",
                "/attachment/out/ground_truth.json",
                "/attachment/mail/inbox/mail_0001.json"):
        assert client.get(bad).status_code == 400


def test_the_header_counts_what_arrived(site):
    client, out, mail = site
    store.save_email("a@b.com", "s", "b", [], root=mail)
    assert "1 received" in client.get("/").text
