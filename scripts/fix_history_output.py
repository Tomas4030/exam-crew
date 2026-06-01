#!/usr/bin/env python3
"""Hotfix for História A outputs generated before the source-reference fix.

Usage from project root:
  python scripts/fix_history_output.py data/output/<exam_id>.json

What it fixes:
- Rebuilds question.media from sourceRefs so stale duplicated images disappear.
- Resolves mixed refs like "imagem A do documento 1 e documentos 2 e 3".
- Splits a lettered "Documento 1 (conjunto documental)" into A/B/C/D child crops.
- Creates a full source crop for Grupo I from data/extracted/<exam_id>/pages/page_N.png
  when the previous output only has a too-tight context/visual crop.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from PIL import Image

DOC_REF_RE = re.compile(r"\bdocumento\s+(\d+)\b", re.IGNORECASE)
PLURAL_DOC_REF_RE = re.compile(r"\bdocumentos\s+((?:\d+[\s,;e]*)+)", re.IGNORECASE)
CHILD_OF_DOC_RE = re.compile(r"\bimagem\s+([A-Z])\s+(?:do|da)\s+documento\s+(\d+)\b", re.IGNORECASE)
DOC_CHILD_RE = re.compile(r"\bdocumento\s+(\d+)\s*[,;:\-\u2013\u2014]?\s*imagem\s+([A-Z])\b", re.IGNORECASE)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python fix_history_output.py data/output/<exam_id>.json", file=sys.stderr)
        return 2

    json_path = Path(sys.argv[1]).resolve()
    output_dir = json_path.with_suffix("")
    # Normal app layout: data/output/<exam_id>.json + data/output/<exam_id>/assets.
    # Export ZIP layout: exam.json + assets directly next to it.
    if not (output_dir / "assets").exists() and (json_path.parent / "assets").exists():
        output_dir = json_path.parent
    data = json.loads(json_path.read_text(encoding="utf-8"))
    exam_id = data.get("exam_id") or json_path.stem

    sources = data.get("sources", [])
    questions = data.get("questions", [])

    _ensure_source_full_crop_for_group_i(data, json_path, output_dir, exam_id)
    _ensure_lettered_children(data, output_dir, exam_id)

    source_by_id = {s.get("sourceId"): s for s in sources}
    source_ids = set(source_by_id)

    for q in questions:
        statement = f"{q.get('statement', '')} {q.get('rawText', '')}"
        group_id = q.get("groupId") or _group_label_to_id(q.get("group"))
        if not group_id:
            continue

        refs = _refs_from_statement(statement, group_id, source_ids)
        if refs:
            q["sourceRefs"] = refs
            q["visualDependency"] = True

        # Always rebuild media from sourceRefs to remove stale/doubled entries.
        if q.get("sourceRefs"):
            q["media"] = _media_from_refs(q["sourceRefs"], source_by_id)

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fixed {json_path}")
    return 0


def _group_label_to_id(group: str | None) -> str | None:
    if not group:
        return None
    return group.strip().lower().replace(" ", "_")


def _refs_from_statement(statement: str, group_id: str, source_ids: set[str]) -> list[dict[str, Any]]:
    child_by_doc: dict[str, list[str]] = {}
    for m in CHILD_OF_DOC_RE.finditer(statement):
        letter, doc_num = m.group(1).upper(), m.group(2)
        child_by_doc.setdefault(doc_num, []).append(letter)
    for m in DOC_CHILD_RE.finditer(statement):
        doc_num, letter = m.group(1), m.group(2).upper()
        child_by_doc.setdefault(doc_num, []).append(letter)

    doc_nums = set(DOC_REF_RE.findall(statement))
    for plural_m in PLURAL_DOC_REF_RE.finditer(statement):
        doc_nums.update(re.findall(r"\d+", plural_m.group(1)))

    refs: list[dict[str, Any]] = []
    for doc_num in sorted(doc_nums, key=lambda n: int(n)):
        prefix = f"{group_id}_documento_{doc_num}"
        source_id = next((sid for sid in source_ids if str(sid).startswith(prefix)), None)
        if not source_id:
            continue
        letters = child_by_doc.get(doc_num, [])
        if letters:
            for letter in letters:
                refs.append({"sourceId": source_id, "childId": f"{source_id}_{letter.lower()}", "mode": "specific_child"})
        else:
            refs.append({"sourceId": source_id, "childId": None, "mode": "full_group"})

    return _dedupe_refs(refs)


def _media_from_refs(refs: list[dict[str, Any]], source_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    media: list[dict[str, Any]] = []
    for ref in refs:
        source = source_by_id.get(ref.get("sourceId"))
        if not source:
            continue
        child_id = ref.get("childId")
        if child_id:
            crop = (source.get("childCrops") or {}).get(child_id) or ((source.get("crops") or {}).get("children") or {}).get(child_id)
            url = _crop_url(crop)
            if url:
                letter = child_id.split("_")[-1].upper()
                media.append({"type": "source_image", "url": url, "sourceId": source.get("sourceId"), "childId": child_id, "label": f"{source.get('label', '')} \u2014 imagem {letter}"})
            continue

        crop = (source.get("crops") or {}).get("best") or (source.get("crops") or {}).get("full")
        url = _crop_url(crop)
        if url:
            media.append({"type": "source", "url": url, "sourceId": source.get("sourceId"), "label": source.get("label") or source.get("sourceId")})

    # de-duplicate by source/child/url
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for item in media:
        key = (item.get("sourceId"), item.get("childId"), item.get("url"))
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _ensure_lettered_children(data: dict[str, Any], output_dir: Path, exam_id: str) -> None:
    sources_dir = output_dir / "assets" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    for source in data.get("sources", []):
        text = f"{source.get('label', '')} {source.get('description', '')}"
        if "conjunto documental" not in text.lower():
            continue
        if source.get("childCrops"):
            continue

        full_rel = _crop_rel((source.get("crops") or {}).get("full") or (source.get("crops") or {}).get("best"))
        if not full_rel:
            continue
        full_path = output_dir / full_rel
        if not full_path.exists():
            continue

        img = Image.open(full_path)
        child_crops: dict[str, dict[str, Any]] = {}
        children: list[str] = []
        for letter, box in _quadrant_boxes(img.size).items():
            child_id = f"{source.get('sourceId')}_{letter.lower()}"
            filename = f"{child_id}.png"
            path = sources_dir / filename
            crop = img.crop(box)
            crop.save(path)
            info = {
                "status": "success",
                "method": "lettered_source_quadrant",
                "relativePath": f"assets/sources/{filename}",
                "url": f"/api/exams/{exam_id}/assets/sources/{filename}",
                "width": crop.width,
                "height": crop.height,
            }
            child_crops[child_id] = info
            children.append(child_id)

        source["kind"] = "image_set"
        source["children"] = children
        source["childCrops"] = child_crops
        source.setdefault("crops", {})["children"] = child_crops


def _ensure_source_full_crop_for_group_i(data: dict[str, Any], json_path: Path, output_dir: Path, exam_id: str) -> None:
    source = next((s for s in data.get("sources", []) if s.get("sourceId") == "grupo_i_documento_1"), None)
    if not source:
        return

    page_num = source.get("pageStart")
    if not page_num:
        return

    # If a proper source crop already exists, keep it.
    current = (source.get("crops") or {}).get("full")
    if current and (output_dir / (current.get("relativePath") or "")).exists():
        source.setdefault("crops", {})["best"] = current
        return

    # Try to recover from the original rendered page: data/extracted/<exam_id>/pages/page_N.png
    data_dir = json_path.parent.parent
    page_render = data_dir / "extracted" / exam_id / "pages" / f"page_{page_num}.png"
    if not page_render.exists():
        return

    img = Image.open(page_render)
    w, h = img.size
    cropped = img.crop((int(w * 0.025), int(h * 0.055), int(w * 0.975), int(h * 0.92)))

    sources_dir = output_dir / "assets" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    filename = "grupo_i_documento_1_full.png"
    path = sources_dir / filename
    cropped.save(path)
    info = {
        "status": "success",
        "method": "full_page_source_recovery",
        "relativePath": f"assets/sources/{filename}",
        "url": f"/api/exams/{exam_id}/assets/sources/{filename}",
        "width": cropped.width,
        "height": cropped.height,
    }
    source.setdefault("crops", {})["full"] = info
    source.setdefault("crops", {})["best"] = info


def _quadrant_boxes(size: tuple[int, int]) -> dict[str, tuple[int, int, int, int]]:
    w, h = size
    mid_x = w // 2
    overlap = int(w * 0.018)
    top = int(h * 0.035)
    top_bottom = int(h * 0.435)
    bottom_top = int(h * 0.410)
    bottom_bottom = int(h * 0.835)
    return {
        "A": (0, top, min(w, mid_x + overlap), top_bottom),
        "B": (max(0, mid_x - overlap), top, w, top_bottom),
        "C": (0, bottom_top, min(w, mid_x + overlap), bottom_bottom),
        "D": (max(0, mid_x - overlap), bottom_top, w, bottom_bottom),
    }


def _crop_url(crop: Any) -> str | None:
    return crop.get("url") or crop.get("relativePath") if isinstance(crop, dict) else None


def _crop_rel(crop: Any) -> str | None:
    return crop.get("relativePath") if isinstance(crop, dict) else None


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for ref in refs:
        key = (ref.get("sourceId"), ref.get("childId"), ref.get("mode"))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
