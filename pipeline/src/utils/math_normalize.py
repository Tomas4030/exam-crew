"""math_normalize: normalizes mathematical text in questions.

Runs after normalize, before validate. For mathHeavy questions:
1. Detects corrupt/suspicious text from PDF extraction
2. Calls vision model to produce LaTeX-normalized statement
3. Generates statementPlain, statementLatex, mathSpans
4. Validates LaTeX structure
5. Sets textQuality per question
"""
import re
import time
import json
from pathlib import Path

from ..tools.vision_tool import _call_vision, _parse_json
from .progress import report_progress


# ── Corrupt text detection ────────────────────────────────────────

_CORRUPT_CHARS_RE = re.compile(r'[\x00-\x1f\ufffd]|(\[\d+;\d+u)')
_SUSPICIOUS_MATH_PATTERNS = [
    re.compile(r'[a-zA-Z]\s*\n\s*\d'),       # letter newline digit
    re.compile(r'\^\s*\^'),                    # double caret
    re.compile(r'u\s*\n\s*n'),                 # u_n split across lines
    re.compile(r'\s[b-z]\s[b-z]\s[b-z]\s'),   # spaced single chars (broken formula)
]


def has_corrupt_chars(text: str) -> bool:
    return bool(_CORRUPT_CHARS_RE.search(text))


def has_suspicious_math(text: str) -> bool:
    return any(p.search(text) for p in _SUSPICIOUS_MATH_PATTERNS)


def should_fallback_math_vision(q: dict) -> bool:
    text = q.get("statement", "") or ""
    one_char_tokens = len(re.findall(r'\b.\b', text))
    weird_hits = len(re.findall(r'[\ufffd□]|\[\d+;\d+u|n\s*\^\s*h', text))
    tq_status = (q.get("textQuality") or {}).get("status")
    return bool(
        q.get("mathHeavy", False)
        and (
            has_corrupt_chars(text)
            or has_suspicious_math(text)
            or weird_hits > 0
            or one_char_tokens > 10
            or tq_status not in (None, "ok")
        )
    )


def _text_quality_metrics(text: str) -> dict:
    tokens = re.findall(r'\S+', text or "")
    one_char = sum(1 for t in tokens if len(t) == 1)
    weird = len(re.findall(r'[\ufffd□]|\[\d+;\d+u|�', text or ""))
    math_struct = 1.0
    if tokens:
        math_struct = max(0.0, 1.0 - (one_char / len(tokens)))
    return {
        "oneCharTokenRatio": round((one_char / len(tokens)), 3) if tokens else 0.0,
        "weirdGlyphCount": weird,
        "mathStructureScore": round(math_struct, 3),
    }


# ── LaTeX validation ──────────────────────────────────────────────

def validate_latex(text: str) -> dict[str, bool]:
    if not text:
        return {}
    return {
        "balancedLatexDelimiters": text.count("\\(") == text.count("\\)"),
        "balancedParentheses": text.count("(") == text.count(")"),
        "noReplacementChars": not has_corrupt_chars(text),
        "balancedBraces": _braces_balanced(text),
        "hasLikelyLatex": bool(re.search(r'\\frac|\\sqrt|\\pi|\\in|\\mathbb|\\left|\\right|\^{', text)),
    }


def _braces_balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


# ── Plain text generation (strip LaTeX) ───────────────────────────

def latex_to_plain(text: str) -> str:
    """Convert LaTeX-annotated text to readable plain text."""
    s = text
    # Remove inline math delimiters
    s = s.replace("\\(", "").replace("\\)", "")
    # Common replacements
    replacements = [
        (r'\\frac\{([^}]*)\}\{([^}]*)\}', r'\1/\2'),
        (r'\\sqrt\{([^}]*)\}', r'√(\1)'),
        (r'\\overrightarrow\{([^}]*)\}', r'\1'),
        (r'\\left([(\[|])', r'\1'), (r'\\right([)\]|])', r'\1'),
        (r'\\cdot', '·'), (r'\\times', '×'), (r'\\leq', '≤'), (r'\\geq', '≥'),
        (r'\\pi', 'π'), (r'\\in', '∈'), (r'\\infty', '∞'), (r'\\alpha', 'α'),
        (r'\\beta', 'β'), (r'\\theta', 'θ'), (r'\\mathbb\{([^}]*)\}', r'\1'),
        (r'\^{([^}]*)}', r'^\1'), (r'_{([^}]*)}', r'_\1'),
    ]
    for pattern, repl in replacements:
        s = re.sub(pattern, repl, s)
    # Remove remaining backslash commands
    s = re.sub(r'\\[a-zA-Z]+', '', s)
    # Clean extra braces
    s = s.replace('{', '').replace('}', '')
    return s.strip()


