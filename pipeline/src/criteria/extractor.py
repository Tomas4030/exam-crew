"""Extract text (and, for legacy scans, vision OCR) from a criteria PDF."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz  # PyMuPDF


@dataclass
class CriteriaPage:
    page: int
    text: str
    image_path: str | None = None


@dataclass
class ExtractedCriteria:
    pages: list[CriteriaPage] = field(default_factory=list)
    total_pages: int = 0
    text_quality: str = "native"  # "native" | "scanned"

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)


# Characters that signal a healthy Latin-1/UTF-8 text layer for Portuguese.
_PT_HINTS = ("ção", "GRUPO", "pontos", "Versão", "classificação", "item")


def _looks_corrupted(text: str) -> bool:
    """Heuristic: detect a broken/scanned text layer.

    Legacy scanned PDFs return either almost no text, or text dominated by
    replacement chars / custom-font garbage.
    """
    stripped = text.strip()
    if len(stripped) < 200:
        return True
    # Proportion of non-printable / replacement characters.
    bad = sum(1 for c in stripped if c in "�\x00")
    if bad / max(len(stripped), 1) > 0.02:
        return True
    # Must contain at least one Portuguese criteria hint somewhere.
    if not any(h.lower() in stripped.lower() for h in _PT_HINTS):
        return True
    return False


def extract_pdf_text(pdf_path: str) -> ExtractedCriteria:
    """Extract native text per page. Marks text_quality=scanned if corrupted."""
    doc = fitz.open(pdf_path)
    pages: list[CriteriaPage] = []
    for i in range(doc.page_count):
        text = doc[i].get_text() or ""
        pages.append(CriteriaPage(page=i + 1, text=text))
    total = doc.page_count
    doc.close()

    result = ExtractedCriteria(pages=pages, total_pages=total)
    result.text_quality = "scanned" if _looks_corrupted(result.full_text) else "native"
    return result


def render_pages_to_images(pdf_path: str, out_dir: str, *, dpi: int = 200) -> dict[int, str]:
    """Render each PDF page to a PNG. Returns {page_num: image_path}.

    Used only for the vision OCR fallback on scanned legacy PDFs.
    """
    import os

    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    paths: dict[int, str] = {}
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    for i in range(doc.page_count):
        pix = doc[i].get_pixmap(matrix=matrix)
        path = os.path.join(out_dir, f"criteria_page_{i + 1}.png")
        pix.save(path)
        paths[i + 1] = path
    doc.close()
    return paths


def normalize_whitespace(text: str) -> str:
    """Collapse runs of dots/spaces used as leaders, keep newlines."""
    # Dot leaders (".......") → single space marker so item lines stay parseable.
    text = re.sub(r"\.{4,}", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text
