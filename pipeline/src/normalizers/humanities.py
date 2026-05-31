"""Humanities normalizer: rules for Português, História, Filosofia, Geografia."""
import re


def normalize_humanities(output: dict, extraction: dict | None = None) -> dict:
    """Transform sourceRefs into media entries for the preview."""
    _attach_intro_group_visuals(output)
    _repair_explicit_document_refs(output)

    sources = {s.get("sourceId"): s for s in output.get("sources", [])}
    assets_map = {a.get("id"): a for a in output.get("assets", [])}

    for q in output.get("questions", []):
        refs = q.get("sourceRefs") or []
        if not refs:
            continue

        q["visualDependency"] = True
        media = q.setdefault("media", [])

        for ref in refs:
            source = sources.get(ref.get("sourceId"))
            if not source:
                continue

            # Specific child: show internal asset (e.g. imagem D)
            if ref.get("childId") and source.get("assetRefs"):
                letter = str(ref.get("childId") or "").split("_")[-1].lower()
                idx = ord(letter) - ord("a") if letter.isalpha() else -1
                if 0 <= idx < len(source["assetRefs"]):
                    asset = assets_map.get(source["assetRefs"][idx])
                    url = _best_asset_url(asset)
                    if url:
                        _append_once(media, {
                            "type": "source_image",
                            "url": url,
                            "sourceId": source.get("sourceId"),
                            "label": f"{source.get('label', '')} — imagem {letter.upper()}",
                        })
                        continue

            # Full source document
            url = _best_source_url(source)
            if url:
                _append_once(media, {
                    "type": "source",
                    "url": url,
                    "sourceId": source.get("sourceId"),
                    "label": source.get("label") or source.get("sourceId"),
                })

    return output


def _attach_intro_group_visuals(output: dict) -> None:
    """Attach the intro image/document to Q1/Q2 when sourceRefs are missing."""
    questions = output.get("questions", [])
    assets = output.get("assets", [])
    sources = output.setdefault("sources", [])

    first_questions = [
        q for q in questions
        if str(q.get("number")) in {"1", "2"}
        and not q.get("sourceRefs")
        and not q.get("parentQuestion")
    ]
    if not first_questions:
        return

    min_q_page = min((q.get("sourcePage") or 999) for q in first_questions)

    candidate_assets = [
        a for a in assets
        if (a.get("page") or 999) < min_q_page
        and not _is_accessibility_asset(a)
        and _asset_has_crop(a)
    ]
    if not candidate_assets:
        return

    candidate_assets.sort(key=lambda a: abs((a.get("page") or 0) - min_q_page))
    asset = candidate_assets[0]
    source_id = "grupo_i_documento_1"

    if not any(s.get("sourceId") == source_id for s in sources):
        url = _best_asset_url(asset)
        rel = _url_to_rel(url)
        sources.append({
            "sourceId": source_id,
            "groupId": "grupo_i",
            "label": "Documento 1",
            "kind": "image",
            "pageStart": asset.get("page"),
            "assetRefs": [asset.get("id")],
            "crops": {"best": {"status": "success", "url": url, "relativePath": rel}} if url else {},
        })

    for q in first_questions:
        q["group"] = q.get("group") or "Grupo I"
        q["sourceRefs"] = [{"sourceId": source_id, "childId": None, "mode": "full_group"}]
        q["visualDependency"] = True


def _repair_explicit_document_refs(output: dict) -> None:
    """Fix sourceRefs when the statement explicitly mentions a document number."""
    sources = output.get("sources", [])

    for q in output.get("questions", []):
        text = f"{q.get('statement', '')} {q.get('rawText', '')}".lower()
        group = (q.get("group") or "").lower().replace(" ", "_")
        if not group:
            continue

        refs = []
        for doc_num in ("1", "2", "3", "4"):
            if f"documento {doc_num}" not in text:
                continue
            wanted = f"{group}_documento_{doc_num}"
            source = next((s for s in sources if str(s.get("sourceId", "")).startswith(wanted)), None)
            if source:
                refs.append({"sourceId": source["sourceId"], "childId": None, "mode": "full_group"})

        if refs:
            q["sourceRefs"] = refs
            q["visualDependency"] = True


def _best_source_url(source: dict | None) -> str | None:
    if not source:
        return None
    crops = source.get("crops") or {}
    crop = crops.get("best") or crops.get("full") or crops.get("document") or crops.get("visual")
    return (crop.get("url") or crop.get("relativePath")) if isinstance(crop, dict) else None


def _best_asset_url(asset: dict | None) -> str | None:
    if not asset:
        return None
    crops = asset.get("crops") or {}
    crop = crops.get("best") or asset.get("crop") or crops.get("visual") or crops.get("full")
    if isinstance(crop, dict):
        return crop.get("url") or crop.get("relativePath")
    return asset.get("url") or asset.get("relativePath")


def _asset_has_crop(asset: dict) -> bool:
    crops = asset.get("crops") or {}
    return bool(crops.get("best") or crops.get("visual") or crops.get("context") or asset.get("crop"))


def _is_accessibility_asset(asset: dict) -> bool:
    text = f"{asset.get('id', '')} {asset.get('description', '')}".lower()
    return "coloradd" in text or "cores" in text


def _url_to_rel(url: str | None) -> str | None:
    if not url:
        return None
    if "/assets/" in url:
        return "assets/" + url.split("/assets/", 1)[1]
    return url if url.startswith("assets/") else None


def _append_once(media: list[dict], item: dict) -> None:
    url = item.get("url")
    if url and not any(m.get("url") == url for m in media):
        media.append(item)
