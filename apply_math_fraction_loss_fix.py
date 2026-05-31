from pathlib import Path
import re

path = Path('pipeline/src/normalizers/matematica.py')
text = path.read_text(encoding='utf-8')
backup = path.with_suffix(path.suffix + '.bak_fraction_loss_fix')
if not backup.exists():
    backup.write_text(text, encoding='utf-8')

if '_repair_math_fraction_losses(output, extraction)' not in text:
    text = text.replace(
        '    _remove_non_visual_option_images(questions)\n',
        '    _repair_math_fraction_losses(output, extraction)\n'
        '    questions = output.get("questions", [])\n'
        '    _remove_non_visual_option_images(questions)\n',
        1,
    )

helper = r'''

# ── Math fraction / LaTeX repair ─────────────────────────────────────────────

def _wrap_inline_latex(latex: str) -> str:
    latex = str(latex or "").strip()
    if not latex:
        return ""
    if latex.startswith("\\(") or latex.startswith("$"):
        return latex
    return f"\\({latex}\\)"


def _latexize_using_math_spans(text: str, math_spans: list[dict]) -> str:
    if not isinstance(text, str) or not text:
        return text
    out = text
    for span in sorted(math_spans or [], key=lambda s: len(str(s.get("plain") or "")), reverse=True):
        plain = str(span.get("plain") or "").strip()
        latex = str(span.get("latex") or "").strip()
        if not plain or not latex:
            continue
        useful = ("\\frac" in latex or "\\sqrt" in latex or "^" in latex or "_" in latex or "/" in plain)
        if not useful:
            continue
        inline = _wrap_inline_latex(latex)
        if inline in out or latex in out:
            continue
        out = re.sub(rf"(?<!\w){re.escape(plain)}(?!\w)", inline, out, count=1)
    return out


def _native_vertical_fraction_replacements(q: dict) -> list[tuple[str, str, str]]:
    raw = str(q.get("sourceTextRaw") or "")
    if not raw:
        return []
    reps: list[tuple[str, str, str]] = []
    pat = re.compile(r"(?:^|\n)\s*[•\-–‒]\s*(\d{1,3})\s*\n\s*(\d{1,3})\s+([^\n;]{6,120};?)", re.I)
    for m in pat.finditer(raw):
        bottom = m.group(1).strip()
        top = m.group(2).strip()
        phrase = re.sub(r"\s+", " ", m.group(3)).strip()
        if not phrase or int(bottom) == 0:
            continue
        plain = f"{top}/{bottom}"
        latex = f"\\frac{{{top}}}{{{bottom}}}"
        reps.append((phrase, plain, latex))
    return reps


def _repair_missing_vertical_fractions_in_text(text: str, q: dict) -> str:
    if not isinstance(text, str) or not text:
        return text
    out = text
    for phrase, plain, latex in _native_vertical_fraction_replacements(q):
        inline = _wrap_inline_latex(latex)
        if plain in out or latex in out or inline in out:
            continue
        words = re.findall(r"\S+", phrase)
        if len(words) < 3:
            continue
        anchor = " ".join(words[:min(7, len(words))])
        anchor_pat = re.escape(anchor).replace(r"\ ", r"\s+")
        pat = re.compile(rf"([•\-–‒]\s*)(?:\\\(\s*\\\))?\s*(?={anchor_pat})", re.I)
        new, count = pat.subn(rf"\1{inline} ", out, count=1)
        if count:
            out = new
            continue
        pat2 = re.compile(rf"(?<!\w)({anchor_pat})", re.I)
        out = pat2.sub(rf"{inline} \1", out, count=1)
    return out


def _repair_math_fraction_losses(output: dict, extraction: dict | None = None):
    for q in output.get("questions", []):
        math_spans = q.get("mathSpans") or []
        for field in ("statement", "rawText", "statementRaw", "statementFormatted",
                      "statementPlain", "statementPlainFormatted"):
            val = q.get(field)
            if isinstance(val, str) and val:
                q[field] = _repair_missing_vertical_fractions_in_text(val, q)
        base = (q.get("statementLatexFormatted") or q.get("statementFormatted")
                or q.get("statementLatex") or q.get("statement") or "")
        if isinstance(base, str) and base:
            latex_text = _repair_missing_vertical_fractions_in_text(base, q)
            latex_text = _latexize_using_math_spans(latex_text, math_spans)
            if latex_text != base or "\\frac" in latex_text:
                q["statementLatex"] = latex_text
                q["statementLatexFormatted"] = latex_text
        for opt in q.get("options") or []:
            opt_text = str(opt.get("text") or "")
            opt_latex = str(opt.get("latex") or "")
            repaired = _latexize_using_math_spans(opt_latex or opt_text, math_spans)
            repaired = re.sub(r"\((-?1)\)\^n\s*/\s*n", r"\\(\\frac{(-1)^n}{n}\\)", repaired)
            repaired = re.sub(r"\((-?1)\)\^n\s*[×x]\s*n", r"\\((-1)^n \\times n\\)", repaired)
            if repaired and repaired != opt_text:
                opt["latex"] = repaired
'''

if '_repair_math_fraction_losses' not in text:
    text = text.rstrip() + helper + '\n'

path.write_text(text, encoding='utf-8')
print('OK: applied math fraction loss fix to', path)
print('Backup:', backup)
