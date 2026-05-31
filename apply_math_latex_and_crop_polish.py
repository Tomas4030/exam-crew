from pathlib import Path
import re

ROOT = Path.cwd()
MATH_PATH = ROOT / 'pipeline' / 'src' / 'normalizers' / 'matematica.py'
CROPPER_PATH = ROOT / 'pipeline' / 'src' / 'utils' / 'cropper.py'

if not MATH_PATH.exists():
    raise SystemExit(f'Não encontrei {MATH_PATH}')
if not CROPPER_PATH.exists():
    raise SystemExit(f'Não encontrei {CROPPER_PATH}')

math_backup = MATH_PATH.with_suffix('.py.bak_math_latex_crop_polish')
if not math_backup.exists():
    math_backup.write_text(MATH_PATH.read_text(encoding='utf-8'), encoding='utf-8')

MATH_PATH.write_text(r'''"""Matemática normalizer: rules specific to Math exams."""
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
''', encoding='utf-8')

# Patch cropper: column clamp
crop_text = CROPPER_PATH.read_text(encoding='utf-8')
crop_backup = CROPPER_PATH.with_suffix('.py.bak_math_latex_crop_polish')
if not crop_backup.exists():
    crop_backup.write_text(crop_text, encoding='utf-8')

needle = '''        # Safety padding.
        pad_x = 14
        pad_top = 12
        pad_bottom = 10
        crop_rect = fitz.Rect(
'''
insert = '''        # Column clamp: if label is clearly in one column, don't extend into the other.
        page_mid = page_rect.width / 2
        if label_cx > page_mid * 1.08:
            crop_rect.x0 = max(crop_rect.x0, page_rect.width * 0.50)
            crop_rect.x1 = min(crop_rect.x1, page_rect.width * 0.985)
        elif label_cx < page_mid * 0.92:
            crop_rect.x0 = max(crop_rect.x0, page_rect.width * 0.015)
            crop_rect.x1 = min(crop_rect.x1, page_rect.width * 0.50)

        # Safety padding.
        pad_x = 14
        pad_top = 12
        pad_bottom = 10
        crop_rect = fitz.Rect(
'''
if needle in crop_text and 'Column clamp' not in crop_text:
    crop_text = crop_text.replace(needle, insert, 1)
    CROPPER_PATH.write_text(crop_text, encoding='utf-8')
    print('Patched cropper.py with column clamp')
else:
    print('Cropper: column clamp already present or block not found')

print(f'Backup: {math_backup}')
print(f'Backup: {crop_backup}')
print('Done. Reprocess the exam.')
