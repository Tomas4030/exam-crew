"""Deterministic text formatting for extracted exam statements.

This module does not fix a single exam. It applies broad layout rules that are
common in Portuguese national exams: introductory sentence, "Sabe-se que:" /
"Considere que:", bullet lists and final instructions are rendered on separate
lines. The original `statement` is kept; this adds formatted fields for the UI.
"""
from __future__ import annotations

import re


_SECTION_STARTERS = (
    "Sabe-se que:",
    "Considere que:",
    "Admita que:",
    "Na sua resposta,",
    "Apresente o resultado",
    "Apresente a sua resposta",
    "Determine ",
    "Resolva ",
)


def _protect_latex_newlines(text: str) -> str:
    # Keep display blocks intact if the model already returned them.
    return text.replace("\\\\\n", "\\\\ __NL__ ")


def _restore_latex_newlines(text: str) -> str:
    return text.replace("\\\\ __NL__ ", "\\\\\n")


def format_statement_text(text: str | None) -> str:
    """Return a readable multi-line statement without changing its meaning."""
    if not text:
        return ""

    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = _protect_latex_newlines(s)

    # Collapse accidental spaces, but keep existing intentional line breaks.
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)

    # Put structural phrases on their own line.
    s = re.sub(r"\s+(Sabe-se que:)\s*", r"\n\1\n", s)
    s = re.sub(r"\s+(Considere que:|Admita que:)\s*", r"\n\1\n", s)

    # Each bullet starts a new line; avoids the current one-line blob.
    s = re.sub(r"\s*•\s*", "\n• ", s)
    s = re.sub(r";\s*\n•", ";\n•", s)

    # Common final instructions should not remain glued to the paragraph.
    s = re.sub(r"\s+(Apresente (?:o resultado|a sua resposta)[^.]*\.)", r"\n\1", s)
    s = re.sub(r"\s+(Na sua resposta,[^.]*\.)", r"\n\1", s)

    # Multiple-choice options, when present in statement text, each get a line.
    s = re.sub(r"\s+\(([A-D])\)\s*", r"\n(\1) ", s)

    # If the question number is embedded, separate it from the body.
    s = re.sub(r"^(\d+(?:\.\d+)?)\.\s+", r"\1. ", s.strip())

    # Clean spacing around newlines.
    lines = [line.strip() for line in s.split("\n")]
    s = "\n".join(line for line in lines if line)
    return _restore_latex_newlines(s)


def apply_text_formatting(output: dict) -> dict:
    """Format statement in-place; preserve original in statementRaw."""
    for q in output.get("questions", []):
        if q.get("statement"):
            q["statementRaw"] = q["statement"]
            formatted = format_statement_text(q["statement"])
            q["statement"] = formatted
            q["statementFormatted"] = formatted
        if q.get("statementPlain"):
            q["statementPlainFormatted"] = format_statement_text(q["statementPlain"])
        if q.get("statementLatex"):
            q["statementLatexFormatted"] = format_statement_text(q["statementLatex"])
    return output
