"""Matemática normalizer: rules specific to Math exams."""
import re


def normalize_math(output: dict, extraction: dict | None = None) -> dict:
    """Apply Math-specific corrections.

    Math exams have:
    - Fractions like 3/5 that should become LaTeX
    - Geometric figures (vectors, not photos)
    - At most 2-level hierarchy (1.1, not 1.2.1)
    - No matching/COLUNA questions
    """
    questions = output.get("questions", [])

    _ensure_math_heavy_flags(questions)

    return output


def _ensure_math_heavy_flags(questions: list[dict]):
    """Mark questions with math content for LaTeX processing."""
    _MATH_INDICATORS = re.compile(
        r'\\frac|\\sqrt|\^{|_{|[=<>≤≥±×÷∈∞πθ]|'
        r'\b(sen|cos|tg|log|ln)\b|'
        r'\d+/\d+'
    )
    for q in questions:
        if q.get("mathHeavy") is not None:
            continue
        stmt = q.get("statement") or ""
        q["mathHeavy"] = bool(_MATH_INDICATORS.search(stmt))
