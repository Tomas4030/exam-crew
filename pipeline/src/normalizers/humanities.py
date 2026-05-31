"""Humanities normalizer: rules for Português, História, Filosofia, Geografia."""


def normalize_humanities(output: dict, extraction: dict | None = None) -> dict:
    """Apply humanities-specific corrections.

    Ensures questions with sourceRefs have media entries so the preview
    can show documents even if the frontend doesn't read sourceRefs directly.
    """
    sources = {s.get("sourceId"): s for s in output.get("sources", [])}

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
            crops = source.get("crops") or {}
            crop = (
                crops.get("best")
                or crops.get("full")
                or crops.get("document")
                or crops.get("visual")
                or crops.get("context")
            )
            url = crop.get("url") if isinstance(crop, dict) else None
            if not url:
                continue
            if not any(m.get("url") == url for m in media):
                media.append({
                    "type": "source",
                    "url": url,
                    "sourceId": source.get("sourceId"),
                    "label": source.get("label") or source.get("sourceId"),
                })

    return output
