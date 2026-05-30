"""Humanities normalizer: rules for Português, História, Filosofia, Geografia."""


def normalize_humanities(output: dict, extraction: dict | None = None) -> dict:
    """Apply humanities-specific corrections.

    These subjects have:
    - Source grouping (Grupo I, Documento 1, etc.)
    - Text-based questions (no math, no figures to crop)
    - Essays and document analysis
    - No option images, no matching columns

    Most of the heavy lifting is done by source_grouping.py.
    This normalizer handles edge cases.
    """
    # Placeholder — source_grouping already runs in crew.py.
    # Future: migrate source-specific repairs here.
    return output
