from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .history_audit import SEVERITY_ORDER, Issue, OutputBundle, audit_bundle as _history_style_asset_audit


def audit_output(output: dict[str, Any], asset_base: str | Path) -> list[Issue]:
    if not _is_portuguese_output(output):
        return []

    root = str(output.get("exam_id") or Path(asset_base).name)
    issues: list[Issue] = []
    questions = output.get("questions") or []

    _audit_groups(root, questions, issues)
    _audit_points(root, questions, issues)
    _audit_question_types(root, questions, issues)
    _audit_composition(root, questions, issues)
    _audit_media_files(output, asset_base, issues)

    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i.severity, 99), i.root, i.question_id, i.code))
    return issues


def summarize_issues(issues: list[Issue]) -> dict[str, Any]:
    counts = {"BLOCKER": 0, "HIGH": 0, "MEDIUM": 0, "INFO": 0}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return {
        "blocker": counts.get("BLOCKER", 0),
        "high": counts.get("HIGH", 0),
        "medium": counts.get("MEDIUM", 0),
        "info": counts.get("INFO", 0),
        "verdict": "FAIL" if counts.get("BLOCKER") or counts.get("HIGH") else "REVIEW" if counts.get("MEDIUM") else "PASS",
    }


def apply_portuguese_audit_gate(output: dict[str, Any], asset_base: str | Path) -> tuple[dict[str, Any], list[Issue], dict[str, Any]]:
    if not _is_portuguese_output(output):
        return output, [], {"verdict": "SKIPPED", "reason": "not_portuguese"}

    issues = audit_output(output, asset_base)
    summary = summarize_issues(issues)
    output.setdefault("metadata", {})["portugueseAudit"] = {
        "verdict": summary["verdict"],
        "summary": summary,
        "issues": [issue.row() for issue in issues[:200]],
    }

    if summary["verdict"] == "FAIL":
        output["processingStatus"] = "needs_review"
        output["needsHumanReview"] = True
        output.setdefault("warnings", []).append({
            "type": "portuguese_audit_failed",
            "severity": "critical",
            "message": (
                f"Portuguese audit failed: {summary['blocker']} blocker(s), "
                f"{summary['high']} high severity issue(s)."
            ),
        })
    elif summary["verdict"] == "REVIEW" and output.get("processingStatus") != "partial_failed":
        output["processingStatus"] = "completed_with_warnings"
        output["needsHumanReview"] = False
    elif summary["verdict"] == "PASS" and output.get("processingStatus") != "partial_failed":
        output["processingStatus"] = "completed"
        output["needsHumanReview"] = False

    return output, issues, summary


def _audit_groups(root: str, questions: list[dict], issues: list[Issue]) -> None:
    groups = {q.get("groupId") for q in questions}
    for expected in ("grupo_i", "grupo_ii", "grupo_iii"):
        if expected not in groups:
            issues.append(Issue(
                root, "BLOCKER", "PORTUGUESE_GROUP_MISSING",
                f"{expected} is missing from Portuguese exam",
                group=expected,
                expected="grupo_i,grupo_ii,grupo_iii",
                actual=",".join(sorted(str(g) for g in groups if g)),
            ))

    for q in questions:
        text = _question_prompt_text(q).lower()
        if q.get("groupId") != "grupo_iii" and "grupo iii" in text:
            issues.append(Issue(
                root, "BLOCKER", "PORTUGUESE_GROUP_III_EMBEDDED",
                "Grupo III prompt is embedded inside another question",
                question_id=_qid(q),
                group=str(q.get("groupId") or ""),
                number=str(q.get("number") or ""),
            ))


def _audit_points(root: str, questions: list[dict], issues: list[Issue]) -> None:
    total = 0
    invalid = []
    for q in questions:
        points = q.get("points")
        try:
            points_i = int(points)
        except (TypeError, ValueError):
            invalid.append(_qid(q))
            continue
        if points_i <= 0:
            invalid.append(_qid(q))
            continue
        total += points_i

    if invalid:
        issues.append(Issue(
            root, "BLOCKER", "PORTUGUESE_POINTS_INVALID",
            f"{len(invalid)} question(s) have null/non-positive points: {', '.join(invalid[:10])}",
            expected="integer > 0",
            actual=str(len(invalid)),
        ))

    if not invalid and questions and total < 200:
        issues.append(Issue(
            root, "HIGH", "PORTUGUESE_TOTAL_POINTS_TOO_LOW",
            f"Portuguese exam total points = {total}, expected at least 200",
            expected=">=200",
            actual=str(total),
        ))


