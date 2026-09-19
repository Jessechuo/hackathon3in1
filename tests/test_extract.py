import pytest

from sdoc.extract import read_document


def test_txt_is_read():
    d = read_document("attachments/email_001_SI.txt")
    assert d.readable and "SHIPPING INSTRUCTION" in d.text


def test_xlsx_cells_are_read_as_lines():
    d = read_document("attachments/email_005_SI.xlsx")
    assert d.readable and "15 x 20'GP" in d.text and "341715" in d.text


def test_docx_is_read():
    d = read_document("attachments/email_055_BL.docx")
    assert d.readable and "BILL OF LADING" in d.text.upper()


def test_text_pdf_is_read():
    d = read_document("attachments/email_059_SI.pdf")
    assert d.readable and "131,322 KG" in d.text


def test_scanned_pdf_is_unreadable():
    d = read_document("attachments/email_512_SI.pdf")
    assert not d.readable and "scanned" in d.problem


@pytest.mark.parametrize("path", ["attachments/email_511_BL.pdf", "attachments/email_515_BL.pdf"])
def test_broken_pdf_is_unreadable(path):
    d = read_document(path)
    assert not d.readable and d.problem


def test_exactly_the_known_bad_files_in_the_bundle_are_unreadable():
    """Sweeps all 250 attachments: every txt/xlsx/docx and text PDF must
    read; only the 6 scans and 2 corrupt PDFs may not."""
    import os
    from pathlib import Path

    from sdoc.config import BUNDLE_DIR

    names = sorted(os.listdir(Path(BUNDLE_DIR) / "attachments"))
    unreadable = {n for n in names if not read_document(f"attachments/{n}").readable}
    assert unreadable == {
        "email_511_BL.pdf", "email_515_BL.pdf",                        # corrupt
        "email_512_SI.pdf", "email_512_BL.pdf", "email_513_SI.pdf",    # scanned
        "email_513_BL.pdf", "email_514_SI.pdf", "email_514_BL.pdf",
    }


def test_missing_file_is_unreadable_not_an_exception():
    d = read_document("attachments/does_not_exist.txt")
    assert not d.readable and d.problem == "file not found"
