from __future__ import annotations

from pathlib import Path


def _url_to_relative(url: str, exam_id: str) -> str | None:
    marker = f"/api/exams/{exam_id}/assets/"
    if marker in url:
        return "assets/" + url.split(marker, 1)[1]
    if "/assets/" in url:
        return "assets/" + url.split("/assets/", 1)[1]
    if url.startswith("assets/"):
        return url
    return None


def _exists_for_ref(output_exam_dir: Path, ref: str, exam_id: str) -> bool:
    rel = _url_to_relative(ref, exam_id) if ref.startswith("/") else ref
    if not rel:
        return False
    return (output_exam_dir / rel).exists()


def _collect_crop_refs(container: dict) -> list[tuple[str, dict]]:
    refs: list[tuple[str, dict]] = []
    crops = container.get("crops") or {}
    if isinstance(crops, dict):
        for key, crop in crops.items():
            if key == "children" and isinstance(crop, dict):
                for child_id, child_crop in crop.items():
                    if isinstance(child_crop, dict):
                        refs.append((f"crops.children.{child_id}", child_crop))
                continue
            if isinstance(crop, dict):
                refs.append((f"crops.{key}", crop))

    child_crops = container.get("childCrops") or {}
    if isinstance(child_crops, dict):
        for child_id, crop in child_crops.items():
            if isinstance(crop, dict):
                refs.append((f"childCrops.{child_id}", crop))
    return refs


def enforce_asset_integrity(output: dict, output_root: Path) -> dict:
    exam_id = output.get("exam_id", "")
    if not exam_id:
        return output

    output_exam_dir = output_root / exam_id
    warnings = output.setdefault("warnings", [])

    # questions[].media
    for q in output.get("questions", []):
        media = q.get("media") or []
        if not isinstance(media, list):
            continue
        kept = []
        for m in media:
            url = (m or {}).get("url")
            if not url:
                continue
            if _exists_for_ref(output_exam_dir, url, exam_id):
                kept.append(m)
            else:
                warnings.append(
                    {
                        "type": "missing_media_ref",
                        "message": f"Removed missing media ref for {q.get('questionId')}: {url}",
                    }
                )
        q["media"] = kept

    # assets/sources crop refs
    for group in ("assets", "sources", "sourceGroups"):
        for item in output.get(group, []):
            for path_key, crop in _collect_crop_refs(item):
                rel = crop.get("relativePath")
                url = crop.get("url")
                ref = rel or url
                if not ref:
                    continue
                if _exists_for_ref(output_exam_dir, ref, exam_id):
                    continue
                crop["status"] = "missing"
                crop["reason"] = "missing_file"
                crop.pop("url", None)
                crop.pop("relativePath", None)
                warnings.append(
                    {
                        "type": "missing_crop_ref",
                        "message": f"Removed missing crop ref {group}.{item.get('id') or item.get('sourceId')}::{path_key}",
                    }
                )

    return output