def _audit_question_types(root: str, questions: list[dict], issues: list[Issue]) -> None:
    for q in questions:
        qtype = q.get("type")
        if qtype == "multiple_choice" and len(q.get("options") or []) < 2:
            issues.append(Issue(
                root, "HIGH", "PORTUGUESE_MC_WITHOUT_OPTIONS",
                "multiple_choice item has fewer than 2 options",
                question_id=_qid(q),
                group=str(q.get("groupId") or ""),
                number=str(q.get("number") or ""),
            ))
        if qtype == "multi_select" and len(q.get("options") or []) < 3:
            issues.append(Issue(
                root, "HIGH", "PORTUGUESE_MULTI_SELECT_WITHOUT_OPTIONS",
                "multi_select item has fewer than 3 options",
                question_id=_qid(q),
                group=str(q.get("groupId") or ""),
                number=str(q.get("number") or ""),
            ))
        if qtype == "multi_blank_choice":
            blanks = q.get("blanks") or []
            if not blanks or any(not (b.get("options") or []) for b in blanks if isinstance(b, dict)):
                issues.append(Issue(
                    root, "HIGH", "PORTUGUESE_MULTIBLANK_WITHOUT_OPTIONS",
                    "multi_blank_choice item has missing blanks/options",
                    question_id=_qid(q),
                    group=str(q.get("groupId") or ""),
                    number=str(q.get("number") or ""),
                ))


def _audit_composition(root: str, questions: list[dict], issues: list[Issue]) -> None:
    grupo_iii = [q for q in questions if q.get("groupId") == "grupo_iii"]
    if not grupo_iii:
        return
    if len(grupo_iii) > 1:
        issues.append(Issue(root, "HIGH", "PORTUGUESE_MULTIPLE_COMPOSITIONS",
                            f"expected one Grupo III composition, found {len(grupo_iii)}"))
    q = grupo_iii[0]
    text = _question_text(q).lower()
    if q.get("type") not in {"open_answer", "essay"}:
        issues.append(Issue(root, "HIGH", "PORTUGUESE_COMPOSITION_WRONG_TYPE",
                            "Grupo III composition should be open_answer/essay", _qid(q), "grupo_iii", str(q.get("number") or "")))
    if len(text.split()) < 25 or not ("texto" in text or "opini" in text or "exposição" in text or "exposicao" in text):
        issues.append(Issue(root, "HIGH", "PORTUGUESE_COMPOSITION_TRUNCATED",
                            "Grupo III composition prompt looks missing/truncated", _qid(q), "grupo_iii", str(q.get("number") or "")))


def _audit_media_files(output: dict[str, Any], asset_base: str | Path, issues: list[Issue]) -> None:
    # Reuse the robust source/media asset checks already implemented in the bundle auditor.
    bundle = OutputBundle(output, Path(asset_base))
    asset_issues = _history_style_asset_audit(bundle)
    for issue in asset_issues:
        if issue.code in {"MISSING_MEDIA_FILE", "MISSING_SOURCE_CROP_FILE", "MISSING_CHILD_CROP_FILE", "BROKEN_SOURCE_REF", "BROKEN_CHILD_REF"}:
            issues.append(issue)


def _is_portuguese_output(output: dict[str, Any]) -> bool:
    metadata = output.get("metadata") or {}
    subject = str(metadata.get("subject") or output.get("subject") or "").lower()
    return "portug" in subject


def _question_text(q: dict) -> str:
    return " ".join(str(q.get(k) or "") for k in ("statement", "statementPlain", "rawText", "sourceTextRaw"))


def _question_prompt_text(q: dict) -> str:
    return " ".join(str(q.get(k) or "") for k in ("statement", "statementPlain", "rawText"))


def _qid(q: dict) -> str:
    return str(q.get("questionId") or q.get("id") or "")
