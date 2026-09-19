"""Attachment -> text. Knows file formats, nothing about shipping.

Never raises: a file that cannot be read comes back readable=False with a
problem a human reviewer can act on. That is what feeds the `unreadable`
escalation.
"""
import io
from dataclasses import dataclass
from pathlib import Path

from sdoc.inbox import read_attachment_bytes

# Below this many characters a document has no usable text. For a PDF that
# means an image-only scan with no text layer.
MIN_TEXT = 50


@dataclass
class DocText:
    path: str
    text: str
    readable: bool
    problem: str | None = None


def _txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _pdf(data: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _docx(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    lines = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            # merged cells repeat their text; keep one copy
            kept = [c for i, c in enumerate(cells) if c and (i == 0 or c != cells[i - 1])]
            if kept:
                lines.append(" | ".join(kept))
    return "\n".join(lines)


def _xlsx(data: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append(" | ".join(cells))
    wb.close()
    return "\n".join(lines)


_READERS = {".txt": _txt, ".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx}


def read_document(rel_path: str) -> DocText:
    try:
        data = read_attachment_bytes(rel_path)
    except FileNotFoundError:
        return DocText(rel_path, "", False, "file not found")
    if not data.strip():
        return DocText(rel_path, "", False, "file is empty")

    suffix = Path(rel_path).suffix.lower()
    reader = _READERS.get(suffix)
    if reader is None:
        return DocText(rel_path, "", False, f"unsupported file type {suffix}")
    try:
        text = reader(data)
    except Exception as e:
        return DocText(rel_path, "", False,
                       f"file is corrupt or cannot be opened ({type(e).__name__})")

    if len(text.strip()) < MIN_TEXT:
        if suffix == ".pdf":
            return DocText(rel_path, text, False, "no text layer - looks like a scanned image")
        return DocText(rel_path, text, False, "almost no readable text")
    return DocText(rel_path, text, True)
