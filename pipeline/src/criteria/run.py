"""Criteria pipeline entry point.

Usage:
    uv run python -m src.criteria.run <exam_id>
    uv run python -m src.criteria.run <exam_id> --pdf path/to/criterios.pdf
    uv run python -m src.criteria.run <exam_id> --url https://.../Criterios.pdf

Reads data/output/{exam_id}.json, fetches the official criteria PDF, extracts
and parses it, matches to the exam questions, audits, and writes
data/output/{exam_id}.criteria.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..config import OPENROUTER_API_KEY
from ..utils.progress import report_progress
from . import urls
from .extractor import extract_pdf_text, render_pages_to_images
from .parser import parse_criteria_text
from .matcher import match_criteria_to_questions
from .audit import audit_criteria

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "output"
CRITERIA_UPLOAD_DIR = BASE_DIR / "data" / "uploads" / "criteria"
CRITERIA_EXTRACT_DIR = BASE_DIR / "data" / "extracted"

EXAM_CODE_PORTUGUES = "639"


def _load_exam(exam_id: str) -> dict:
    path = OUTPUT_DIR / f"{exam_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Exam output not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _is_portuguese(exam: dict) -> bool:
    subj = str((exam.get("metadata") or {}).get("subject") or "").lower()
    return "portug" in subj


def _vision_items_to_struct(raw_items: list[dict], default_page: int) -> list[dict[str, Any]]:
    """Normalize LLM-extracted criteria items into the parser's item shape."""
    roman = {"GRUPO I": "grupo_i", "GRUPO II": "grupo_ii", "GRUPO III": "grupo_iii",
             "I": "grupo_i", "II": "grupo_ii", "III": "grupo_iii"}
    out: list[dict[str, Any]] = []
    for it in raw_items or []:
        grp = str(it.get("grupo") or "").strip().upper()
        gid = roman.get(grp) or roman.get(grp.replace("GRUPO ", "").strip()) or ""
        if not gid:
            continue
        ca = it.get("correctAnswer")
        correct = None
        if isinstance(ca, dict):
            correct = {k: str(v).upper() for k, v in ca.items() if v}
        elif isinstance(ca, str) and ca.strip():
            correct = {"v1": ca.strip().upper().strip("()")}
        out.append({
            "groupId": gid,
            "number": str(it.get("numero") or "").strip().rstrip("."),
            "points": it.get("points"),
            "type": it.get("type") or ("multiple_choice" if correct else "open_answer"),
            "correctAnswer": correct,
            "rawText": str(it.get("rawText") or "").strip(),
            "sourcePages": [it.get("sourcePage") or default_page],
            "contentTopics": it.get("contentTopics") or [],
            "confidence": float(it.get("confidence") or 0.6),
            "source": "vision",
        })
    return out


def _extract_via_vision(pdf_path: str, exam_id: str) -> dict[str, Any]:
    """Vision OCR fallback for legacy scanned criteria PDFs."""
    from ..tools.vision_tool import _call_vision, _parse_json
    from .prompts import criteria_vision_prompt

    out_dir = CRITERIA_EXTRACT_DIR / f"{exam_id}_criteria"
    images = render_pages_to_images(pdf_path, str(out_dir))
    all_items: list[dict[str, Any]] = []
    for page_num, image_path in sorted(images.items()):
        content = _call_vision(image_path, criteria_vision_prompt(page_num), max_tokens=2048)
        data = _parse_json(content) if content else None
        if data and isinstance(data.get("criteriaItems"), list):
            all_items += _vision_items_to_struct(data["criteriaItems"], page_num)

    # Merge duplicate items (same group+number) keeping the most complete.
    merged: dict[tuple[str, str], dict] = {}
    for it in all_items:
        key = (it["groupId"], it["number"])
        if key not in merged:
            merged[key] = it
            continue
        prev = merged[key]
        # Prefer the one with an answer or higher confidence / longer rawText.
        if (it.get("correctAnswer") and not prev.get("correctAnswer")) or \
           len(it.get("rawText", "")) > len(prev.get("rawText", "")):
            merged[key] = it

    items = list(merged.values())
    versions: dict[str, list[dict[str, str]]] = {"1": [], "2": []}
    for it in items:
        ca = it.get("correctAnswer") or {}
        if ca.get("v1"):
            versions["1"].append({"groupId": it["groupId"], "number": it["number"], "correctAnswer": ca["v1"]})
        if ca.get("v2"):
            versions["2"].append({"groupId": it["groupId"], "number": it["number"], "correctAnswer": ca["v2"]})
    answer_keys = []
    if versions["1"]:
        answer_keys.append({"version": "1", "default": True, "items": versions["1"]})
    if versions["2"]:
        answer_keys.append({"version": "2", "default": False, "items": versions["2"]})
    return {"items": items, "answerKeys": answer_keys, "crossCheck": {}}


