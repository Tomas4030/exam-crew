"""Golden-set regression harness for the criteria pipeline.

The golden set is built from criteria PDFs already cached in
data/uploads/criteria/ whose exam JSON still exists in data/output/.
For each exam we run extract → parse → match → audit fully offline and
record a compact summary (items, points, answers, verdict). Any future
change to the parser/matcher/audit that alters one of these summaries
makes the regression test fail loudly.

Usage:
    uv run python -m tests.golden_tool update     # (re)build snapshots
    uv run python -m tests.golden_tool check      # compare against snapshots
    uv run python -m pytest tests/test_golden.py  # same check via pytest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PIPELINE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = PIPELINE_DIR.parent
CRITERIA_PDF_DIR = BASE_DIR / "data" / "uploads" / "criteria"
OUTPUT_DIR = BASE_DIR / "data" / "output"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

sys.path.insert(0, str(PIPELINE_DIR))


def _golden_cases() -> list[tuple[str, Path, Path]]:
    """Return (exam_id, criteria_pdf, exam_json) for every cached pair."""
    cases = []
    for pdf in sorted(CRITERIA_PDF_DIR.glob("*_criterios.pdf")):
        exam_id = pdf.name.removesuffix("_criterios.pdf")
        exam_json = OUTPUT_DIR / f"{exam_id}.json"
        if exam_json.exists():
            cases.append((exam_id, pdf, exam_json))
    return cases


def _summarize(exam_id: str, pdf_path: Path, exam_json: Path) -> dict[str, Any]:
    """Run the offline criteria pipeline and produce a compact, stable summary."""
    from src.criteria.extractor import extract_pdf_text
    from src.criteria.parser import parse_criteria_text
    from src.criteria.matcher import match_criteria_to_questions
    from src.criteria.audit import audit_criteria

    exam = json.loads(exam_json.read_text(encoding="utf-8"))
    questions = exam.get("questions") or []
    metadata = exam.get("metadata") or {}

    extracted = extract_pdf_text(str(pdf_path))
    if extracted.text_quality != "native":
        return {
            "examId": exam_id,
            "subject": metadata.get("subject"),
            "year": metadata.get("year"),
            "skipped": "scanned_pdf",
        }

    parsed = parse_criteria_text(extracted)
    items, unmatched = match_criteria_to_questions(parsed["items"], questions)
    audit = audit_criteria(items, questions, unmatched)

    return {
        "examId": exam_id,
        "subject": metadata.get("subject"),
        "year": metadata.get("year"),
        "phase": metadata.get("phase"),
        "items": [
            {
                "group": it.get("groupId"),
                "number": it.get("number"),
                "points": it.get("points"),
                "type": it.get("type"),
                "answer": (it.get("correctAnswer") or {}).get("v1"),
                "match": it.get("match"),
            }
            for it in items
        ],
        "unmatchedQuestions": sorted(str(u) for u in unmatched),
        "verdict": audit.get("verdict"),
        "high": audit.get("high"),
        "blocker": audit.get("blocker"),
        "issueCodes": sorted({i["code"] for i in audit.get("issues", [])}),
    }


def update() -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    cases = _golden_cases()
    written = 0
    for exam_id, pdf, exam_json in cases:
        try:
            summary = _summarize(exam_id, pdf, exam_json)
        except Exception as exc:  # snapshot the failure so regressions catch it too
            summary = {"examId": exam_id, "error": f"{type(exc).__name__}: {exc}"}
        out = GOLDEN_DIR / f"{exam_id}.json"
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        written += 1
        print(f"  snapshot {exam_id}: verdict={summary.get('verdict', summary.get('skipped', summary.get('error')))}")
    print(f"Wrote {written} golden snapshot(s) to {GOLDEN_DIR}")
    return 0


def check(verbose: bool = True) -> list[str]:
    """Return a list of human-readable diffs (empty = all good)."""
    failures: list[str] = []
    snapshots = sorted(GOLDEN_DIR.glob("*.json"))
    if not snapshots:
        failures.append("No golden snapshots found — run: uv run python -m tests.golden_tool update")
        return failures

    for snap_file in snapshots:
        exam_id = snap_file.stem
        expected = json.loads(snap_file.read_text(encoding="utf-8"))
        pdf = CRITERIA_PDF_DIR / f"{exam_id}_criterios.pdf"
        exam_json = OUTPUT_DIR / f"{exam_id}.json"
        if not pdf.exists() or not exam_json.exists():
            if verbose:
                print(f"  SKIP {exam_id}: inputs no longer on disk")
            continue
        try:
            actual = _summarize(exam_id, pdf, exam_json)
        except Exception as exc:
            actual = {"examId": exam_id, "error": f"{type(exc).__name__}: {exc}"}

        if actual != expected:
            diff_lines = _diff(expected, actual)
            failures.append(f"{exam_id}:\n" + "\n".join(f"    {d}" for d in diff_lines))
            if verbose:
                print(f"  FAIL {exam_id}")
                for d in diff_lines[:8]:
                    print(f"       {d}")
        elif verbose:
            print(f"  ok   {exam_id} (verdict={expected.get('verdict', expected.get('skipped'))})")
    return failures


def _diff(expected: dict, actual: dict) -> list[str]:
    lines: list[str] = []
    keys = sorted(set(expected) | set(actual))
    for k in keys:
        ev, av = expected.get(k), actual.get(k)
        if ev == av:
            continue
        if k == "items" and isinstance(ev, list) and isinstance(av, list):
            e_by = {(i.get("group"), i.get("number")): i for i in ev}
            a_by = {(i.get("group"), i.get("number")): i for i in av}
            for ik in sorted(set(e_by) | set(a_by), key=str):
                if e_by.get(ik) != a_by.get(ik):
                    lines.append(f"item {ik}: {e_by.get(ik)} -> {a_by.get(ik)}")
        else:
            lines.append(f"{k}: {ev!r} -> {av!r}")
    return lines or ["(structural difference)"]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "update":
        raise SystemExit(update())
    fails = check()
    if fails:
        print(f"\n{len(fails)} golden regression(s):")
        for f in fails:
            print(f"- {f}")
        raise SystemExit(1)
    print("\nAll golden snapshots match.")