def _latex_fractionize_text(text: str) -> str:
    """Convert simple numeric fractions to LaTeX fractions.

    Broad rules: only convert standalone integer/integer ratios outside dates,
    URLs and decimal numbers. This catches exam text like `3/5` and `3/10` while
    avoiding page markers such as `3/ 8` in raw headers because it runs on the
    cleaned statement fields, not on full page text.
    """
    if not text:
        return text

    def repl(m: re.Match) -> str:
        num, den = m.group(1), m.group(2)
        return f"\\(\\frac{{{num}}}{{{den}}}\\)"

    # Do not touch already-latexed \frac or inline math that already contains it.
    if "\\frac" in text:
        return text
    return re.sub(r"(?<![\w.])([0-9]{1,4})\s*/\s*([0-9]{1,4})(?![\w.])", repl, text)


def _apply_deterministic_math(q: dict) -> None:
    """Cheap normalization that runs even when vision normalization is skipped."""
    for field in ("statement", "rawText", "statementPlain", "statementLatex"):
        val = q.get(field)
        if isinstance(val, str) and re.search(r"(?<![\w.])\d{1,4}\s*/\s*\d{1,4}(?![\w.])", val):
            if field == "statementLatex":
                q[field] = _latex_fractionize_text(val)
            elif not q.get("statementLatex"):
                q["statementLatex"] = _latex_fractionize_text(val)

    if q.get("statementLatex"):
        q["statementPlain"] = q.get("statementPlain") or latex_to_plain(q["statementLatex"])
        existing = q.get("mathSpans") or []
        spans = extract_math_spans(q["statementLatex"])
        seen = {s.get("latex") for s in existing}
        q["mathSpans"] = existing + [s for s in spans if s.get("latex") not in seen]


# ── Extract math spans from LaTeX text ────────────────────────────

def extract_math_spans(latex_text: str) -> list[dict]:
    """Extract inline math spans from text with \\( ... \\) delimiters."""
    spans = []
    for m in re.finditer(r'\\\((.+?)\\\)', latex_text):
        latex_content = m.group(1)
        plain = latex_to_plain(latex_content)
        spans.append({"plain": plain, "latex": f"\\({latex_content}\\)", "confidence": 0.92})
    return spans


# ── Vision-based LaTeX normalization ──────────────────────────────

_NORMALIZE_PROMPT = """You are normalizing a Portuguese Mathematics exam question from an image.

Return ONLY strict JSON with these fields:
{{
  "statementLatex": "full question text with LaTeX inline math using \\\\( ... \\\\)",
  "options": [{{"letter": "A", "text": "plain text", "latex": "with \\\\( ... \\\\) if math"}}],
  "mathSpans": [{{"plain": "readable", "latex": "\\\\(...\\\\)", "confidence": 0.95}}]
}}

Rules:
- Preserve ALL text exactly as shown on the image
- Use \\\\( ... \\\\) for inline math ONLY for actual formulas/expressions
- Use \\\\frac{{}}{{}} for fractions, ^{{}} for exponents, \\\\sqrt{{}} for roots
- Use \\\\pi, \\\\in, \\\\mathbb{{R}}, \\\\leq, \\\\geq where appropriate
- Do NOT solve or simplify
- Keep Portuguese ordinals as plain text: 12.º, 1.ª, 2.ª, n.º — never use \\\\degree
- Do NOT wrap ordinary numbers, ages, years, percentages in math delimiters
- mathSpans: list each distinct formula/expression found
- If no options visible, return empty options array"""


def _normalize_question_via_vision(image_path: str, page_num: int, q_number: str) -> dict | None:
    """Call vision model to get LaTeX-normalized version of a question."""
    prompt = f"Extract question {q_number} from page {page_num}.\n\n{_NORMALIZE_PROMPT}"
    content = _call_vision(image_path, prompt, max_tokens=2048)
    return _parse_json(content) if content else None


# ── Main entry point ──────────────────────────────────────────────

