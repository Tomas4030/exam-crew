from __future__ import annotations

import re
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
    _audit_duplicate_numbers(root, questions, issues)
    _audit_points(root, output, questions, issues)
    _audit_scoring_policy(root, output, questions, issues)
    _audit_question_types(root, questions, issues)
    _audit_composition(root, questions, issues)
    _audit_media_files(output, asset_base, issues)
    _audit_metadata(root, output, issues)
    _audit_sources(root, output, issues)
    _audit_broken_parents(root, questions, issues)
    _audit_cover_page_sources(root, output, issues)
    _audit_scoring_policy_completeness(root, output, issues)
    _audit_legacy_grupo_iii_points(root, output, questions, issues)
    _audit_recovered_without_source_page(root, questions, issues)

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
        # Flag for human review when the warnings stem from reconstructed/recovered
        # data or a rebuilt scoring policy — these are trustworthy enough to ship
        # but a human should confirm them.
        _review_codes = {
            "PORTUGUESE_RECOVERED_WITHOUT_SOURCE_PAGE",
            "PORTUGUESE_SCORING_POLICY_REBUILT",
        }
        output["needsHumanReview"] = any(i.code in _review_codes for i in issues)
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


def _audit_duplicate_numbers(root: str, questions: list[dict], issues: list[Issue]) -> None:
    seen: dict[tuple[str, str], str] = {}
    for q in questions:
        group = str(q.get("groupId") or "")
        number = str(q.get("number") or "")
        if not group or not number:
            continue
        key = (group, number)
        qid = _qid(q)
        previous = seen.get(key)
        if previous:
            issues.append(Issue(
                root, "HIGH", "PORTUGUESE_DUPLICATE_QUESTION_NUMBER",
                f"duplicate Portuguese question number {group} {number}: {previous}, {qid}",
                question_id=qid,
                group=group,
                number=number,
                expected="unique groupId+number",
                actual=f"{previous},{qid}",
            ))
        else:
            seen[key] = qid

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


def _audit_points(root: str, output: dict[str, Any], questions: list[dict], issues: list[Issue]) -> None:
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

    if not invalid and questions:
        metadata = output.get("metadata") or {}
        has_optional_pool = bool(
            (metadata.get("scoringPolicy") or {}).get("optionalPool") or
            (metadata.get("scoringPolicy") or {}).get("optionalPoolSubtotal")
        )
        if total < 200:
            issues.append(Issue(
                root, "HIGH", "PORTUGUESE_TOTAL_POINTS_TOO_LOW",
                f"Portuguese exam total points = {total}, expected at least 200",
                expected=">=200",
                actual=str(total),
            ))
        elif total > 210 and not has_optional_pool:
            issues.append(Issue(
                root, "HIGH", "PORTUGUESE_TOTAL_POINTS_TOO_HIGH",
                f"Portuguese exam total points = {total} (>210) without an optional pool — possible scoring extraction error",
                expected="~200",
                actual=str(total),
            ))


