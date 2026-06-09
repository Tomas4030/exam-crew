from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .doc_refs import doc_nums_from_source_refs, resolve_doc_numbers


SEVERITY_ORDER = {"BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}


@dataclass
class Issue:
    root: str
    severity: str
    code: str
    message: str
    question_id: str = ""
    group: str = ""
    number: str = ""
    expected: str = ""
    actual: str = ""

    def row(self) -> dict[str, str]:
        return {
            "root": self.root,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "questionId": self.question_id,
            "group": self.group,
            "number": self.number,
            "expected": self.expected,
            "actual": self.actual,
        }


class ExamBundle:
    def __init__(self, path: Path):
        self.path = path
        self.root = path.stem if path.suffix.lower() == ".zip" else path.parent.name
        self.data: dict[str, Any] = {}
        self.asset_names: set[str] = set()
        self.asset_bytes: dict[str, bytes] = {}
        self._load()

    def _load(self) -> None:
        if self.path.suffix.lower() == ".zip":
            with zipfile.ZipFile(self.path) as zf:
                names = set(zf.namelist())
                json_name = "exam.json" if "exam.json" in names else next(
                    (n for n in names if n.endswith("/exam.json")), None
                )
                if not json_name:
                    raise ValueError(f"{self.path}: exam.json not found")
                self.data = json.loads(zf.read(json_name).decode("utf-8"))
                for name in names:
                    if _is_asset_name(name):
                        self.asset_names.add(_norm_asset_path(name))
                        try:
                            self.asset_bytes[_norm_asset_path(name)] = zf.read(name)
                        except Exception:
                            pass
            return

        if self.path.is_file():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            base = self.path.parent if self.path.name == "exam.json" else self.path.parent / self.path.stem
        else:
            json_path = self.path / "exam.json"
            if not json_path.exists():
                alt = self.path.with_suffix(".json")
                if alt.exists():
                    json_path = alt
                else:
                    raise ValueError(f"{self.path}: exam.json not found")
            self.data = json.loads(json_path.read_text(encoding="utf-8"))
            base = self.path

        asset_root = base / "assets"
        if asset_root.exists():
            for file in asset_root.rglob("*"):
                if file.is_file():
                    rel = _norm_asset_path(str(file.relative_to(base)).replace("\\", "/"))
                    self.asset_names.add(rel)
                    try:
                        self.asset_bytes[rel] = file.read_bytes()
                    except Exception:
                        pass


class OutputBundle:
    def __init__(self, data: dict[str, Any], asset_base: Path):
        self.path = asset_base
        self.root = str(data.get("exam_id") or asset_base.name)
        self.data = data
        self.asset_names: set[str] = set()
        self.asset_bytes: dict[str, bytes] = {}
        self._load_assets(asset_base)

    def _load_assets(self, asset_base: Path) -> None:
        if not asset_base.exists():
            return
        for file in asset_base.rglob("*"):
            if not file.is_file() or not _is_asset_name(str(file)):
                continue
            rel = _norm_asset_path(str(file.relative_to(asset_base)).replace("\\", "/"))
            self.asset_names.add(rel)
            try:
                self.asset_bytes[rel] = file.read_bytes()
            except Exception:
                pass


def audit_bundle(bundle: ExamBundle) -> list[Issue]:
    data = bundle.data
    root = data.get("exam_id") or bundle.root
    issues: list[Issue] = []

    questions = data.get("questions") or []
    sources = data.get("sources") or []
    metadata = data.get("metadata") or {}

    _audit_counts(root, questions, metadata, issues)
    _audit_points(root, questions, issues, metadata)
    _audit_metadata(root, metadata, issues)
    _audit_text_quality(root, questions, issues)
    _audit_question_types(root, questions, issues)
    _audit_sources_and_media(root, questions, sources, bundle, issues)
    _audit_document_expectations(root, questions, sources, issues)
    _audit_crops(root, sources, bundle, issues, metadata)
    _audit_warning_noise(root, data, issues)

    issues.sort(key=lambda i: (SEVERITY_ORDER.get(i.severity, 99), i.root, i.question_id, i.code))
    return issues


def audit_output(output: dict[str, Any], asset_base: str | Path) -> list[Issue]:
    return audit_bundle(OutputBundle(output, Path(asset_base)))


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


def apply_history_audit_gate(output: dict[str, Any], asset_base: str | Path) -> tuple[dict[str, Any], list[Issue], dict[str, Any]]:
    if not _is_probably_history_output(output):
        return output, [], {"verdict": "SKIPPED", "reason": "not_history"}

    issues = audit_output(output, asset_base)
    summary = summarize_issues(issues)
    audit_payload = {
        "verdict": summary["verdict"],
        "summary": summary,
        "issues": [issue.row() for issue in issues[:200]],
    }
    output.setdefault("metadata", {})["historyAudit"] = audit_payload

    if summary["verdict"] == "FAIL":
        output["processingStatus"] = "needs_review"
        output["needsHumanReview"] = True
        output.setdefault("warnings", []).append({
            "type": "history_audit_failed",
            "severity": "critical",
            "message": (
                f"History audit failed: {summary['blocker']} blocker(s), "
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


def _is_probably_history_output(output: dict[str, Any]) -> bool:
    metadata = output.get("metadata") or {}
    subject = str(metadata.get("subject") or output.get("subject") or "").lower()
    if subject and "hist" not in subject:
        return False

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


def _audit_counts(root: str, questions: list[dict], metadata: dict, issues: list[Issue]) -> None:
    stats = metadata.get("stats") or {}
    expected = stats.get("answerableItems") or stats.get("mainQuestions")
    if expected and expected != len(questions):
        issues.append(Issue(
            root, "HIGH", "QUESTION_COUNT_MISMATCH",
            f"metadata expects {expected} answerable/main items but JSON has {len(questions)}",
            expected=str(expected), actual=str(len(questions)),
        ))

    by_group: dict[str, list[int]] = {}
    for q in questions:
        group = _group_id(q)
        number = str(q.get("number") or "")
        if group and number.isdigit():
            by_group.setdefault(group, []).append(int(number))

    for group, nums in by_group.items():
        if not nums:
            continue
        unique = sorted(set(nums))
        missing = [n for n in range(unique[0], unique[-1] + 1) if n not in unique]
        if missing:
            issues.append(Issue(
                root, "BLOCKER", "GROUP_NUMBER_GAP",
                f"{group} has missing item number(s): {missing}",
                group=group, expected=",".join(map(str, range(unique[0], unique[-1] + 1))),
                actual=",".join(map(str, unique)),
            ))


def _audit_points(root: str, questions: list[dict], issues: list[Issue], metadata: dict | None = None) -> None:
    null_points: list[str] = []
    zero_points: list[str] = []
    total = 0

    for q in questions:
        qid = _question_id(q)
        points = q.get("points")
        if points is None:
            null_points.append(qid)
            continue
        try:
            numeric = int(points)
        except (TypeError, ValueError):
            null_points.append(qid)
            continue
        if numeric <= 0:
            zero_points.append(qid)
            continue
        total += numeric

    if null_points:
        issues.append(Issue(
            root, "BLOCKER", "POINTS_NULL",
            f"{len(null_points)} question(s) have null/non-numeric points: {', '.join(null_points[:10])}",
            expected="integer > 0",
            actual=f"{len(null_points)} invalid",
        ))
    if zero_points:
        issues.append(Issue(
            root, "BLOCKER", "POINTS_ZERO",
            f"{len(zero_points)} question(s) have zero/negative points: {', '.join(zero_points[:10])}",
            expected="integer > 0",
            actual=f"{len(zero_points)} zero",
        ))

    # Recent Historia A exams include optional items in the exported quiz, so
    # totals above 200 can be valid. Totals below 200 are still structurally bad.
    if questions and not null_points and not zero_points and total < 200:
        issues.append(Issue(
            root, "HIGH", "TOTAL_POINTS_TOO_LOW",
            f"total points = {total}, expected at least 200",
            expected=">=200",
            actual=str(total),
        ))


def _audit_metadata(root: str, metadata: dict, issues: list[Issue]) -> None:
    year = metadata.get("year")
    phase = metadata.get("phase")
    if not year:
        issues.append(Issue(
            root, "HIGH", "MISSING_YEAR",
            "metadata.year is missing, so the exam cannot be catalogued reliably",
            expected="year",
            actual=str(year),
        ))
    if not phase:
        issues.append(Issue(
            root, "HIGH", "MISSING_PHASE",
            "metadata.phase is missing, so the exam cannot be catalogued reliably",
            expected="phase",
            actual=str(phase),
        ))


def _audit_text_quality(root: str, questions: list[dict], issues: list[Issue]) -> None:
    bad_chars = ("�", "ï¿½", "\ufffd")
    for q in questions:
        text = _question_text(q)
        qmarks = text.count("?")
        words = max(1, len(re.findall(r"\w+", text)))
        has_bad = any(ch in text for ch in bad_chars)
        if has_bad or qmarks >= 2 and qmarks / words >= 0.015 or qmarks >= 4:
            issues.append(Issue(
                root, "BLOCKER", "CORRUPT_TEXT",
                f"question text has likely mojibake/corruption ({qmarks} question marks)",
                question_id=_question_id(q),
                group=_group_id(q),
                number=str(q.get("number") or ""),
                actual=str(qmarks),
            ))


def _audit_question_types(root: str, questions: list[dict], issues: list[Issue]) -> None:
    for q in questions:
        qid = _question_id(q)
        qtype = q.get("type")
        options = q.get("options") or []
        blanks = q.get("blanks") or []
        text = _question_text(q).lower()

        if qtype == "multiple_choice" and len(options) < 2:
            issues.append(Issue(root, "HIGH", "MULTIPLE_CHOICE_WITHOUT_OPTIONS",
                                "multiple_choice item has fewer than 2 options", qid, _group_id(q), str(q.get("number") or "")))

        if qtype == "multi_select":
            max_selections = q.get("maxSelections")
            if len(options) < 3:
                issues.append(Issue(root, "HIGH", "MULTI_SELECT_WITHOUT_OPTIONS",
                                    "multi_select item has fewer than 3 options", qid, _group_id(q), str(q.get("number") or "")))
            if max_selections is None or int(max_selections or 0) < 2:
                issues.append(Issue(root, "MEDIUM", "MULTI_SELECT_SELECTION_COUNT",
                                    "multi_select item is missing maxSelections >= 2", qid, _group_id(q), str(q.get("number") or "")))

        if qtype == "multi_blank_choice":
            invalid = not blanks or any(not (b.get("options") or []) for b in blanks if isinstance(b, dict))
            if invalid:
                issues.append(Issue(root, "HIGH", "MULTIBLANK_WITHOUT_OPTIONS",
                                    "multi_blank_choice item has missing blanks/options", qid, _group_id(q), str(q.get("number") or "")))

        if qtype == "matching":
            columns = q.get("matchColumns") or {}
            left = columns.get("left") or columns.get("columnA") or []
            right = columns.get("right") or columns.get("columnB") or []
            if len(left) < 2 or len(right) < 2:
                issues.append(Issue(root, "HIGH", "MATCHING_WITHOUT_COLUMNS",
                                    "matching item has missing/insufficient matchColumns", qid, _group_id(q), str(q.get("number") or "")))

        if qtype == "ordering" and len(q.get("orderingItems") or []) < 2:
            issues.append(Issue(root, "HIGH", "ORDERING_WITHOUT_ITEMS",
                                "ordering item has fewer than 2 orderingItems", qid, _group_id(q), str(q.get("number") or "")))

        if "complete o texto" in text and qtype != "multi_blank_choice":
            issues.append(Issue(root, "HIGH", "MULTIBLANK_MISCLASSIFIED",
                                "statement looks like fill-in-blanks but type is not multi_blank_choice", qid, _group_id(q), str(q.get("number") or ""), "multi_blank_choice", str(qtype)))

        if re.search(r"\([A-D]\)", _question_text(q)) and qtype == "open_answer":
            issues.append(Issue(root, "MEDIUM", "CHOICE_LIKE_OPEN_ANSWER",
                                "open_answer statement contains A-D option markers", qid, _group_id(q), str(q.get("number") or "")))

        if qtype == "open_answer" and _looks_like_selection_prompt(text):
            issues.append(Issue(
                root, "HIGH", "OPEN_ANSWER_SHOULD_BE_SELECTION",
                "open_answer statement asks the student to select/identify options",
                qid, _group_id(q), str(q.get("number") or ""),
                expected="multiple_choice or multi_select",
                actual="open_answer",
            ))


def _audit_sources_and_media(
    root: str,
    questions: list[dict],
    sources: list[dict],
    bundle: ExamBundle,
    issues: list[Issue],
) -> None:
    source_ids = {s.get("sourceId") for s in sources}
    child_ids = set()
    for s in sources:
        child_ids.update(s.get("children") or [])
        child_ids.update((s.get("childCrops") or {}).keys())

    for q in questions:
        qid = _question_id(q)
        refs = q.get("sourceRefs") or []
        media = q.get("media") or []
        text = _question_text(q)

        for ref in refs:
            sid = ref.get("sourceId")
            child = ref.get("childId")
            if sid not in source_ids:
                issues.append(Issue(root, "BLOCKER", "BROKEN_SOURCE_REF",
                                    f"sourceRef points to missing source {sid}", qid, _group_id(q), str(q.get("number") or ""), actual=str(sid)))
            if child and child not in child_ids:
                issues.append(Issue(root, "BLOCKER", "BROKEN_CHILD_REF",
                                    f"sourceRef childId missing: {child}", qid, _group_id(q), str(q.get("number") or ""), actual=str(child)))
            if sid and _group_id(q) and not str(sid).startswith(_group_id(q) + "_"):
                issues.append(Issue(root, "BLOCKER", "CROSS_GROUP_SOURCE_REF",
                                    f"sourceRef {sid} does not belong to question group {_group_id(q)}", qid, _group_id(q), str(q.get("number") or ""), actual=str(sid)))

        if refs and not media:
            issues.append(Issue(root, "HIGH", "SOURCE_REFS_WITHOUT_MEDIA",
                                "question has sourceRefs but media is empty", qid, _group_id(q), str(q.get("number") or "")))

        if _mentions_document_or_image(text) and not refs:
            issues.append(Issue(root, "HIGH", "MENTIONS_SOURCE_WITHOUT_REF",
                                "question mentions document/image but has no sourceRefs", qid, _group_id(q), str(q.get("number") or "")))

        for m in media:
            url = m.get("url") or ""
            rel = _url_to_rel(url)
            if rel and rel not in bundle.asset_names:
                issues.append(Issue(root, "BLOCKER", "MISSING_MEDIA_FILE",
                                    f"media file not found in bundle: {rel}", qid, _group_id(q), str(q.get("number") or ""), actual=rel))


def _audit_document_expectations(root: str, questions: list[dict], sources: list[dict], issues: list[Issue]) -> None:
    docs_by_group: dict[str, list[int]] = {}
    for s in sources:
        gid = s.get("groupId") or ""
        match = re.search(r"_documento_(\d+)$", str(s.get("sourceId") or ""))
        if gid and match:
            docs_by_group.setdefault(gid, []).append(int(match.group(1)))

    for q in questions:
        gid = _group_id(q)
        expected = resolve_doc_numbers(_question_text(q), sorted(docs_by_group.get(gid, [])))
        if not expected:
            continue
        actual = doc_nums_from_source_refs(q.get("sourceRefs") or [])
        missing = sorted(set(expected) - set(actual))
        if missing:
            issues.append(Issue(
                root, "BLOCKER", "MISSING_EXPECTED_DOCUMENTS",
                f"question text requires document(s) {expected}, but sourceRefs only include {actual}; missing {missing}",
                _question_id(q), gid, str(q.get("number") or ""),
                ",".join(map(str, expected)), ",".join(map(str, actual)),
            ))


def _audit_crops(root: str, sources: list[dict], bundle: ExamBundle, issues: list[Issue], metadata: dict | None = None) -> None:
    hashes_by_group: dict[tuple[str, str], list[str]] = {}
    total_pages = int((metadata or {}).get("total_pages") or 0)
    for source in sources:
        crop = ((source.get("crops") or {}).get("best") or (source.get("crops") or {}).get("full") or {})
        rel = _url_to_rel(crop.get("url") or crop.get("relativePath") or "")
        method = str(crop.get("method") or "")
        if (
            total_pages
            and source.get("groupId") == "grupo_i"
            and int(source.get("pageStart") or 0) >= total_pages
            and method == "history_unlabelled_doc_crop"
        ):
            issues.append(Issue(
                root, "BLOCKER", "SCORING_PAGE_AS_SOURCE",
                "implicit Grupo I document crop points to the final scoring page",
                group="grupo_i", actual=str(source.get("sourceId") or ""),
            ))
        if not rel:
            if source.get("preferredRender") == "text":
                continue
            issues.append(Issue(root, "HIGH", "SOURCE_WITHOUT_CROP",
                                f"source has no best/full crop: {source.get('sourceId')}", actual=str(source.get("sourceId"))))
            continue
        data = bundle.asset_bytes.get(rel)
        if not data:
            issues.append(Issue(root, "BLOCKER", "MISSING_SOURCE_CROP_FILE",
                                f"source crop file missing: {rel}", actual=rel))
            continue
        width, height = _png_dimensions(data)
        if height and height < 80:
            issues.append(Issue(
                root, "HIGH", "SUSPECT_CROP_TOO_SMALL",
                f"source crop is only {width}x{height}px; likely a footer/citation, not a document",
                question_id=str(source.get("sourceId") or ""),
                group=str(source.get("groupId") or ""),
                actual=f"{rel} ({width}x{height})",
            ))
        elif width and height and width / height > 8:
            issues.append(Issue(
                root, "INFO", "SUSPECT_CROP_TOO_SMALL",
                f"source crop has extreme aspect ratio {width}x{height}px; visually inspect if this document matters",
                question_id=str(source.get("sourceId") or ""),
                group=str(source.get("groupId") or ""),
                actual=f"{rel} ({width}x{height})",
            ))
        digest = hashlib.sha256(data).hexdigest()
        key = (source.get("groupId") or "", digest)
        hashes_by_group.setdefault(key, []).append(source.get("sourceId") or "")

    for (group, _digest), source_ids in hashes_by_group.items():
        if len(source_ids) > 1:
            issues.append(Issue(root, "HIGH", "DUPLICATE_SOURCE_CROPS",
                                f"sources in {group} have identical crop bytes: {source_ids}",
                                group=group, actual=",".join(source_ids)))

    for source in sources:
        for child_id, crop in (source.get("childCrops") or {}).items():
            rel = _url_to_rel((crop or {}).get("url") or (crop or {}).get("relativePath") or "")
            if rel and rel not in bundle.asset_names:
                issues.append(Issue(root, "BLOCKER", "MISSING_CHILD_CROP_FILE",
                                    f"child crop file missing: {rel}", actual=rel))


def _audit_warning_noise(root: str, data: dict, issues: list[Issue]) -> None:
    warnings = data.get("warnings") or []
    for warning in warnings:
        wtype = warning.get("type") or ""
        if wtype in {"missing_crop_ref", "missing_media_ref"}:
            continue
        if wtype == "possible_hallucination":
            continue
        if wtype in {"broken_ref"}:
            issues.append(Issue(root, "MEDIUM", "PIPELINE_WARNING",
                                warning.get("message") or wtype, actual=wtype))


def _question_text(q: dict) -> str:
    return " ".join(str(q.get(k) or "") for k in ("statement", "rawText", "statementPlain"))


def _question_id(q: dict) -> str:
    return str(q.get("questionId") or q.get("id") or "")


def _group_id(q: dict) -> str:
    if q.get("groupId"):
        return str(q["groupId"])
    group = str(q.get("group") or "").strip().lower().replace(" ", "_")
    roman = {"grupo_i", "grupo_ii", "grupo_iii", "grupo_iv"}
    return group if group in roman else ""


def _mentions_document_or_image(text: str) -> bool:
    return bool(re.search(r"\b(documento|imagem)\s+[A-Z0-9]", text or "", re.IGNORECASE))


def _looks_like_selection_prompt(text: str) -> bool:
    if not text:
        return False
    if re.search(r"\btranscreva\s+duas\s+afirma", text, re.IGNORECASE):
        return False
    patterns = (
        r"\bselec(?:ione|cione|cione)\s+as?\s+duas\b",
        r"\bsele(?:ccione|cione)\s+as?\s+duas\b",
        r"\bidentifique\s+as?\s+duas\b",
        r"\bduas\s+afirma(?:ções|coes)\b",
        r"\bduas\s+op(?:ções|coes)\s+selecionadas\b",
        r"\bop(?:ção|cao)\s+adequada\b",
        r"\bassinale\b",
        r"\bindique\s+a\s+op(?:ção|cao)\b",
        r"\btranscreva\s+a\s+op(?:ção|cao)\b",
    )
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _is_asset_name(name: str) -> bool:
    return bool(re.search(r"\.(png|jpg|jpeg|webp|gif)$", name, re.IGNORECASE))


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    try:
        return struct.unpack(">II", data[16:24])
    except struct.error:
        return 0, 0


def _norm_asset_path(path: str) -> str:
    path = path.replace("\\", "/")
    if "/assets/" in path:
        return "assets/" + path.split("/assets/", 1)[1]
    return path.lstrip("/")


def _url_to_rel(url: str | None) -> str:
    if not url:
        return ""
    value = str(url)
    if "/assets/" in value:
        return "assets/" + value.split("/assets/", 1)[1]
    if value.startswith("assets/"):
        return value
    return value


def discover_inputs(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(path.rglob("*.zip")))
            found.extend(sorted(path.rglob("exam.json")))
            found.extend(sorted(p for p in path.glob("*.json") if p.name != "jobs.json"))
    unique = []
    seen = set()
    for path in found:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def write_reports(issues: list[Issue], bundles: list[ExamBundle], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "history_audit_issues.csv"
    md_path = out_dir / "history_audit_report.md"
    summary_path = out_dir / "history_audit_summary.csv"

    fields = ["root", "severity", "code", "message", "questionId", "group", "number", "expected", "actual"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for issue in issues:
            writer.writerow(issue.row())

    counts: dict[str, dict[str, int]] = {}
    for bundle in bundles:
        root = bundle.data.get("exam_id") or bundle.root
        counts[root] = {"BLOCKER": 0, "HIGH": 0, "MEDIUM": 0, "INFO": 0}
    for issue in issues:
        counts.setdefault(issue.root, {"BLOCKER": 0, "HIGH": 0, "MEDIUM": 0, "INFO": 0})
        counts[issue.root][issue.severity] = counts[issue.root].get(issue.severity, 0) + 1

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["root", "blocker", "high", "medium", "info", "verdict"])
        for root, c in sorted(counts.items()):
            verdict = "FAIL" if c["BLOCKER"] else "REVIEW" if c["HIGH"] or c["MEDIUM"] else "PASS"
            writer.writerow([root, c["BLOCKER"], c["HIGH"], c["MEDIUM"], c["INFO"], verdict])

    total = len(issues)
    blockers = sum(1 for i in issues if i.severity == "BLOCKER")
    high = sum(1 for i in issues if i.severity == "HIGH")
    medium = sum(1 for i in issues if i.severity == "MEDIUM")
    lines = [
        "# Historia Audit",
        "",
        f"Bundles audited: {len(bundles)}",
        f"Issues: {total} ({blockers} BLOCKER, {high} HIGH, {medium} MEDIUM)",
        "",
        "## Verdicts",
        "",
    ]
    for root, c in sorted(counts.items()):
        verdict = "FAIL" if c["BLOCKER"] else "REVIEW" if c["HIGH"] or c["MEDIUM"] else "PASS"
        lines.append(f"- **{root}**: {verdict} -- B:{c['BLOCKER']} H:{c['HIGH']} M:{c['MEDIUM']} I:{c['INFO']}")

    lines.extend(["", "## Top Issues", ""])
    for issue in issues[:80]:
        where = f" `{issue.question_id}`" if issue.question_id else ""
        lines.append(f"- **{issue.severity} {issue.code}**{where}: {issue.message}")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Historia exam outputs for objective quality gates.")
    parser.add_argument("paths", nargs="+", help="ZIP, exam.json, output folder, or folder containing many outputs.")
    parser.add_argument("--out", default="data/audit/history", help="Directory for CSV/Markdown reports.")
    args = parser.parse_args(argv)

    input_paths = discover_inputs([Path(p) for p in args.paths])
    if not input_paths:
        print("No audit inputs found.", file=sys.stderr)
        return 2

    bundles: list[ExamBundle] = []
    issues: list[Issue] = []
    for path in input_paths:
        try:
            bundle = ExamBundle(path)
        except Exception as exc:
            issues.append(Issue(path.stem, "BLOCKER", "LOAD_FAILED", str(exc)))
            continue
        subject = str((bundle.data.get("metadata") or {}).get("subject") or "").lower()
        if "hist" not in subject and "hist" not in str(bundle.data.get("exam_id") or bundle.root).lower():
            continue
        bundles.append(bundle)
        issues.extend(audit_bundle(bundle))

    write_reports(issues, bundles, Path(args.out))
    blockers = sum(1 for i in issues if i.severity == "BLOCKER")
    high = sum(1 for i in issues if i.severity == "HIGH")
    print(f"Audited {len(bundles)} Historia output(s). BLOCKER={blockers} HIGH={high} issues={len(issues)}")
    print(f"Reports written to {Path(args.out).resolve()}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
