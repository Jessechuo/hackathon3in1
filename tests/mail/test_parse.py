from email.message import EmailMessage

from sdoc.mail.parse import parse_message


def build(subject="Check this BL", sender="Ops Team <ops@shipper.com>",
          text="Hi,\n\nPlease compare the attached.\n", html=None, files=()):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "hackathon3in1@gmail.com"
    if text is not None:
        msg.set_content(text)
    if html is not None:
        if text is None:
            msg.set_content(html, subtype="html")
        else:
            msg.add_alternative(html, subtype="html")
    for name, data in files:
        msg.add_attachment(data, maintype="application", subtype="octet-stream",
                           filename=name)
    return msg.as_bytes()


def test_the_sender_is_the_bare_address():
    assert parse_message(build())["from"] == "ops@shipper.com"


def test_subject_and_body_come_through():
    parsed = parse_message(build())
    assert parsed["subject"] == "Check this BL"
    assert "Please compare the attached." in parsed["body"]


def test_attachments_come_back_as_name_and_bytes():
    parsed = parse_message(build(files=[("SI.txt", b"SHIPPER: ACME"),
                                        ("BL.txt", b"SHIPPER: ACME CORP")]))
    assert parsed["attachments"] == [("SI.txt", b"SHIPPER: ACME"),
                                     ("BL.txt", b"SHIPPER: ACME CORP")]


def test_plain_text_is_preferred_over_html():
    parsed = parse_message(build(text="the plain one", html="<p>the html one</p>"))
    assert "the plain one" in parsed["body"]
    assert "the html one" not in parsed["body"]


def test_an_html_only_message_is_reduced_to_readable_text():
    html = ("<html><head><style>p{color:red}</style></head><body>"
            "<p>Hi,</p><p>Please check the&nbsp;attached BL.</p>"
            "<script>alert(1)</script></body></html>")
    body = parse_message(build(text=None, html=html))["body"]
    assert "Hi," in body and "Please check the attached BL." in body
    assert "<p>" not in body and "alert" not in body and "color:red" not in body


def test_a_subject_encoded_for_non_ascii_is_decoded():
    raw = build(subject="Sjöfart BL kontroll")
    assert parse_message(raw)["subject"] == "Sjöfart BL kontroll"


def test_a_message_with_no_subject_or_body_does_not_crash():
    msg = EmailMessage()
    msg["From"] = "a@b.com"
    parsed = parse_message(msg.as_bytes())
    assert parsed["subject"] == "" and parsed["from"] == "a@b.com"
    assert parsed["attachments"] == []


def test_an_attachment_with_no_filename_is_skipped():
    msg = EmailMessage()
    msg["From"] = "a@b.com"
    msg["Subject"] = "s"
    msg.set_content("body")
    msg.add_attachment(b"\x89PNG", maintype="image", subtype="png")
    assert parse_message(msg.as_bytes())["attachments"] == []
