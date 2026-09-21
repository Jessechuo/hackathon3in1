from sdoc.ai.classify import build_prompt


def test_the_classifier_reads_malay_and_chinese_on_meaning():
    p = build_prompt({"from": "a@b.my", "subject": "Draf BL", "body": "Sila semak draf BL", "attachments": []})
    assert "English, Malay or Chinese" in p
    assert "Sila semak draf BL" in p          # the email goes in as written, untranslated
