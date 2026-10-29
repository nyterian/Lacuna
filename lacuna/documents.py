from __future__ import annotations
import hashlib
import io
import re
from pathlib import Path
from pypdf import PdfReader
from .models import Study


def read_pdf(body: bytes, filename: str, max_pages: int = 300, include_tail: bool = False) -> Study:
    if not body[:1024].lstrip().startswith(b"%PDF-"):
        raise ValueError("File does not contain a valid PDF header.")
    reader = PdfReader(io.BytesIO(body), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("Encrypted PDF could not be opened. Supply an unencrypted copy.")
    pages, failed = [], []
    total = len(reader.pages)
    sampled_tail=include_tail and total>max_pages
    if sampled_tail:
        head=max_pages//2
        indices=list(range(head))+list(range(total-(max_pages-head),total))
        pages=[""]*total
    else:
        indices=list(range(min(total,max_pages)))
    for index in indices:
        try:
            text = reader.pages[index].extract_text(extraction_mode="plain") or ""
            if sampled_tail:pages[index]=text.replace("\x00", "")
            else:pages.append(text.replace("\x00", ""))
        except Exception:
            if sampled_tail:pages[index]=""
            else:pages.append("")
            failed.append(index+1)
    first = "" if sampled_tail and max_pages//2==0 else "\n".join(pages[:2])
    metadata = reader.metadata
    title = str(metadata.title or "").strip() if metadata else ""
    if not title or title.lower() in {"untitled", "microsoft word", "document"} or title.lower().endswith(".docx"):
        title = next((line.strip() for line in first.splitlines() if len(line.strip()) > 20), Path(filename).stem)
    dois = re.findall(r"\b10\.\d{4,9}/[^\s<>\"{}]+", first, re.I)
    # Do not infer a document DOI from a bibliography containing several DOIs.
    doi = dois[0].rstrip(".,;)") if len(set(dois)) == 1 else ""
    visible = sum(len(p.strip()) for p in pages)
    status = "read" if visible >= 100 else "ocr_required"
    if failed or total > max_pages:
        status = "partial" if visible >= 100 else "ocr_required"
    note = ""
    if visible < 100:
        note = "Insufficient extractable text; OCR is required. Image-only pages were not analyzed."
    if sampled_tail:
        note += f" Read a head/tail sample of {max_pages}/{total} physical PDF pages; unread middle pages were not analyzed."
    elif total > max_pages:
        note += f" Only the first {max_pages}/{total} PDF pages were processed."
    if failed:
        note += f" Unreadable PDF pages: {failed}."
    return Study(title=title[:1000], abstract="", doi=doi, sources=["local_pdf"], type="unknown",
                 source_ids={"local_pdf": hashlib.sha256(body).hexdigest()}, local_filename=Path(filename).name,
                 file_sha256=hashlib.sha256(body).hexdigest(), pages=pages, pages_total=total,
                 pages_read=sum(bool(p.strip()) for p in pages), full_text_status=status, full_text_note=note.strip())


def attach_pdf(study: Study, pdf: Study):
    study.pages, study.pages_read, study.pages_total = pdf.pages, pdf.pages_read, pdf.pages_total
    study.full_text_status, study.full_text_note = pdf.full_text_status, pdf.full_text_note
    study.file_sha256 = pdf.file_sha256
    # Preserve provider bibliographic identity; a guessed PDF title must not overwrite it.
