"""Common normalizers: universal rules safe for all disciplines."""
import re


_STMT_FIELDS = (
    "statement", "statementRaw", "statementLatex", "statementPlain",
    "rawText", "statementFormatted", "statementLatexFormatted", "statementPlainFormatted",
)


def normalize_common(output: dict, extraction: dict | None = None) -> dict:
    """Apply universal corrections safe for every discipline."""
    questions = output.get("questions", [])

    _ensure_fields(questions)
    _clean_control_chars(questions)
    _validate_asset_refs(output)

    return output


def _ensure_fields(questions: list[dict]):
    """Guarantee all questions have required list fields."""
    for q in questions:
        q.setdefault("imageRefs", [])
        q.setdefault("tableRefs", [])
        q.setdefault("assetRefs", [])
        q.setdefault("options", [])
        q.setdefault("warnings", [])
        q.setdefault("subQuestions", [])


def _clean_control_chars(questions: list[dict]):
    """Remove PDF control characters from all text fields."""
    _CONTROL_RE = re.compile(r'[\u0007\x07\ufeff]|\[\d+;\d+u')

    for q in questions:
        for field in _STMT_FIELDS:
            val = q.get(field)
            if isinstance(val, str):
                q[field] = _CONTROL_RE.sub('', val)


def _validate_asset_refs(output: dict):
    """Remove refs to assets that don't exist in the assets list."""
    asset_ids = {a.get("id") for a in output.get("assets", [])}

    for q in output.get("questions", []):
        q["imageRefs"] = [r for r in q.get("imageRefs", []) if r in asset_ids]
        q["assetRefs"] = [r for r in q.get("assetRefs", []) if r in asset_ids]
        q["tableRefs"] = [r for r in q.get("tableRefs", []) if r in asset_ids]
