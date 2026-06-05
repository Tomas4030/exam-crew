"""Normalizers: discipline-aware post-processing pipeline."""
from .common import normalize_common


def normalize_by_profile(output: dict, extraction: dict | None, profile: dict) -> dict:
    """Apply normalizers based on subject profile."""
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
        output = normalize_portugues(output, extraction)

    return output
