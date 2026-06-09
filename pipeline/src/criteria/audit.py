"""Audit a built criteria document against the exam.

Blockers (per the guide §14) escalate the criteria document to needs_review:
    CRITERIA_GROUP_MISSING   — an exam group has no criteria items
    CRITERIA_ITEM_MISSING    — an exam question has no matching criteria item
    CRITERIA_MC_NO_ANSWER    — a multiple-choice criteria item lacks a correct answer
    CRITERIA_POINTS_MISMATCH — criteria points differ from exam-question points
"""
from __future__ import annotations

from typing import Any

BLOCKER_CODES = {
    "CRITERIA_GROUP_MISSING",
    "CRITERIA_ITEM_MISSING",
    "CRITERIA_MC_NO_ANSWER",
    "CRITERIA_POINTS_MISMATCH",
}


def audit_criteria(
    items: list[dict[str, Any]],
    questions: list[dict],
    unmatched_question_ids: list[str],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    # Group coverage: every exam group should have at least one criteria item.
    exam_groups = {str(q.get("groupId") or "").strip().lower() for q in questions if q.get("groupId")}
    criteria_groups = {it["groupId"] for it in items}
    for gid in sorted(exam_groups - criteria_groups):
        issues.append({
            "code": "CRITERIA_GROUP_MISSING",
            "severity": "high",
            "message": f"Grupo '{gid}' existe no exame mas não tem critérios extraídos.",
        })

    # Question coverage. Distinguish a genuine criteria gap (a well-formed,
    # unique question with no criteria) from exam-extraction artifacts (orphan
    # questions with no group, or duplicates of an already-matched question).
    q_by_id = {q.get("questionId"): q for q in questions}
    matched_group_numbers = {
        (str(q.get("groupId") or "").strip().lower(), str(q.get("number") or "").strip().rstrip("."))
        for q in questions
        if q.get("questionId") not in set(unmatched_question_ids)
    }
    for qid in unmatched_question_ids:
        q = q_by_id.get(qid) or {}
        gid = str(q.get("groupId") or "").strip().lower()
        num = str(q.get("number") or "").strip().rstrip(".")
        if not gid:
            issues.append({
                "code": "CRITERIA_QUESTION_NOT_GROUPED",
                "severity": "medium",
                "message": (
                    f"Pergunta '{qid}' (nº {num}) sem grupo — provável artefacto/duplicado "
                    f"da extração do enunciado, não há critério para associar."
                ),
            })
        elif (gid, num) in matched_group_numbers:
            issues.append({
                "code": "CRITERIA_QUESTION_DUPLICATE",
                "severity": "medium",
                "message": f"Pergunta '{qid}' duplica {gid} nº {num} (já associada) — provável duplicado.",
            })
        else:
            issues.append({
                "code": "CRITERIA_ITEM_MISSING",
                "severity": "high",
                "message": f"Pergunta '{qid}' ({q.get('groupId')} nº {num}) sem critério correspondente.",
            })

    # Per-item checks.
    for it in items:
        if it["type"] == "multiple_choice":
            ca = it.get("correctAnswer") or {}
            if not ca.get("v1"):
                issues.append({
                    "code": "CRITERIA_MC_NO_ANSWER",
                    "severity": "blocker",
                    "message": f"Item escolha múltipla {it['groupId']} nº {it['number']} sem chave de resposta.",
                })
        # Points mismatch against matched question.
        if it.get("questionId"):
            q = q_by_id.get(it["questionId"]) or {}
            q_pts = q.get("points")
            c_pts = it.get("points")
            if q_pts is not None and c_pts is not None and int(q_pts) != int(c_pts):
                issues.append({
                    "code": "CRITERIA_POINTS_MISMATCH",
                    "severity": "high",
                    "message": (
                        f"{it['groupId']} nº {it['number']}: critérios={c_pts} pts "
                        f"≠ exame={q_pts} pts."
                    ),
                })

    blocker = sum(1 for i in issues if i["code"] in BLOCKER_CODES and i["severity"] == "blocker")
    high = sum(1 for i in issues if i["severity"] == "high")
    verdict = "FAIL" if (blocker or high) else "PASS"
    return {
        "verdict": verdict,
        "blocker": blocker,
        "high": high,
        "issues": issues,
    }
