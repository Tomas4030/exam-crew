"""Generic quality audit gate for subjects without a dedicated audit.

História A and Português have their own deep audits (history_audit.py,
portuguese_audit.py). Every other subject — Matemática, FQ, Biologia,
Inglês, Economia, … — previously finished with no subject-level validation
at all. This gate enforces the invariants that hold for ALL Portuguese
national exams:

    GENERIC_TOTAL_POINTS       — leaf-question points must sum to 200
    GENERIC_MISSING_POINTS     — every leaf question carries points
    GENERIC_MC_OPTIONS         — multiple choice needs >= 3 real options
    GENERIC_EMPTY_STATEMENT    — statements must have real text
    GENERIC_DUPLICATE_NUMBER   — no duplicate question numbers (per group)
    GENERIC_CORRUPT_TEXT       — flagged corrupt math/text quality

Unlike the História/Português gates this one never aborts the run — it
downgrades the status to needs_review so the exam still lands in the UI
with a clear verdict.
"""
from __future__ import annotations

from typing import Any

from .history_audit import SEVERITY_ORDER, Issue

OFFICIAL_TOTAL = 200


def _leaf_questions(output: dict[str, Any]) -> list[dict]:
    """Answerable questions: not groups, not parents of sub-questions."""
    questions = [q for q in output.get("questions") or [] if isinstance(q, dict)]
    parents = {q.get("parentQuestion") for q in questions if q.get("parentQuestion")}
    return [
        q for q in questions
        if not q.get("isGroup") and q.get("questionId") not in parents
    ]


def audit_output_generic(output: dict[str, Any]) -> list[Issue]:
    root = str(output.get("exam_id") or "exam")
    issues: list[Issue] = []
    leaves = _leaf_questions(output)
    if not leaves:
        issues.append(Issue(root, "BLOCKER", "GENERIC_NO_QUESTIONS",
                            "Exame sem perguntas respondíveis."))
        return issues

    # ── Points ──────────────────────────────────────────────────────────────
    missing_points = [q for q in leaves if q.get("points") in (None, 0)]
    for q in missing_points:
        issues.append(Issue(
            root, "HIGH", "GENERIC_MISSING_POINTS",
            f"Pergunta {q.get('number')} sem cotação atribuída.",
            question_id=str(q.get("questionId") or ""),
            number=str(q.get("number") or ""),
        ))

    pts_total = sum(int(q.get("points") or 0) for q in leaves)
    # Optional-pool exams legitimately carry more raw points than the official
    # total; only flag when there is no optional pool in the scoring policy.
    policy = ((output.get("metadata") or {}).get("scoringPolicy") or {})
    has_optional_pool = bool(policy.get("optionalPool")) or any(
        not item.get("isMandatory", True) for item in policy.get("items") or []
    )
    if not missing_points and not has_optional_pool and pts_total != OFFICIAL_TOTAL:
        severity = "HIGH" if abs(pts_total - OFFICIAL_TOTAL) > 10 else "MEDIUM"
        issues.append(Issue(
            root, severity, "GENERIC_TOTAL_POINTS",
            f"Soma das cotações = {pts_total} pts (esperado {OFFICIAL_TOTAL}).",
            expected=str(OFFICIAL_TOTAL), actual=str(pts_total),
        ))

    # ── Multiple choice structure ───────────────────────────────────────────
    for q in leaves:
        if q.get("type") != "multiple_choice":
            continue
        options = [o for o in q.get("options") or [] if (o.get("text") or o.get("imageUrl"))]
        if len(options) < 3:
            issues.append(Issue(
                root, "HIGH", "GENERIC_MC_OPTIONS",
                f"Escolha múltipla {q.get('number')} tem {len(options)} opções (mínimo 3).",
                question_id=str(q.get("questionId") or ""),
                number=str(q.get("number") or ""),
            ))

    # ── Statements ──────────────────────────────────────────────────────────
    for q in leaves:
        stmt = str(q.get("statement") or q.get("statementPlain") or "").strip()
        if len(stmt) < 10 and not q.get("visualDependency"):
            issues.append(Issue(
                root, "MEDIUM", "GENERIC_EMPTY_STATEMENT",
                f"Pergunta {q.get('number')} com enunciado vazio/curto ({len(stmt)} chars).",
                question_id=str(q.get("questionId") or ""),
                number=str(q.get("number") or ""),
            ))

    # ── Duplicate numbers within the same group ─────────────────────────────
    seen: dict[tuple[str, str], str] = {}
    for q in leaves:
        key = (str(q.get("groupId") or ""), str(q.get("number") or ""))
        if not key[1]:
            continue
        if key in seen:
            issues.append(Issue(
                root, "MEDIUM", "GENERIC_DUPLICATE_NUMBER",
                f"Número {key[1]} duplicado (grupo '{key[0] or '—'}'): "
                f"{seen[key]} e {q.get('questionId')}.",
                question_id=str(q.get("questionId") or ""),
                number=key[1],
            ))
        else:
            seen[key] = str(q.get("questionId") or "")

    # ── Corrupt text quality (math-heavy extractions) ───────────────────────
    for q in leaves:
        tq = q.get("textQuality") or {}
        if tq.get("status") == "corrupt":
            issues.append(Issue(
                root, "HIGH", "GENERIC_CORRUPT_TEXT",
                f"Pergunta {q.get('number')} com texto corrompido (textQuality=corrupt).",
                question_id=str(q.get("questionId") or ""),
                number=str(q.get("number") or ""),
            ))

    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i.severity, 99), i.question_id, i.code))
    return issues


def summarize_issues(issues: list[Issue]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return {
        "blocker": counts.get("BLOCKER", 0),
        "high": counts.get("HIGH", 0),
        "medium": counts.get("MEDIUM", 0),
        "info": counts.get("INFO", 0),
        "verdict": (
            "FAIL" if counts.get("BLOCKER") or counts.get("HIGH")
            else "REVIEW" if counts.get("MEDIUM")
            else "PASS"
        ),
    }


def apply_generic_audit_gate(output: dict[str, Any]) -> tuple[dict[str, Any], list[Issue], dict[str, Any]]:
    """Run the generic audit and fold the verdict into processingStatus.

    Never raises: a FAIL downgrades the exam to needs_review instead of
    aborting, because subjects covered by this gate don't (yet) have the
    deterministic repair machinery that História/Português have.
    """
    issues = audit_output_generic(output)
    summary = summarize_issues(issues)
    output.setdefault("metadata", {})["genericAudit"] = {
        "verdict": summary["verdict"],
        "summary": summary,
        "issues": [issue.row() for issue in issues[:200]],
    }

    if summary["verdict"] == "FAIL":
        if output.get("processingStatus") not in ("partial_failed",):
            output["processingStatus"] = "needs_review"
        output["needsHumanReview"] = True
        output.setdefault("warnings", []).append({
            "type": "generic_audit_failed",
            "severity": "high",
            "message": (
                f"Auditoria genérica falhou: {summary['blocker']} blocker(s), "
                f"{summary['high']} high issue(s)."
            ),
        })
    elif summary["verdict"] == "REVIEW":
        if output.get("processingStatus") == "completed":
            output["processingStatus"] = "completed_with_warnings"

    return output, issues, summary
