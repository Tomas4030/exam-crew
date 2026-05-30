"""DocumentIR: structured intermediate representation from PyMuPDF extraction.

This module normalizes raw PyMuPDF output into a clean, typed structure that
downstream modules (question_segmenter, asset_candidates) can consume without
knowing PyMuPDF internals.  It runs passively alongside the existing pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

import fitz


@dataclass
class LayoutBlock:
    id: str
    page: int
    type: str  # text | image | table | drawing_cluster | separator
    text: str | None
    bbox_pdf: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points
    reading_order: int
    source: str  # pymupdf_text | pymupdf_image | pymupdf_table | pymupdf_drawing
    font_size: float | None = None
    is_bold: bool = False


@dataclass
class PageIR:
    page: int
    width: float
    height: float
    blocks: list[LayoutBlock] = field(default_factory=list)
    image_count: int = 0
    table_count: int = 0
    drawing_cluster_count: int = 0


@dataclass
class DocumentIR:
    exam_id: str
    pdf_path: str
    total_pages: int
    pages: list[PageIR] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_document_ir(pdf_path: str | Path, exam_id: str = "") -> DocumentIR:
    """Build DocumentIR from a PDF file using PyMuPDF."""
    pdf_path = str(pdf_path)
    doc = fitz.open(pdf_path)
    ir = DocumentIR(exam_id=exam_id, pdf_path=pdf_path, total_pages=doc.page_count)

    for page_idx in range(doc.page_count):
        page = doc[page_idx]
        page_num = page_idx + 1
        rect = page.rect
        page_ir = PageIR(page=page_num, width=rect.width, height=rect.height)
        order = 0

        # Text blocks
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:  # text block
                lines_text = []
                max_size = 0.0
                has_bold = False
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        lines_text.append(span.get("text", ""))
                        size = span.get("size", 0)
                        if size > max_size:
                            max_size = size
                        if "bold" in (span.get("font", "") or "").lower():
                            has_bold = True
                text = " ".join(lines_text).strip()
                if not text:
                    continue
                bbox = block["bbox"]
                page_ir.blocks.append(LayoutBlock(
                    id=f"p{page_num}_b{order}",
                    page=page_num,
                    type="text",
                    text=text,
                    bbox_pdf=(bbox[0], bbox[1], bbox[2], bbox[3]),
                    reading_order=order,
                    source="pymupdf_text",
                    font_size=round(max_size, 1) if max_size else None,
                    is_bold=has_bold,
                ))
                order += 1
            elif block.get("type") == 1:  # image block
                bbox = block["bbox"]
                page_ir.blocks.append(LayoutBlock(
                    id=f"p{page_num}_img{page_ir.image_count}",
                    page=page_num,
                    type="image",
                    text=None,
                    bbox_pdf=(bbox[0], bbox[1], bbox[2], bbox[3]),
                    reading_order=order,
                    source="pymupdf_image",
                ))
                page_ir.image_count += 1
                order += 1

        # Tables
        try:
            tables = page.find_tables().tables
            for t_idx, table in enumerate(tables):
                bbox = table.bbox
                page_ir.blocks.append(LayoutBlock(
                    id=f"p{page_num}_tbl{t_idx}",
                    page=page_num,
                    type="table",
                    text=None,
                    bbox_pdf=(bbox[0], bbox[1], bbox[2], bbox[3]),
                    reading_order=order,
                    source="pymupdf_table",
                ))
                page_ir.table_count += 1
                order += 1
        except Exception:
            pass

        # Drawing clusters
        try:
            clusters = list(page.cluster_drawings())
            for c_idx, cluster_rect in enumerate(clusters):
                r = fitz.Rect(cluster_rect)
                if r.width < 10 or r.height < 10:
                    continue
                # Skip separator lines
                if r.height < 3 and r.width > rect.width * 0.5:
                    continue
                page_ir.blocks.append(LayoutBlock(
                    id=f"p{page_num}_dc{c_idx}",
                    page=page_num,
                    type="drawing_cluster",
                    text=None,
                    bbox_pdf=(r.x0, r.y0, r.x1, r.y1),
                    reading_order=order,
                    source="pymupdf_drawing",
                ))
                page_ir.drawing_cluster_count += 1
                order += 1
        except Exception:
            pass

        # Sort by reading order (top-to-bottom, left-to-right)
        page_ir.blocks.sort(key=lambda b: (b.bbox_pdf[1], b.bbox_pdf[0]))
        for i, b in enumerate(page_ir.blocks):
            b.reading_order = i

        ir.pages.append(page_ir)

    doc.close()
    return ir
