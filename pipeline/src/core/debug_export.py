"""Debug export: save intermediate IR and candidates as JSON for inspection."""
from __future__ import annotations

import json
from pathlib import Path

from .layout_ir import DocumentIR
from .question_segmenter import SegmentationResult


def export_debug(
    output_dir: Path,
    document_ir: DocumentIR | None = None,
    segmentation: SegmentationResult | None = None,
) -> None:
    """Save debug artifacts to output_dir/debug/."""
    debug_dir = output_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    if document_ir:
        path = debug_dir / "document_ir.json"
        path.write_text(
            json.dumps(document_ir.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    if segmentation:
        path = debug_dir / "question_candidates.json"
        path.write_text(
            json.dumps(segmentation.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