def _audit_scoring_policy(root: str, output: dict[str, Any], questions: list[dict], issues: list[Issue]) -> None:
    policy = (output.get("metadata") or {}).get("scoringPolicy") or {}
    items = policy.get("items") or []
    if not isinstance(items, list) or not items:
        return

    by_key = {
        (str(q.get("groupId") or ""), str(q.get("number") or "")): q
        for q in questions
        if q.get("groupId") and q.get("number")
    }
    missing = []
    mismatched = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("groupId") or ""), str(item.get("number") or ""))
        expected_points = item.get("points")
        q = by_key.get(key)
        if not q:
            missing.append(f"{key[0]}:{key[1]}")
            continue
        try:
            actual_points = int(q.get("points"))
            expected_i = int(expected_points)
        except (TypeError, ValueError):
            mismatched.append(f"{key[0]}:{key[1]}={q.get('points')} expected {expected_points}")
            continue
        if actual_points != expected_i:
            mismatched.append(f"{key[0]}:{key[1]}={actual_points} expected {expected_i}")

    if missing:
        issues.append(Issue(
            root, "BLOCKER", "PORTUGUESE_SCORING_ITEM_MISSING",
            f"{len(missing)} item(s) from scoring table are missing: {', '.join(missing[:10])}",
            expected="all scoringPolicy.items present",
            actual=str(len(missing)),
        ))
    if mismatched:
        issues.append(Issue(
            root, "BLOCKER", "PORTUGUESE_SCORING_POINTS_MISMATCH",
            f"{len(mismatched)} item(s) do not match scoring table: {', '.join(mismatched[:10])}",
            expected="points from scoringPolicy.items",
            actual=str(len(mismatched)),
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
        if qtype == "multi_select" and len(q.get("options") or []) >= 3:
            max_selections = q.get("maxSelections")
            try:
                max_i = int(max_selections)
            except (TypeError, ValueError):
                max_i = 0
            if max_i < 2 or max_i > len(q.get("options") or []):
                issues.append(Issue(
                    root, "HIGH", "PORTUGUESE_MULTI_SELECT_INVALID_MAX",
                    "multi_select item has missing/invalid maxSelections",
                    question_id=_qid(q),
                    group=str(q.get("groupId") or ""),
                    number=str(q.get("number") or ""),
                    expected="2..options_count",
                    actual=str(max_selections),
                ))
        if qtype == "multi_blank_choice":
            blanks = q.get("blanks") or []
            if len(blanks) < 2 or any(not isinstance(b, dict) or len(b.get("options") or []) < 2 for b in blanks):
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
    if _composition_requires_visual(text) and not (q.get("media") or q.get("assetRefs") or q.get("sourceRefs")):
        issues.append(Issue(root, "HIGH", "PORTUGUESE_COMPOSITION_MISSING_VISUAL",
                            "Grupo III composition asks for a visual/cartoon but has no media/assetRefs",
                            _qid(q), "grupo_iii", str(q.get("number") or "")))


def _audit_media_files(output: dict[str, Any], asset_base: str | Path, issues: list[Issue]) -> None:
    # Reuse the robust source/media asset checks already implemented in the bundle auditor.
    bundle = OutputBundle(output, Path(asset_base))
    asset_issues = _history_style_asset_audit(bundle)
    for issue in asset_issues:
        if issue.code in {
            "MISSING_MEDIA_FILE",
            "MISSING_SOURCE_CROP_FILE",
            "MISSING_CHILD_CROP_FILE",
            "BROKEN_SOURCE_REF",
            "BROKEN_CHILD_REF",
        }:
            issues.append(issue)
        elif issue.code == "SOURCE_WITHOUT_CROP":
            # Portuguese text sources (texto de apoio) may not have crop images;
            # the text content is already embedded in the JSON. Downgrade to MEDIUM
            # so the exam processes instead of failing the audit gate.
            issues.append(Issue(
                issue.root, "MEDIUM", issue.code, issue.message,
                issue.question_id, issue.group, issue.number,
                issue.expected, issue.actual,
            ))

    _audit_asset_ref_files(output, asset_base, issues)


def _audit_asset_ref_files(output: dict[str, Any], asset_base: str | Path, issues: list[Issue]) -> None:
    base = Path(asset_base)
    assets = {
        str(asset.get("id")): asset
        for asset in (output.get("assets") or [])
        if isinstance(asset, dict) and asset.get("id")
    }
    for q in output.get("questions") or []:
        for ref_id in q.get("assetRefs") or []:
            asset = assets.get(str(ref_id))
            if not asset:
                issues.append(Issue(
                    str(output.get("exam_id") or base.name), "HIGH", "PORTUGUESE_BROKEN_ASSET_REF",
                    f"question assetRef points to missing asset {ref_id}",
                    _qid(q), str(q.get("groupId") or ""), str(q.get("number") or ""),
                    expected="asset id in assets[]", actual=str(ref_id),
                ))
                continue
            rel = _asset_relative_path(asset)
            if rel and not (base / rel).exists():
                issues.append(Issue(
                    str(output.get("exam_id") or base.name), "HIGH", "PORTUGUESE_MISSING_ASSET_REF_FILE",
                    f"question assetRef points to missing file {rel}",
                    _qid(q), str(q.get("groupId") or ""), str(q.get("number") or ""),
                    expected=rel, actual="missing",
                ))


def _asset_relative_path(asset: dict[str, Any]) -> str:
    rel = asset.get("relativePath")
    if isinstance(rel, str) and rel.startswith("assets/"):
        return rel
    url = asset.get("url")
    if isinstance(url, str) and "/assets/" in url:
        return "assets/" + url.split("/assets/", 1)[1]
    crop = asset.get("crop")
    if isinstance(crop, dict):
        rel = crop.get("relativePath")
        if isinstance(rel, str) and rel.startswith("assets/"):
            return rel
    crops = asset.get("crops")
    if isinstance(crops, dict):
        for key in ("visual", "best", "full", "document", "context"):
            crop = crops.get(key)
            if isinstance(crop, dict):
                rel = crop.get("relativePath")
                if isinstance(rel, str) and rel.startswith("assets/"):
                    return rel
    return ""


def _is_portuguese_output(output: dict[str, Any]) -> bool:
    metadata = output.get("metadata") or {}
    subject = str(metadata.get("subject") or output.get("subject") or "").lower()
    return "portug" in subject


def _question_text(q: dict) -> str:
    return " ".join(str(q.get(k) or "") for k in ("statement", "statementPlain", "rawText", "sourceTextRaw"))


def _question_prompt_text(q: dict) -> str:
    return " ".join(str(q.get(k) or "") for k in ("statement", "statementPlain", "rawText"))


def _composition_requires_visual(text: str) -> bool:
    return (
        "cartoon" in text
        or "refloresta" in text
        or "figura apresentada" in text
        or "imagem apresentada" in text
        or "descrição da cena" in text
        or "descricao da cena" in text
    )


def _qid(q: dict) -> str:
    return str(q.get("questionId") or q.get("id") or "")


# ---------------------------------------------------------------------------
# New audit checks added in round 3
# ---------------------------------------------------------------------------

def _audit_metadata(root: str, output: dict[str, Any], issues: list[Issue]) -> None:
    """Check that the exam title contains the correct year."""
    metadata = output.get("metadata") or {}
    year = str(metadata.get("year") or "").strip()
    title = str(metadata.get("title") or "").strip()
    if year and title and year not in title:
        issues.append(Issue(
            root, "HIGH", "PORTUGUESE_TITLE_YEAR_MISMATCH",
            f"Exam title '{title}' does not contain the detected year {year}",
            expected=f"year {year} in title",
            actual=title,
        ))


def _audit_sources(root: str, output: dict[str, Any], issues: list[Issue]) -> None:
    """Check that text_source entries actually have text content."""
    for source in output.get("sources") or []:
        if not isinstance(source, dict):
            continue
        if source.get("groupId") not in {"grupo_i", "grupo_ii"}:
            continue
        if source.get("kind") != "text_source":
            continue
        has_text = bool(str(source.get("text") or "").strip())
        has_crop = bool(
            (source.get("crops") or {}).get("full") or
            (source.get("crops") or {}).get("best")
        )
        if not has_text and not has_crop:
            issues.append(Issue(
                root, "HIGH", "PORTUGUESE_TEXT_SOURCE_EMPTY",
                f"text_source {source.get('sourceId')} has no text and no crop",
                expected="text or crop",
                actual="empty",
            ))


def _audit_broken_parents(root: str, questions: list[dict], issues: list[Issue]) -> None:
    """Check that parentQuestion references point to existing question IDs."""
    existing_ids = {str(q.get("questionId") or "") for q in questions if isinstance(q, dict)}
    for q in questions:
        if not isinstance(q, dict):
            continue
        parent = q.get("parentQuestion")
        if not parent:
            continue
        if parent in existing_ids:
            continue
        # Allow container scenario: parent prefix exists
        if any(eid.startswith(str(parent) + "_") for eid in existing_ids):
            continue
        issues.append(Issue(
            root, "HIGH", "PORTUGUESE_BROKEN_PARENT",
            f"question {_qid(q)} references non-existent parentQuestion {parent}",
            question_id=_qid(q),
            group=str(q.get("groupId") or ""),
            number=str(q.get("number") or ""),
            expected="existing questionId",
            actual=str(parent),
        ))


# ---------------------------------------------------------------------------
# New audit checks added in round 4
# ---------------------------------------------------------------------------

def _audit_cover_page_sources(root: str, output: dict[str, Any], issues: list[Issue]) -> None:
    """Flag sources whose pageStart is 1 (cover page) — never a valid source."""
    _COVER_SIGNALS = re.compile(
        r'exame nacional|prova\s+\d{3}|decreto.lei|duração da prova|instruções|folha de resposta',
        re.IGNORECASE,
    )
    for source in output.get("sources") or []:
        if not isinstance(source, dict):
            continue
        if source.get("groupId") not in {"grupo_i", "grupo_ii", "grupo_iii"}:
            continue
        page_start = source.get("pageStart")
        try:
            page_start_i = int(page_start)
        except (TypeError, ValueError):
            continue
        if page_start_i != 1:
            continue
        # pageStart = 1 is cover/instructions page
        issues.append(Issue(
            root, "HIGH", "PORTUGUESE_COVER_PAGE_AS_SOURCE",
            f"source {source.get('sourceId')} has pageStart=1 (cover page), not a valid text source",
            expected="pageStart > 1",
            actual=str(page_start_i),
        ))


def _audit_scoring_policy_completeness(root: str, output: dict[str, Any], issues: list[Issue]) -> None:
    """Flag scoring policies that only captured a fraction of the expected entries."""
    import re as _re
    metadata = output.get("metadata") or {}
    try:
        year = int(metadata.get("year") or 0)
    except (TypeError, ValueError):
        year = 0

    policy = metadata.get("scoringPolicy") or {}
    items = policy.get("items") or []
    if not items:
        return  # no policy extracted → different check

    raw_subtotal = policy.get("rawSubtotal") or 0
    try:
        raw_subtotal_i = int(raw_subtotal)
    except (TypeError, ValueError):
        raw_subtotal_i = 0

    # A complete Portuguese scoring table must have at least 8 items and sum ≥ 180
    if len(items) < 8 or raw_subtotal_i < 180:
        issues.append(Issue(
            root, "HIGH", "PORTUGUESE_SCORING_POLICY_INCOMPLETE",
            (
                f"scoringPolicy has only {len(items)} item(s) and rawSubtotal={raw_subtotal_i} "
                f"— scoring table likely mis-parsed"
            ),
            expected=">=8 items and rawSubtotal>=180",
            actual=f"{len(items)} items, subtotal={raw_subtotal_i}",
        ))

    # Policy was auto-rebuilt from question points (normalizer repair) — flag as MEDIUM
    # so the exam lands at completed_with_warnings rather than silently completed.
    if policy.get("source") == "rebuilt_from_questions":
        issues.append(Issue(
            root, "MEDIUM", "PORTUGUESE_SCORING_POLICY_REBUILT",
            (
                f"scoringPolicy was rebuilt automatically from question points "
                f"({len(items)} items, rawSubtotal={raw_subtotal_i}) — "
                f"verify the point values match the original scoring table"
            ),
            expected="source=cotacoes (parsed from PDF)",
            actual="source=rebuilt_from_questions",
        ))

    # Pre-2020 exams should not have optional questions
    if year and year < 2020:
        optional_items = [i for i in items if isinstance(i, dict) and not i.get("isMandatory", True)]
        if optional_items:
            issues.append(Issue(
                root, "HIGH", "PORTUGUESE_LEGACY_EXAM_HAS_OPTIONAL",
                f"exam year {year} (<2020) has {len(optional_items)} optional scoring item(s) — likely mis-parsed",
                expected="all isMandatory for pre-2020",
                actual=str(len(optional_items)),
            ))


def _audit_legacy_grupo_iii_points(
    root: str,
    output: dict[str, Any],
    questions: list[dict],
    issues: list[Issue],
) -> None:
    """For 2008-2014 Portuguese exams, Grupo III (composition) must be exactly 50 pts.

    The scoring table in these old editions always assigns 50 points to the
    composition task.  Any other value indicates a parser error or incorrect
    inflation by ``_repair_composition_points_remainder``.
    """
    metadata = output.get("metadata") or {}
    try:
        year = int(metadata.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    if not (2008 <= year <= 2014):
        return

    composition = next((q for q in questions if q.get("groupId") == "grupo_iii"), None)
    if not composition:
        return  # absence is caught by _audit_groups

    try:
        pts = int(composition.get("points") or 0)
    except (TypeError, ValueError):
        pts = 0

    if pts != 50:
        issues.append(Issue(
            root, "HIGH", "PORTUGUESE_LEGACY_GRUPO_III_POINTS_INVALID",
            f"year {year}: Grupo III (composition) has {pts} pts — must be exactly 50 for 2008-2014 exams",
            expected="50",
            actual=str(pts),
        ))


def _audit_recovered_without_source_page(
    root: str,
    questions: list[dict],
    issues: list[Issue],
) -> None:
    """Flag recovered questions that have no known source page.

    A question whose ID contains ``_recovered`` was not found by the LLM and
    was reconstructed from the PDF text layer.  If we also could not determine
    which page it belongs to, the question's placement and context are unknown —
    the exam must be reviewed by a human before it can be marked complete.
    """
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("questionId") or "")
        if "_recovered" not in qid:
            continue
        if q.get("sourcePage"):
            continue  # has a page — lower risk, covered elsewhere
        # MEDIUM, not HIGH: when the exam's overall scoring is internally
        # consistent (total == 200, groups correct), a recovered question
        # without a page is a metadata gap, not a correctness error.  Genuinely
        # broken exams are already blocked by the TOTAL_POINTS / SCORING_POLICY
        # HIGH checks, so this stays a review flag (→ completed_with_warnings).
        issues.append(Issue(
            root, "MEDIUM", "PORTUGUESE_RECOVERED_WITHOUT_SOURCE_PAGE",
            f"question {qid!r} was recovered from PDF text but has no known sourcePage",
            expected="sourcePage set",
            actual="null",
            question_id=qid,
        ))
