"""Matemática normalizer: rules specific to Math exams."""
import re


def normalize_math(output: dict, extraction: dict | None = None) -> dict:
    """Apply Math-specific corrections."""
    questions = output.get("questions", [])
    _drop_sfi_duplicate_questions(output, extraction)
    questions = output.get("questions", [])
    _remove_fake_math_subquestions_and_recover_parents(output, extraction)
    questions = output.get("questions", [])
    _remove_non_visual_option_images(questions)
    _attach_figures_by_same_page_mentions(output)
    _ensure_math_heavy_flags(questions)
    _sort_questions(output)
    return output


def _page_texts(extraction: dict | None) -> dict[int, str]:
    if not extraction:
        return {}
    return {int(p.get("page")): (p.get("text") or "") for p in extraction.get("pages", []) if p.get("page") is not None}


def _drop_sfi_duplicate_questions(output: dict, extraction: dict | None):
    """Remove questions from SFI/accessibility duplicate pages."""
    texts = _page_texts(extraction)
    if not texts:
        return
    sfi_markers = ("sem figuras", "entrelinha 1,5", "entrelinha 1.5", "/sfi")
    first_sfi = None
    for page_num, text in sorted(texts.items()):
        low = text.lower()
        if any(m in low for m in sfi_markers):
            first_sfi = page_num
            break
    if not first_sfi:
        return
    before_has_questions = any(p < first_sfi and re.search(r"(?m)^\s*\d{1,2}\.\s+", t) for p, t in texts.items())
    if not before_has_questions:
        return
    kept, removed = [], []
    for q in output.get("questions", []):
        page = q.get("sourcePage")
        if isinstance(page, int) and page >= first_sfi:
            removed.append(str(q.get("number", "")))
        else:
            kept.append(q)
    if removed:
        output["questions"] = kept
        output.setdefault("warnings", []).append({
            "type": "math_sfi_duplicate_removed",
            "message": f"Removed {len(removed)} duplicate SFI question(s)"
        })


def _native_has_question_number(page_text: str, number: str) -> bool:
    number = str(number).strip()
    if not number:
        return False
    pat = re.compile(rf"(?m)(?:^|\n)\s*{re.escape(number)}\.?\s+")
    return bool(pat.search(page_text or ""))


def _extract_question_block_from_native_text(page_text: str, number: str) -> str | None:
    major = str(number).split(".")[0]
    try:
        next_major = str(int(major) + 1)
    except Exception:
        return None
    pat = re.compile(rf"(?ms)(?:^|\n)\s*{re.escape(major)}\.\s*(.*?)(?=\n\s*{next_major}\.\s+|\Z)")
    m = pat.search(page_text or "")
    if not m:
        return None
    block = m.group(1).strip()
    block = re.sub(r"(?m)^Prova\s+635/.*$", "", block).strip()
    return block if len(block) >= 20 else None


def _question_id(number: str) -> str:
    return "q" + str(number).replace(".", "_")


