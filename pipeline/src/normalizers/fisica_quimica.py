"""Física e Química normalizer: rules specific to FQ exams."""
import re


def normalize_fq(output: dict, extraction: dict | None = None) -> dict:
    """Apply FQ-specific corrections."""
    questions = output.get("questions", [])
    assets = output.get("assets", [])

    _detect_matching(questions)
    _repair_multiblank(questions)
    _strip_phantom_tables(questions)
    _fix_group_asset_inheritance(questions)

    return output


def _detect_matching(questions: list[dict]):
    """Detect COLUNA I / COLUNA II questions and structure as matching."""
    for q in questions:
        stmt = q.get("rawText") or q.get("statement") or ""
        if not (re.search(r'\bCOLUNA\s+I\b', stmt, re.I) and
                re.search(r'\bCOLUNA\s+II\b', stmt, re.I)):
            continue

        q["type"] = "matching"
        q["options"] = []
        q["blanks"] = None

        left = re.findall(r'\(([a-e])\)\s*([^\n(]+)', stmt, flags=re.I)
        right = re.findall(r'\((\d+)\)\s*([^\n(]+)', stmt)

        seen_l, seen_r = set(), set()
        left_items, right_items = [], []
        for k, v in left:
            k = k.strip().lower()
            if k not in seen_l:
                seen_l.add(k)
                left_items.append({"key": k, "text": v.strip()})
        for k, v in right:
            k = k.strip()
            if k not in seen_r:
                seen_r.add(k)
                right_items.append({"key": k, "text": v.strip()})

        if left_items and right_items:
            q["matchColumns"] = {"left": left_items, "right": right_items}


def _repair_multiblank(questions: list[dict]):
    """Clean multi_blank_choice statements: remove option bank from text."""
    for q in questions:
        if q.get("type") != "multi_blank_choice" or not q.get("blanks"):
            continue
        for field in ("statement", "statementPlain", "statementFormatted"):
            val = q.get(field)
            if not isinstance(val, str):
                continue
            # Remove numbered option lines
            val = re.sub(r'(?m)^\s*[1-5]\.\s+.+$', '', val).strip()
            # Remove a) b) c) d) header
            val = re.sub(r'\ba\)\s*b\)\s*c\)\s*d\)?\s*$', '', val, flags=re.I).strip()
            q[field] = val


def _strip_phantom_tables(questions: list[dict]):
    """Remove table refs from questions that don't mention tables."""
    _TABLE_WORDS = re.compile(r'tabela|medições|medidas|apresentam-se|coluna\s+[iI]', re.I)
    for q in questions:
        if not q.get("tableRefs"):
            continue
        text = (q.get("statement") or "") + " " + (q.get("rawText") or "")
        if not _TABLE_WORDS.search(text):
            q["tableRefs"] = []
            q["assetRefs"] = [a for a in q.get("assetRefs", []) if "tabela" not in a.lower()]
            q["hasTable"] = False


def _fix_group_asset_inheritance(questions: list[dict]):
    """Groups should not own assets from child pages."""
    by_id = {q.get("questionId"): q for q in questions}

    for parent in questions:
        if not parent.get("isGroup") and parent.get("type") != "group":
            continue
        children_ids = parent.get("subQuestions") or []
        children = [by_id[cid] for cid in children_ids if cid in by_id]
        if not children:
            continue

        parent_page = parent.get("sourcePage", 0)
        child_pages = {c.get("sourcePage") for c in children if c.get("sourcePage")}

        # If children span multiple pages, parent only keeps assets from its own page
        if parent_page and child_pages - {parent_page}:
            parent["imageRefs"] = [r for r in parent.get("imageRefs", []) if f"_p{parent_page}" in r]
            parent["tableRefs"] = [r for r in parent.get("tableRefs", []) if f"_p{parent_page}" in r]
            parent["assetRefs"] = [r for r in parent.get("assetRefs", []) if f"_p{parent_page}" in r]
