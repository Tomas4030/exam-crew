"""Match criteria items to exam questions.

Hierarchy (never invent a match):
    1. groupId + number (exact)
    2. unique (groupId + points)
    3. positional within group — all remaining unmatched in both sides aligned by order
    4. no match -> status unmatched, needsHumanReview

Positional fallback handles the pre-2018 format where Grupo II questions in the
exam are numbered with decimals (1.1, 1.2 … 1.7, 2.1 … 2.3) while the official
criteria PDFs use flat numbering (1, 2 … 10).  When every remaining unmatched
question in a group has a decimal number and every remaining unmatched criteria
item has a flat (integer) number, we align them positionally in sorted order.
"""
from __future__ import annotations

import re
from typing import Any


def _norm_num(value: Any) -> str:
    return str(value or "").strip().rstrip(".")


def _question_index(questions: list[dict]) -> dict[tuple[str, str], dict]:
    """Index by (groupId, number). Ungrouped exams (Matemática, FQ, línguas)
    use the empty string as a shared implicit group on both sides."""
    idx: dict[tuple[str, str], dict] = {}
    for q in questions:
        gid = str(q.get("groupId") or "").strip().lower()
        num = _norm_num(q.get("number") or q.get("displayNumber"))
        if num:
            idx[(gid, num)] = q
    return idx


def _sort_key(num_str: str) -> tuple[float, ...]:
    """Sort helper: '1.2' < '1.10' < '2' < '10'."""
    parts = re.split(r"[.\-]", num_str)
    try:
        return tuple(float(p) for p in parts if p)
    except ValueError:
        return (0.0,)


def _is_decimal_number(num: str) -> bool:
    """Return True for numbers like '1.1', '2.3' (at least one dot)."""
    return bool(re.match(r"^\d+\.\d+", num))


def _is_flat_number(num: str) -> bool:
    """Return True for plain integers like '1', '7', '10'."""
    return bool(re.match(r"^\d+$", num))


def match_criteria_to_questions(
    criteria_items: list[dict[str, Any]],
    questions: list[dict],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (matched_items, unmatched_question_ids).

    Each criteria item gets `questionId` and `match` ("exact"/"points"/"positional"/None).
    """
    by_group_number = _question_index(questions)
    matched_question_ids: set[str] = set()

    # ── Pass 1: exact match (groupId + number) ───────────────────────────────
    for item in criteria_items:
        gid = item["groupId"]
        num = _norm_num(item["number"])
        q = by_group_number.get((gid, num))
        if q is not None:
            item["questionId"] = q.get("questionId")
            item["match"] = "exact"
            item["status"] = "matched"
            matched_question_ids.add(q.get("questionId"))

    # ── Pass 2: unique question in same group with same points ────────────────
    for item in criteria_items:
        if item.get("status") == "matched":
            continue
        gid = item["groupId"]
        same_group_same_points = [
            cand for cand in questions
            if str(cand.get("groupId") or "").strip().lower() == gid
            and cand.get("points") == item.get("points")
            and cand.get("questionId") not in matched_question_ids
        ]
        if len(same_group_same_points) == 1:
            q = same_group_same_points[0]
            item["questionId"] = q.get("questionId")
            item["match"] = "points"
            item["status"] = "matched"
            matched_question_ids.add(q.get("questionId"))

    # ── Pass 3: positional fallback ────────────────────────────────────────────
    # Collect unmatched on both sides, per group.
    unmatched_criteria_by_group: dict[str, list[dict]] = {}
    for item in criteria_items:
        if item.get("status") == "matched":
            continue
        g = item["groupId"]
        unmatched_criteria_by_group.setdefault(g, []).append(item)

    unmatched_questions_by_group: dict[str, list[dict]] = {}
    for q in questions:
        if q.get("questionId") in matched_question_ids:
            continue
        g = str(q.get("groupId") or "").strip().lower()
        unmatched_questions_by_group.setdefault(g, []).append(q)

    for gid, crit_items in unmatched_criteria_by_group.items():
        exam_qs = unmatched_questions_by_group.get(gid, [])
        if len(crit_items) != len(exam_qs):
            continue  # counts must match for positional to be safe

        crit_nums = [_norm_num(it["number"]) for it in crit_items]
        exam_nums = [_norm_num(q.get("number") or q.get("displayNumber")) for q in exam_qs]

        # Only apply when criteria are flat integers and exam questions have decimal
        # numbers (pre-2018 Grupo II sub-numbering) OR when both sides are flat
        # integers (rarely needed but safe when counts match exactly).
        criteria_all_flat = all(_is_flat_number(n) for n in crit_nums)
        exam_all_decimal = all(_is_decimal_number(n) for n in exam_nums)
        exam_all_flat = all(_is_flat_number(n) for n in exam_nums)

        if not criteria_all_flat:
            continue
        if not (exam_all_decimal or exam_all_flat):
            continue

        # Sort both sides so the alignment is deterministic.
        sorted_crit = sorted(crit_items, key=lambda it: _sort_key(_norm_num(it["number"])))
        sorted_qs = sorted(exam_qs, key=lambda q: _sort_key(_norm_num(q.get("number") or q.get("displayNumber") or "")))

        for item, q in zip(sorted_crit, sorted_qs):
            item["questionId"] = q.get("questionId")
            item["match"] = "positional"
            item["status"] = "matched"
            item["needsHumanReview"] = True  # positional is best-effort; flag for review
            matched_question_ids.add(q.get("questionId"))

    # ── Mark remaining criteria items as unmatched ────────────────────────────
    for item in criteria_items:
        if item.get("status") != "matched":
            item["questionId"] = None
            item["match"] = None
            item["status"] = "unmatched"
            item["needsHumanReview"] = True

    unmatched_questions = [
        q.get("questionId")
        for q in questions
        if q.get("questionId") not in matched_question_ids
    ]
    return criteria_items, unmatched_questions
