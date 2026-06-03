from __future__ import annotations

import re
from collections import defaultdict


_DOC_EXCERPT_PATTERNS = (
    r"^\s*\d+\.\s*-\s*",
    r"^\s*\d+\.º\s*[-–]",
    r"^\s*dizem que\b",
    r"^\s*pedem-nos\b",
    r"^\s*e por que\b",
    r"^\s*reiteraram\b",
    r"^\s*no âmbito da\b",
    r"^\s*ainda no âmbito da\b",
)


def cleanup_history_questions(output: dict) -> dict:
    if not _is_probably_history_output(output):
        return output

    questions = output.get("questions") or []
    if not questions:
        return output

    by_group_number: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for q in questions:
        group = str(q.get("groupId") or q.get("group") or "")
        number = str(q.get("number") or "").strip()
        if group and number:
            by_group_number[(group, number)].append(q)

    strong_numbers_by_group: dict[str, set[int]] = defaultdict(set)
    for q in questions:
        group = str(q.get("groupId") or q.get("group") or "")
        number = str(q.get("number") or "")
        if not group or not number.isdigit():
            continue
        if _is_strong_question(q):
            strong_numbers_by_group[group].add(int(number))

    removed = 0
    kept: list[dict] = []
    seen_ids: set[int] = set()
    for key, candidates in by_group_number.items():
        group, number = key
        best = max(candidates, key=_question_quality_score)
        for q in candidates:
            if q is not best:
                removed += 1
        if _is_out_of_range_doc_excerpt(best, strong_numbers_by_group.get(group, set())):
            removed += 1
            continue
        kept.append(best)
        seen_ids.add(id(best))

    for q in questions:
        if id(q) in seen_ids:
            continue
        group = str(q.get("groupId") or q.get("group") or "")
        number = str(q.get("number") or "")
        if group and number and (group, number) in by_group_number:
            continue
        if _is_out_of_range_doc_excerpt(q, strong_numbers_by_group.get(group, set())):
            removed += 1
            continue
        kept.append(q)

    if not removed:
        return output

    kept.sort(key=_sort_key)
    output["questions"] = kept
    output.setdefault("warnings", []).append({
        "type": "history_question_cleanup",
        "message": f"Removed {removed} duplicated/document-excerpt question candidate(s).",
    })
    _refresh_stats(output)
    return output


def _is_probably_history_output(output: dict) -> bool:
    metadata = output.get("metadata") or {}
    marker = f"{metadata.get('subject') or ''} {metadata.get('title') or ''} {output.get('exam_id') or ''}".lower()
    if "hist" in marker:
        return True

    sources = output.get("sources") or []
    source_marker = " ".join(
        str(src.get(key) or "")
        for src in sources
        if isinstance(src, dict)
        for key in ("id", "label", "title", "type")
    ).lower()
    if sources and ("doc" in source_marker or "documento" in source_marker):
        return True

    questions = output.get("questions") or []
    group_ids = {str(q.get("groupId") or q.get("group") or "").lower() for q in questions}
    has_roman_groups = any(group.startswith("grupo_") for group in group_ids)
    has_source_refs = any(q.get("sourceRefs") for q in questions)
    return has_roman_groups and has_source_refs


def _question_quality_score(q: dict) -> int:
    warnings = {w.get("type") for w in q.get("warnings", []) if isinstance(w, dict)}
    score = 0
    if "text_fallback_extracted" not in warnings:
        score += 100
    if q.get("points") is not None:
        score += 60
    if q.get("type") == "multiple_choice" and len(q.get("options") or []) >= 2:
        score += 90
    if q.get("type") == "multi_select" and len(q.get("options") or []) >= 3:
        score += 90
    if q.get("type") == "multi_blank_choice" and q.get("blanks"):
        score += 90
    if q.get("sourceRefs"):
        score += 25
    if q.get("media"):
        score += 20
    if _looks_like_doc_excerpt(q):
        score -= 120
    if "text_fallback_extracted" in warnings:
        score -= 40
    if not _is_strong_question(q):
        score -= 30
    return score


def _is_strong_question(q: dict) -> bool:
    if q.get("points") is not None:
        return True
    if q.get("type") == "multiple_choice" and len(q.get("options") or []) >= 2:
        return True
    if q.get("type") == "multi_select" and len(q.get("options") or []) >= 3:
        return True
    if q.get("type") == "multi_blank_choice" and q.get("blanks"):
        return True
    if q.get("sourceRefs") and not _looks_like_doc_excerpt(q):
        return True
    return False


def _is_out_of_range_doc_excerpt(q: dict, strong_numbers: set[int]) -> bool:
    number = str(q.get("number") or "")
    if not number.isdigit() or not strong_numbers:
        return False
    max_strong = max(strong_numbers)
    return int(number) > max_strong and _looks_like_doc_excerpt(q)


def _looks_like_doc_excerpt(q: dict) -> bool:
    text = str(q.get("statement") or q.get("rawText") or "").strip().lower()
    if not text:
        return False
    has_no_answer_shape = (
        q.get("points") is None
        and not (q.get("options") or [])
        and not (q.get("blanks") or [])
        and not (q.get("sourceRefs") or [])
    )
    starts_like_source_line = any(re.search(pattern, text) for pattern in _DOC_EXCERPT_PATTERNS)
    if starts_like_source_line and has_no_answer_shape:
        return True
    if len(text) > 220 and has_no_answer_shape and not re.search(r"\b(compare|explique|refira|indique|ordene|associe|desenvolva|complete|transcreva)\b", text):
        return True
    return False


def _sort_key(q: dict) -> tuple:
    number = str(q.get("number") or "")
    try:
        n = int(number.split(".", 1)[0])
    except ValueError:
        n = 999
    return (
        q.get("sourcePage") or 999,
        str(q.get("groupId") or q.get("group") or ""),
        n,
        number,
    )


def _refresh_stats(output: dict) -> None:
    questions = output.get("questions") or []
    groups = [q for q in questions if q.get("isGroup")]
    non_group = [q for q in questions if not q.get("isGroup")]
    main_qs = [q for q in non_group if not q.get("parentQuestion")]
    sub_qs = [q for q in non_group if q.get("parentQuestion")]
    output.setdefault("metadata", {})["stats"] = {
        "mainQuestions": len(main_qs) + len(groups),
        "answerableItems": len(non_group),
        "jsonNodes": len(questions),
        "groups": len(groups),
        "subQuestions": len(sub_qs),
    }