def build_criteria(
    exam_id: str,
    *,
    pdf_path: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    exam = _load_exam(exam_id)
    metadata = exam.get("metadata") or {}
    questions = exam.get("questions") or []

    if not _is_portuguese(exam):
        raise ValueError(f"Criteria pipeline currently supports Portuguese only (got subject={metadata.get('subject')!r}).")

    year, phase = urls.parse_year_phase(metadata)
    report_progress("criteria_resolve", f"Resolving criteria PDF for {year} fase {phase}")

    tried: list[str] = []
    if pdf_path is None:
        if url is None:
            url, tried = urls.resolve_criteria_url(metadata)
            if not url:
                raise RuntimeError(
                    f"Could not resolve criteria PDF URL for {year}-{phase}fase. Tried: {tried}"
                )
        CRITERIA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = str(CRITERIA_UPLOAD_DIR / f"{exam_id}_criterios.pdf")
        report_progress("criteria_download", f"Downloading {url}")
        size = urls.download_criteria(url, pdf_path)
        report_progress("criteria_download_done", f"Downloaded {size} bytes")

    report_progress("criteria_extract", "Extracting criteria text")
    extracted = extract_pdf_text(pdf_path)

    if extracted.text_quality == "native":
        report_progress("criteria_parse", "Parsing native-text criteria")
        parsed = parse_criteria_text(extracted)
        extraction_mode = "native_text"
    else:
        if not OPENROUTER_API_KEY:
            raise RuntimeError("Criteria PDF is scanned and needs vision OCR, but OPENROUTER_API_KEY is not set.")
        report_progress("criteria_vision", "Scanned PDF — running vision OCR fallback")
        parsed = _extract_via_vision(pdf_path, exam_id)
        extraction_mode = "vision_ocr"

    items = parsed["items"]
    report_progress("criteria_match", f"Matching {len(items)} criteria items to {len(questions)} questions")
    items, unmatched = match_criteria_to_questions(items, questions)

    # Inject stable criteriaId and singular sourcePage for schema compatibility.
    for item in items:
        gid_short = item.get("groupId", "").replace("grupo_", "g")
        num = str(item.get("number", "")).replace(".", "_")
        item.setdefault("criteriaId", f"{exam_id}_{gid_short}_{num}")
        pages = item.get("sourcePages") or []
        item.setdefault("sourcePage", pages[0] if pages else None)

    report_progress("criteria_audit", "Auditing criteria")
    audit = audit_criteria(items, questions, unmatched)

    matched = sum(1 for it in items if it.get("status") == "matched")
    status = "processed" if audit["verdict"] == "PASS" else "needs_review"

    criteria_doc = {
        "examId": exam_id,
        "status": status,
        "metadata": {
            "subject": metadata.get("subject"),
            "year": year,
            "phase": metadata.get("phase"),
            "examCode": EXAM_CODE_PORTUGUES,
            "documentType": "criteria",
            "sourcePdf": url,
            "sourcePdfTried": tried or None,
            "pages": extracted.total_pages,
            "extractionMode": extraction_mode,
            "textQuality": extracted.text_quality,
            "matchedQuestions": matched,
            "unmatchedQuestions": unmatched,
            "crossCheck": parsed.get("crossCheck") or {},
        },
        "answerKeys": parsed["answerKeys"],
        "items": items,
        "audit": audit,
    }

    out_path = OUTPUT_DIR / f"{exam_id}.criteria.json"
    out_path.write_text(json.dumps(criteria_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    report_progress(
        "criteria_done",
        f"Saved {out_path.name}: {matched}/{len(questions)} matched, "
        f"verdict={audit['verdict']} ({audit['high']} high, {audit['blocker']} blocker)",
    )
    return criteria_doc


def main() -> None:
    parser = argparse.ArgumentParser(description="Build official criteria.json for an exam.")
    parser.add_argument("exam_id")
    parser.add_argument("--pdf", help="Use a local criteria PDF instead of downloading.")
    parser.add_argument("--url", help="Override the criteria PDF URL.")
    args = parser.parse_args()

    try:
        build_criteria(args.exam_id, pdf_path=args.pdf, url=args.url)
    except Exception as e:  # noqa: BLE001
        report_progress("error", str(e))
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
