"""Normalizers: discipline-aware post-processing pipeline."""
from __future__ import annotations

from pathlib import Path

from .common import normalize_common


def normalize_by_profile(
    output: dict,
    extraction: dict | None,
    profile: dict,
    output_dir: Path | None = None,
) -> dict:
    """Apply normalizers based on subject profile.

    Args:
        output_dir: absolute path to the exam output directory
            (e.g. ``{base}/data/output/{exam_id}``).  Required for normalizers
            that write files to disk (Portuguese text-source crops).
    """
    output = normalize_common(output, extraction)

    normalizers = profile.get("normalizers", ["common"])

    if "fisica_quimica" in normalizers:
        from .fisica_quimica import normalize_fq
        output = normalize_fq(output, extraction)

    if "matematica" in normalizers:
        from .matematica import normalize_math
        output = normalize_math(output, extraction)

    if "humanities" in normalizers:
        from .humanities import normalize_humanities
        output = normalize_humanities(output, extraction)

    if "portugues" in normalizers:
        from .portugues import normalize_portugues
        output = normalize_portugues(output, extraction, output_dir=output_dir)

    return output
