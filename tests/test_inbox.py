from sdoc import inbox


def test_loads_all_520_emails():
    emails = inbox.load_emails()
    assert len(emails) == 520


def test_emails_are_sorted_by_id():
    emails = inbox.load_emails()
    ids = [e["email_id"] for e in emails]
    assert ids == sorted(ids)
    assert ids[0] == "email_001"
    assert ids[-1] == "email_520"


def test_every_email_has_required_keys():
    for e in inbox.load_emails():
        assert set(e) >= {"email_id", "from", "subject", "body", "attachments"}


def test_reads_attachment_text():
    text = inbox.read_attachment_text("attachments/email_001_SI.txt")
    assert "SHIPPING INSTRUCTION" in text


def test_attachment_text_survives_bad_bytes():
    """Some attachments are deliberately corrupt. Reading must not raise."""
    text = inbox.read_attachment_text("attachments/email_001_BL.txt")
    assert isinstance(text, str)
