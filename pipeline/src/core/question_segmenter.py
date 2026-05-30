"""Question segmenter: detect question anchors from DocumentIR text blocks.

This runs BEFORE the VLM and produces QuestionCandidate objects with page
regions.  The VLM then only needs to transcribe/structure within each region
instead of parsing the entire page.

This module is passive: it does not alter the existing pipeline output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from .layout_ir import DocumentIR, PageIR, LayoutBlock


# ── Anchor patterns ──────────────────────────────────────────────

_MAIN_Q = re.compile(r"^\s*(\d{1,2})\.\s+\S")
_SUB_Q = re.compile(r"^\s*(\d{1,2}(?:\.\d+)+)\.\s+\S")
_GROUP = re.compile(r"^\s*Grupo\s+([IVX]+)\b", re.IGNORECASE)
_ITEM = re.compile(r"^\s*Item\s+(\d+)\b", re.IGNORECASE)

# Patterns that look like question numbers but are actually enumerations
# inside a statement (e.g. "1. superior  2. igual  3. inferior")
_ENUM_INSIDE = re.compile(r"^\s*[1-5]\.\s+\w{2,15}\s*$")


@dataclass
class QuestionCandidate:
    number: str
    page_start: int
    page_end: int
    bbox_pdf: tuple[float, float, float, float]  # region on page_start
    block_ids: list[str] = field(default_factory=list)
    confidence: float = 0.9
    detection_method: str = "text_anchor"
    parent_number: str | None = None
    is_group: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SegmentationResult:
    exam_id: str
    candidates: list[QuestionCandidate] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "exam_id": self.exam_id,
            "total_candidates": len(self.candidates),
            "candidates": [c.to_dict() for c in self.candidates],
            "warnings": self.warnings,
        }


def segment_questions(ir: DocumentIR, skip_pages: set[int] | None = None) -> SegmentationResult:
    """Detect question anchors from DocumentIR blocks.

    Args:
        ir: DocumentIR built from the PDF
        skip_pages: pages to ignore (cover, formulary, scoring)

    Returns:
        SegmentationResult with candidates and warnings
    """
    skip = skip_pages or set()
    result = SegmentationResult(exam_id=ir.exam_id)
    anchors: list[tuple[int, str, LayoutBlock, str]] = []  # (page, number, block, method)

    for page_ir in ir.pages:
        if page_ir.page in skip:
            continue

        for block in page_ir.blocks:
            if block.type != "text" or not block.text:
                continue

            text = block.text.strip()
            # Skip very short blocks that are likely labels
            if len(text) < 4:
                continue

            # Check first line only (question numbers are at the start)
            first_line = text.split("\n")[0].strip() if "\n" in text else text[:80]

            # Skip internal enumerations (1. superior, 2. igual, etc.)
            if _ENUM_INSIDE.match(first_line):
                continue

            # Sub-question (2.1, 3.2.1, etc.) — check before main to avoid
            # matching "2" from "2.1"
            m = _SUB_Q.match(first_line)
            if m:
                num = m.group(1)
                parent = num.rsplit(".", 1)[0]
                anchors.append((page_ir.page, num, block, "sub_question"))
                continue

            # Main question (1., 2., etc.)
            m = _MAIN_Q.match(first_line)
            if m:
                num = m.group(1)
                # Avoid matching page numbers, years, etc.
                if int(num) > 30:
                    continue
                anchors.append((page_ir.page, num, block, "main_question"))
                continue

            # Group (Grupo I, Grupo II, etc.)
            m = _GROUP.match(first_line)
            if m:
                anchors.append((page_ir.page, f"Grupo {m.group(1)}", block, "group"))
                continue

            # Item
            m = _ITEM.match(first_line)
            if m:
                anchors.append((page_ir.page, f"Item {m.group(1)}", block, "item"))
                continue

    # Build candidates with regions
    seen_numbers: set[str] = set()
    for i, (page, number, block, method) in enumerate(anchors):
        if number in seen_numbers:
            # Duplicate — lower confidence
            result.warnings.append({
                "type": "duplicate_anchor",
                "number": number,
                "page": page,
            })
            continue
        seen_numbers.add(number)

        # Region: from this anchor to the next anchor on the same page,
        # or to the bottom of the page
        page_ir = next((p for p in ir.pages if p.page == page), None)
        if not page_ir:
            continue

        y0 = block.bbox_pdf[1]
        y1 = page_ir.height  # default: bottom of page

        # Find next anchor on same page
        for j in range(i + 1, len(anchors)):
            next_page, _, next_block, _ = anchors[j]
            if next_page == page:
                y1 = next_block.bbox_pdf[1] - 2
                break
            elif next_page > page:
                break

        # Collect block IDs in this region
        block_ids = [
            b.id for b in page_ir.blocks
            if b.bbox_pdf[1] >= y0 - 5 and b.bbox_pdf[1] < y1
        ]

        parent = None
        if method == "sub_question":
            parent = number.rsplit(".", 1)[0]

        candidate = QuestionCandidate(
            number=number,
            page_start=page,
            page_end=page,  # TODO: multi-page questions
            bbox_pdf=(0, y0, page_ir.width, y1),
            block_ids=block_ids,
            confidence=0.92 if method in ("main_question", "sub_question") else 0.85,
            detection_method=method,
            parent_number=parent,
            is_group=(method == "group"),
        )
        result.candidates.append(candidate)

    return result
