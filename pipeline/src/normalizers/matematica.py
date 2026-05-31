"""Matemática normalizer: rules specific to Math exams."""
from __future__ import annotations
import re

_TEXT_FIELDS = ("statement","statementPlain","statementFormatted","statementPlainFormatted","statementLatex","statementLatexFormatted","rawText")
_MATH_INDICATORS = re.compile(r"\\frac|\\sqrt|\^{|_{|[=<>≤≥±×÷∈∞πθΩ∅∪∩]|\b(sen|cos|tg|log|ln|lim)\b|\d+\s*/\s*\d+|\(-?1\)\^n", re.I)
_VISUAL_OPTION_PROMPT = re.compile(r"\b(diagramas?|gráficos?|graficos?|figuras?|esboços?|esbocos?|curvas?)\b|qual\s+dos\s+seguintes\s+(diagramas|gráficos|graficos|esboços|esbocos)", re.I)
_SIMPLE_TEXT_OPTION = re.compile(r"^\s*(?:[+-]?\d+(?:[,.]\d+)?\s*(?:m|cm|%|pontos?)?|[A-Za-z0-9π∞Ω∅∪∩+\-−×*/^(),.\s]+)\s*$", re.I)


def normalize_math(output: dict, extraction: dict | None = None) -> dict:
    questions = output.get("questions", []) or []
    _ensure_math_heavy_flags(questions)
    _latexify_math_text(questions)
    _repair_math_fraction_losses(output, extraction)
    questions = output.get("questions", [])
    _remove_non_visual_option_images(questions)
    _remove_group_parent_options(questions)
    _remove_fake_math_subquestions(output, extraction)
    _associate_figures_same_page(output)
    return output


def _ensure_math_heavy_flags(questions: list[dict]):
    for q in questions:
        if q.get("mathHeavy") is None:
            q["mathHeavy"] = bool(_MATH_INDICATORS.search(q.get("statement") or ""))


def _latexify_math_text(questions: list[dict]):
    for q in questions:
        for opt in q.get("options") or []:
            text = str(opt.get("text") or "").strip()
            if not text:
                continue
            latex = _option_to_latex(text)
            if latex:
                opt["latex"] = latex
        for field in ("statement", "statementPlain", "statementFormatted"):
            value = q.get(field)
            if isinstance(value, str) and value.strip():
                rendered = _inline_math_to_latex(value)
                if rendered != value:
                    q["statementLatexFormatted"] = rendered
                break


def _option_to_latex(text: str) -> str | None:
    t = text.strip().replace("\u2212", "-")
    if re.fullmatch(r"\(?-?1\)?\^n\s*/\s*n", t):
        return r"\(\frac{(-1)^n}{n}\)"
    m = re.fullmatch(r"\(?-?1\)?\^n\s*([×*+\-])\s*n", t)
    if m:
        op = r"\times" if m.group(1) in ("×", "*") else m.group(1)
        return rf"\((-1)^n {op} n\)"
    m = re.fullmatch(r"([+-]?\d+)\s*/\s*(\d+)", t)
    if m:
        return rf"\(\frac{{{m.group(1)}}}{{{m.group(2)}}}\)"
    if _MATH_INDICATORS.search(t) and len(t) <= 80:
        return "\\(" + _latex_escape_light(t) + "\\)"
    return None


def _inline_math_to_latex(text: str) -> str:
    t = text
    protected: list[str] = []
    def protect(m: re.Match) -> str:
        protected.append(m.group(0))
        return f"@@MATH{len(protected)-1}@@"
    t = re.sub(r"\\\([\s\S]*?\\\)", protect, t)
    t = re.sub(r"(?<![\w/])([+-]?\d+)\s*/\s*(\d+)(?![\w/])",
               lambda m: rf"\(\frac{{{m.group(1)}}}{{{m.group(2)}}}\)", t)
    t = re.sub(r"\(-?1\)\^n\s*/\s*n", r"\\(\\frac{(-1)^n}{n}\\)", t)
    for i, original in enumerate(protected):
        t = t.replace(f"@@MATH{i}@@", original)
    return t


def _latex_escape_light(text: str) -> str:
    t = text.strip()
    t = t.replace("×", r"\times").replace("\u2212", "-").replace("π", r"\pi")
    t = t.replace("∞", r"\infty").replace("∈", r"\in").replace("∅", r"\varnothing")
    return t


def _remove_non_visual_option_images(questions: list[dict]):
    for q in questions:
        opts = q.get("options") or []
        if q.get("type") != "multiple_choice" or not opts:
            continue
        text = "\n".join(str(q.get(k) or "") for k in ("statement", "statementPlain", "rawText"))
        if _VISUAL_OPTION_PROMPT.search(text):
            continue
        simple_count = sum(1 for o in opts if _SIMPLE_TEXT_OPTION.match(str(o.get("text") or "")))
        if simple_count >= max(2, len(opts) - 1):
            for opt in opts:
                opt.pop("imageUrl", None)
                opt.pop("imageAssetId", None)
            q["hasOptionImages"] = False


def _remove_group_parent_options(questions: list[dict]):
    for q in questions:
        if q.get("type") == "group" or q.get("isGroup"):
            q["options"] = []
            q["blanks"] = None


def _remove_fake_math_subquestions(output: dict, extraction: dict | None):
    if not extraction:
        return
    text = "\n".join(str(p.get("text") or "") for p in extraction.get("pages", []))
    if not text:
        return
    questions = output.get("questions", []) or []
    valid, removed_ids = [], set()
    for q in questions:
        num = str(q.get("number") or "").strip()
        if re.fullmatch(r"\d+\.\d+", num):
            pat = re.compile(rf"(?m)(?:^|\n)\s*{re.escape(num)}\.\s+")
            if not pat.search(text):
                removed_ids.add(str(q.get("questionId") or ""))
                continue
        valid.append(q)
    if not removed_ids:
        return
    output["questions"] = valid
    for q in valid:
        if q.get("parentQuestion") in removed_ids:
            q["parentQuestion"] = None
        if q.get("subQuestions"):
            q["subQuestions"] = [c for c in q["subQuestions"] if c not in removed_ids]
        if q.get("type") == "group" and not q.get("subQuestions"):
            q["type"] = "calculation"
            q["isGroup"] = False


def _associate_figures_same_page(output: dict):
    assets = output.get("assets", []) or []
    questions = output.get("questions", []) or []
    fig_assets: dict[tuple[str, int], dict] = {}
    for a in assets:
        m = re.match(r"figura_(\d+)_p(\d+)", str(a.get("id") or ""), re.I)
        if m:
            fig_assets[(m.group(1), int(m.group(2)))] = a
    for q in questions:
        text = " ".join(str(q.get(f) or "") for f in ("statement", "rawText", "statementPlain"))
        page = int(q.get("sourcePage") or 0)
        if not page:
            continue
        for fig_num in set(re.findall(r"Figura\s+(\d+)", text, re.I)):
            asset = fig_assets.get((fig_num, page))
            if not asset:
                continue
            aid = asset["id"]
            if aid not in q.setdefault("imageRefs", []):
                q["imageRefs"].append(aid)
            if aid not in q.setdefault("assetRefs", []):
                q["assetRefs"].append(aid)
            q["visualDependency"] = True


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
    """Repair lost fractions using sourceTextRaw + mathSpans."""
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