def _remove_fake_math_subquestions_and_recover_parents(output: dict, extraction: dict | None):
    """Remove subquestions not present in native PDF text and recover parents."""
    texts = _page_texts(extraction)
    if not texts:
        return
    questions = output.get("questions", [])
    invalid = []
    for q in questions:
        num = str(q.get("number", "")).strip()
        if "." not in num:
            continue
        page = q.get("sourcePage")
        page_text = texts.get(page, "")
        if page_text and not _native_has_question_number(page_text, num):
            invalid.append(q)
    if not invalid:
        return
    invalid_nums = {str(q.get("number", "")).strip() for q in invalid}
    invalid_parent_nums = sorted({n.split(".")[0] for n in invalid_nums if n})
    output["questions"] = [q for q in questions if str(q.get("number", "")).strip() not in invalid_nums]
    for q in output["questions"]:
        if q.get("subQuestions"):
            q["subQuestions"] = [cid for cid in q["subQuestions"] if not any(cid == _question_id(n) for n in invalid_nums)]
    existing_nums = {str(q.get("number", "")).strip() for q in output["questions"]}
    for parent_num in invalid_parent_nums:
        if parent_num in existing_nums:
            parent = next((q for q in output["questions"] if str(q.get("number")) == parent_num), None)
            if parent and parent.get("type") == "group" and not parent.get("subQuestions"):
                parent["type"] = "calculation"
                parent["isGroup"] = False
            continue
        child = next((q for q in invalid if str(q.get("number", "")).startswith(parent_num + ".")), None)
        if not child:
            continue
        page = child.get("sourcePage")
        page_text = texts.get(page, "")
        block = _extract_question_block_from_native_text(page_text, parent_num)
        if not block:
            block = max((q.get("statement") or "" for q in invalid if str(q.get("number", "")).startswith(parent_num + ".")), key=len, default="")
        if not block:
            continue
        new_q = {
            "questionId": _question_id(parent_num),
            "number": parent_num,
            "type": "calculation",
            "sourcePage": page,
            "statement": block,
            "rawText": block,
            "blanks": None,
            "options": [],
            "imageRefs": [],
            "tableRefs": [],
            "assetRefs": [],
            "visualDependency": bool(re.search(r"Figura\s+\d+", block, re.I)),
            "confidence": 0.82,
            "needsHumanReview": True,
            "warnings": [{"type": "math_recovered_parent", "message": f"Recovered Q{parent_num}"}],
            "parentQuestion": None,
            "subQuestions": [],
            "mathHeavy": True,
            "hasGraph": bool(re.search(r"Figura\s+\d+", block, re.I)),
            "hasDiagram": False,
            "hasTable": False,
            "calculatorAllowed": None,
        }
        output["questions"].append(new_q)


def _statement_has_visual_option_cue(text: str) -> bool:
    return bool(re.search(
        r"\b(diagramas?|gráficos?|graficos?|esboços?|esbocos?|curvas?|"
        r"opção\s+que\s+apresenta|opcao\s+que\s+apresenta|"
        r"forças\s+que\s+atuam|forcas\s+que\s+atuam|representar\s+as\s+forças)\b",
        text or "", re.I
    ))


def _remove_non_visual_option_images(questions: list[dict]):
    """Remove imageUrl from options when the question is not visual."""
    for q in questions:
        if q.get("type") != "multiple_choice":
            continue
        stmt = " ".join(str(q.get(f) or "") for f in ("statement", "rawText", "statementPlain"))
        if _statement_has_visual_option_cue(stmt):
            continue
        for opt in q.get("options") or []:
            opt.pop("imageUrl", None)
            opt.pop("imageAssetId", None)
        q.pop("hasOptionImages", None)


def _attach_figures_by_same_page_mentions(output: dict):
    """Attach figure assets to questions that mention them on the same page."""
    assets = output.get("assets", [])
    fig_assets: dict[tuple[str, int], dict] = {}
    for a in assets:
        aid = str(a.get("id") or "")
        m = re.match(r"figura_(\d+)_p(\d+)", aid)
        if not m:
            continue
        fig_assets[(m.group(1), int(m.group(2)))] = a
    for q in output.get("questions", []):
        text = " ".join(str(q.get(f) or "") for f in ("statement", "rawText", "statementPlain"))
        page = q.get("sourcePage")
        if not isinstance(page, int):
            continue
        for fig_num in set(re.findall(r"[Ff]igura\s+(\d+)", text)):
            asset = fig_assets.get((fig_num, page))
            if not asset:
                continue
            aid = asset["id"]
            if aid not in q.setdefault("imageRefs", []):
                q["imageRefs"].append(aid)
            if aid not in q.setdefault("assetRefs", []):
                q["assetRefs"].append(aid)
            q["visualDependency"] = True


def _ensure_math_heavy_flags(questions: list[dict]):
    """Mark questions with math content."""
    _MATH_RE = re.compile(r"[=<>≤≥±×÷∈∞πθ]|\b(sen|cos|tg|log|ln)\b|\d+/\d+|\\frac|\\sqrt")
    for q in questions:
        if q.get("mathHeavy") is None:
            q["mathHeavy"] = bool(_MATH_RE.search(q.get("statement") or ""))


def _sort_questions(output: dict):
    """Sort questions by page and number."""
    def key(q):
        parts = []
        for p in str(q.get("number", "999")).split("."):
            try:
                parts.append(int(p))
            except Exception:
                parts.append(999)
        return (int(q.get("sourcePage") or 999), parts)
    output["questions"].sort(key=key)