def math_normalize(output: dict, extraction: dict, delay: float = 2.0) -> dict:
    """Run math normalization on all mathHeavy questions.

    Args:
        output: assembled exam output dict
        extraction: original PDF extraction with page image paths
        delay: seconds between API calls

    Returns:
        Modified output with statementPlain, statementLatex, mathSpans, textQuality populated.
    """
    subject = (output.get("metadata", {}).get("subject") or "").lower()
    is_math_exam = "matem" in subject or "fisica" in subject or "quimica" in subject

    # Skip entirely for non-math subjects (History, Portuguese, Geography, etc.)
    # These subjects have roman numerals, years, percentages that trigger false mathHeavy
    if not is_math_exam:
        report_progress("math_normalize", f"Skipping math_normalize for non-math subject: {subject or 'unknown'}")
        for q in output.get("questions", []):
            q["statementPlain"] = q.get("statementPlain") or q.get("statement", "")
            q["statementLatex"] = q.get("statementLatex") or q.get("statement", "")
            q["mathHeavy"] = False
            _set_text_quality(q, "ok", "pdf_text_raw")
        return output

    # Build page image lookup
    page_images = {p["page"]: p["page_image_path"] for p in extraction.get("pages", [])}

    questions = output.get("questions", [])
    normalized_count = 0
    warnings_generated = []

    for q in questions:
        if q.get("isGroup") and not q.get("statement"):
            # Groups without statements don't need normalization
            _set_text_quality(q, "ok", "not_applicable")
            continue

        statement = q.get("statement", "")
        is_math_heavy = q.get("mathHeavy", False)

        # Detect corrupt text
        corrupt = has_corrupt_chars(statement)
        suspicious = has_suspicious_math(statement) if is_math_exam else False
        needs_normalization = should_fallback_math_vision(q)

        # Skip normalization for questions that don't benefit from LaTeX rewriting
        if needs_normalization:
            skip_reasons = []
            if q.get("type") == "multi_blank_choice":
                skip_reasons.append("multi_blank_choice")
            if q.get("tableRefs"):
                skip_reasons.append("has_tableRefs")
            if q.get("blanks"):
                skip_reasons.append("has_blanks")
            # Bullets are common in Mathematics statements and must not block
            # deterministic fraction/LaTeX cleanup. The vision call may still be
            # skipped later for very long statements, but simple fixes run below.
            if "____" in statement:
                skip_reasons.append("has_blanks_text")
            if len(statement) > 900:
                skip_reasons.append("statement_too_long")
            if q.get("assetRefs") and re.search(r'[Ff]igura', statement):
                skip_reasons.append("has_figure_ref")
            if skip_reasons:
                needs_normalization = False

        if not needs_normalization:
            # Non-math or clean text: just set quality as ok
            raw_full = q.get("statementRaw") or q.get("rawText") or statement
            existing_latex = q.get("statementLatex") or ""

            # If statementLatex (from VLM extraction) is much shorter than the
            # raw text, the VLM truncated content (e.g. dropped table columns).
            content_ratio = len(existing_latex.strip()) / max(len(raw_full.strip()), 1)
            if existing_latex and content_ratio < 0.6:
                q["statementLatex"] = raw_full
                q["statementPlain"] = raw_full
            else:
                q["statementPlain"] = q.get("statementPlain") or statement
                q["statementLatex"] = q.get("statementLatex") or statement

            _apply_deterministic_math(q)
            _set_text_quality(q, "ok", "pdf_text_raw")
            continue

        # Try vision-based normalization
        page_num = q.get("sourcePage", 0)
        image_path = page_images.get(page_num)

        if not image_path or not Path(image_path).exists():
            # Can't normalize without image — mark for review
            q["statementPlain"] = statement
            q["statementLatex"] = statement
            _set_text_quality(q, "needs_review", "pdf_text_raw",
                              corrupt=corrupt, math_heavy=is_math_heavy)
            continue

        q_number = q.get("number", "")
        report_progress("math_normalize", f"Normalizing Q{q_number} (page {page_num})")

        result = _normalize_question_via_vision(image_path, page_num, q_number)
        time.sleep(delay)

        if result and result.get("statementLatex"):
            latex_stmt = result["statementLatex"]

            # If vision truncated content vs raw text, use raw instead
            raw_full = q.get("statementRaw") or q.get("rawText") or statement
            if raw_full and len(latex_stmt.strip()) < len(raw_full.strip()) * 0.6:
                latex_stmt = raw_full

            checks = validate_latex(latex_stmt)

            # If LaTeX is valid, use it
            if checks.get("balancedLatexDelimiters", True) and checks.get("balancedBraces", True):
                q["statementLatex"] = latex_stmt
                q["statementPlain"] = latex_to_plain(latex_stmt)
                _apply_deterministic_math(q)
                # Preserve original statement; frontend uses statementLatex for rendering

                # Math spans
                spans = result.get("mathSpans") or extract_math_spans(latex_stmt)
                q["mathSpans"] = spans

                # Options with latex
                if result.get("options") and q.get("options"):
                    for opt_new in result["options"]:
                        for opt_existing in q["options"]:
                            if opt_existing.get("letter") == opt_new.get("letter"):
                                opt_existing["latex"] = opt_new.get("latex")
                                break

                _set_text_quality(q, "ok", "vision_latex_normalized",
                                  has_latex=True, math_heavy=is_math_heavy, checks=checks)
                normalized_count += 1
            else:
                # LaTeX invalid — retry once
                report_progress("math_normalize", f"Q{q_number}: LaTeX invalid, retrying")
                time.sleep(delay)
                result2 = _normalize_question_via_vision(image_path, page_num, q_number)
                time.sleep(delay)

                if result2 and result2.get("statementLatex"):
                    latex_stmt2 = result2["statementLatex"]
                    checks2 = validate_latex(latex_stmt2)
                    if checks2.get("balancedLatexDelimiters", True) and checks2.get("balancedBraces", True):
                        q["statementLatex"] = latex_stmt2
                        q["statementPlain"] = latex_to_plain(latex_stmt2)
                        _apply_deterministic_math(q)
                        q["mathSpans"] = result2.get("mathSpans") or extract_math_spans(latex_stmt2)
                        if result2.get("options") and q.get("options"):
                            for opt_new in result2["options"]:
                                for opt_existing in q["options"]:
                                    if opt_existing.get("letter") == opt_new.get("letter"):
                                        opt_existing["latex"] = opt_new.get("latex")
                                        break
                        _set_text_quality(q, "ok", "vision_latex_normalized",
                                          has_latex=True, math_heavy=is_math_heavy, checks=checks2)
                        normalized_count += 1
                        continue

                # Both attempts failed
                q["statementPlain"] = statement
                q["statementLatex"] = latex_stmt  # Keep best attempt
                q["mathSpans"] = extract_math_spans(latex_stmt)
                _set_text_quality(q, "corrupt", "vision_latex_normalized",
                                  has_latex=True, math_heavy=is_math_heavy, checks=checks,
                                  requires_review=True)
                q["needsHumanReview"] = True
                warnings_generated.append({
                    "type": "math_normalization_failed",
                    "message": f"Q{q_number}: LaTeX normalization produced invalid structure",
                    "questionId": q.get("questionId"),
                })
        else:
            # Vision call failed entirely
            q["statementPlain"] = statement
            q["statementLatex"] = statement
            _set_text_quality(q, "corrupt", "pdf_text_raw",
                              corrupt=corrupt, math_heavy=is_math_heavy, requires_review=True)
            q["needsHumanReview"] = True
            warnings_generated.append({
                "type": "math_normalization_failed",
                "message": f"Q{q_number}: Vision normalization failed",
                "questionId": q.get("questionId"),
            })

    # Add warnings to output
    output.setdefault("warnings", []).extend(warnings_generated)

    report_progress("math_normalize", f"Normalized {normalized_count}/{len([q for q in questions if q.get('mathHeavy')])} math questions")
    return output


def _set_text_quality(q: dict, status: str, source: str, *,
                      corrupt: bool = False, has_latex: bool = False,
                      math_heavy: bool = False, requires_review: bool = False,
                      checks: dict = None):
    """Set textQuality on a question dict."""
    tq = {
        "status": status,
        "source": source,
        "hasCorruptChars": corrupt,
        "hasLatex": has_latex,
        "mathHeavy": math_heavy,
        "requiresMathReview": requires_review,
    }
    tq.update(_text_quality_metrics(q.get("statement", "") or ""))
    if checks:
        tq["checks"] = checks
    q["textQuality"] = tq
