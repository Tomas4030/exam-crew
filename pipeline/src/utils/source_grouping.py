"""Source grouping v2: deterministic group/source detection for History exams.

Core principle: scan ALL pages to build page→group map FIRST, then detect
documents within each group, then assign questions, then resolve refs.
"""
import re
from collections import defaultdict


# ── Patterns ──────────────────────────────────────────────────────
_GROUP_PATTERN = re.compile(r'grupo\s+(I{1,3}V?|IV)\b', re.IGNORECASE)
_DOC_LABEL_PATTERN = re.compile(
    r'documento\s+(\d+)\s*(?:\(([^)]+)\))?', re.IGNORECASE
)
_SOURCE_REF_PATTERNS = [
    re.compile(r'[Dd]ocumento\s+(\d+)', re.IGNORECASE),
    re.compile(r'[Dd]oc\.?\s*(\d+)', re.IGNORECASE),
]
_CHILD_REF_PATTERN = re.compile(r'[Ii]magem\s+([A-Z])', re.IGNORECASE)

_ROMAN_MAP = {"I": "i", "II": "ii", "III": "iii", "IV": "iv", "V": "v"}


def _roman_to_id(roman: str) -> str:
    return _ROMAN_MAP.get(roman.strip(), roman.strip().lower())


# ══════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════

def apply_source_grouping(output: dict, subject_profile: dict, extraction: dict = None) -> dict:
    """Main entry: detect groups, sources, composite IDs, sourceRefs.

    Args:
        output: assembled exam output (questions, assets)
        subject_profile: from subjects.py
        extraction: raw PDF extraction with ALL page texts
    """
    if not subject_profile.get("has_source_grouping"):
        return output

    questions = output.get("questions", [])
    assets = output.get("assets", [])

    # ── Step 1: Build page→group map from ALL pages ───────────────
    page_group_map = _build_page_group_map(extraction, questions)

    if not page_group_map:
        return _simple_source_grouping(output, assets, questions)

    # ── Step 2: Assign group to every question ────────────────────
    _assign_groups_from_map(questions, page_group_map)

    has_groups = any(q.get("groupId") for q in questions)
    if not has_groups:
        return _simple_source_grouping(output, assets, questions)

    # ── Step 3: Generate composite questionIds ────────────────────
    _assign_composite_ids(questions)

    # ── Step 4: Detect sources per group ──────────────────────────
    sources = _detect_sources(assets, questions, page_group_map, extraction)

    # ── Step 5: Resolve sourceRefs by text within group ───────────
    _resolve_scoped_refs(questions, sources)

    # ── Step 6: Generate media field on questions ─────────────────
    _generate_media(questions, sources, assets, output.get("exam_id", ""))

    output["sources"] = sources
    return output


# ══════════════════════════════════════════════════════════════════
# STEP 1: Page → Group Map
# ══════════════════════════════════════════════════════════════════

def _build_page_group_map(extraction: dict | None, questions: list[dict]) -> dict[int, str]:
    """Scan ALL page texts to build {page_number: groupId}.

    Groups propagate forward: once 'Grupo II' is seen, all subsequent
    pages belong to Grupo II until 'Grupo III' appears.
    """
    page_texts: dict[int, str] = {}

    # Primary source: extraction pages (has ALL pages including source pages)
    if extraction and extraction.get("pages"):
        for p in extraction["pages"]:
            page_texts[p["page"]] = p.get("text", "")

    # Fallback: sourceTextRaw from questions (only question pages)
    if not page_texts:
        for q in questions:
            pg = q.get("sourcePage", 0)
            if pg and q.get("sourceTextRaw"):
                page_texts[pg] = q["sourceTextRaw"]

    if not page_texts:
        return {}

    # Scan pages in order, detect group headers
    page_group_map: dict[int, str] = {}
    current_group = None

    for page_num in sorted(page_texts.keys()):
        text = page_texts[page_num]
        # Skip cover/instructions (typically pages 1-3)
        if page_num <= 2:
            continue
        # Skip scoring page (contains COTAÇÕES table with group references)
        if "cotaç" in text.lower() or "cotaçõ" in text.lower():
            if current_group:
                page_group_map[page_num] = current_group
            continue

        match = _GROUP_PATTERN.search(text)
        if match:
            roman = match.group(1)
            current_group = f"grupo_{_roman_to_id(roman)}"

        if current_group:
            page_group_map[page_num] = current_group

    return page_group_map


# ══════════════════════════════════════════════════════════════════
# STEP 2: Assign groups to questions
# ══════════════════════════════════════════════════════════════════

def _assign_groups_from_map(questions: list[dict], page_group_map: dict[int, str]):
    """Assign groupId and group label to each question from the page map."""
    for q in questions:
        page = q.get("sourcePage", 0)
        gid = page_group_map.get(page)
        if gid:
            q["groupId"] = gid
            # "grupo_ii" → "Grupo II"
            roman = gid.replace("grupo_", "").upper()
            q["group"] = f"Grupo {roman}"


# ══════════════════════════════════════════════════════════════════
# STEP 3: Composite IDs
# ══════════════════════════════════════════════════════════════════

def _assign_composite_ids(questions: list[dict]):
    """Replace q1/q2 IDs with grupo_i_q1, grupo_ii_q1, etc."""
    old_to_new: dict[str, str] = {}

    for q in questions:
        gid = q.get("groupId")
        number = q.get("number", "")
        if not gid or not number:
            continue
        new_id = f"{gid}_q{number.replace('.', '_')}"
        old_to_new[q["questionId"]] = new_id
        q["questionId"] = new_id
        q["displayNumber"] = f"{q.get('group', '')}, item {number}"

    # Update parent/child references
    for q in questions:
        if q.get("parentQuestion") in old_to_new:
            q["parentQuestion"] = old_to_new[q["parentQuestion"]]
        q["subQuestions"] = [old_to_new.get(s, s) for s in q.get("subQuestions", [])]


# ══════════════════════════════════════════════════════════════════
# STEP 4: Detect sources per group
# ══════════════════════════════════════════════════════════════════

def _detect_sources(assets: list[dict], questions: list[dict],
                    page_group_map: dict[int, str], extraction: dict | None) -> list[dict]:
    """Detect source documents from page text and assets, scoped by group."""
    sources = []
    pages_with_questions = {q["sourcePage"] for q in questions}

    # Get page texts for document label detection
    page_texts: dict[int, str] = {}
    if extraction and extraction.get("pages"):
        for p in extraction["pages"]:
            page_texts[p["page"]] = p.get("text", "")

    # Find source pages (pages with group but no questions)
    source_pages = sorted(
        pg for pg, gid in page_group_map.items()
        if pg not in pages_with_questions
    )

    # For each source page, detect document labels from text
    # Track doc numbering per group
    group_doc_counter: dict[str, int] = defaultdict(int)
    # Track which doc numbers we've seen explicitly in text per group
    group_explicit_docs: dict[str, dict[int, int]] = defaultdict(dict)  # gid → {doc_num: page}

    for page in source_pages:
        gid = page_group_map.get(page)
        if not gid:
            continue

        text = page_texts.get(page, "")
        # Find explicit "Documento N" labels in page text
        doc_matches = list(_DOC_LABEL_PATTERN.finditer(text))

        if doc_matches:
            for m in doc_matches:
                doc_num = int(m.group(1))
                if doc_num not in group_explicit_docs[gid]:
                    group_explicit_docs[gid][doc_num] = page
        else:
            # No explicit label — this page has source material without "Documento N"
            # (e.g. Grupo I just has an image without labeling it "Documento 1")
            group_doc_counter[gid] += 1
            implicit_num = group_doc_counter[gid]
            # Only add if we haven't seen explicit docs for this group yet
            if not group_explicit_docs[gid]:
                group_explicit_docs[gid][implicit_num] = page

    # Also check question pages for documents (some docs appear on same page as questions)
    for page in sorted(pages_with_questions):
        gid = page_group_map.get(page)
        if not gid:
            continue
        text = page_texts.get(page, "")
        for m in _DOC_LABEL_PATTERN.finditer(text):
            doc_num = int(m.group(1))
            if doc_num not in group_explicit_docs[gid]:
                group_explicit_docs[gid][doc_num] = page

    # Build Source entities
    # First, identify pages with multiple documents to split assets correctly
    page_doc_counts: dict[int, list[int]] = defaultdict(list)  # page → [doc_nums]
    for gid in sorted(set(page_group_map.values())):
        for doc_num, page in group_explicit_docs.get(gid, {}).items():
            page_doc_counts[page].append(doc_num)

    for gid in sorted(set(page_group_map.values())):
        docs = group_explicit_docs.get(gid, {})
        for doc_num in sorted(docs.keys()):
            page = docs[doc_num]
            source_id = f"{gid}_documento_{doc_num}"

            # Find assets on this page — prefer embedded (clean PDF images)
            embedded = sorted(
                [a for a in assets if a.get("page") == page and a.get("type") == "embedded_image"],
                key=lambda a: a.get("id", "")
            )
            detected = sorted(
                [a for a in assets if a.get("page") == page and a.get("type") != "embedded_image"],
                key=lambda a: a.get("id", "")
            )
            all_page_assets = embedded if embedded else detected

            # If multiple documents share this page, split assets by position
            docs_on_page = sorted(page_doc_counts.get(page, [doc_num]))
            if len(docs_on_page) > 1 and all_page_assets:
                n_docs = len(docs_on_page)
                if len(all_page_assets) >= n_docs:
                    # Enough assets to split evenly
                    doc_idx = docs_on_page.index(doc_num)
                    chunk_size = max(1, len(all_page_assets) // n_docs)
                    start = doc_idx * chunk_size
                    end = start + chunk_size if doc_idx < n_docs - 1 else len(all_page_assets)
                    page_assets = all_page_assets[start:end]
                else:
                    # Fewer assets than documents — don't assign (use source.crops.full)
                    page_assets = []
            else:
                page_assets = all_page_assets

            # Determine kind and children
            kind = _infer_kind(page_assets, page_texts.get(page, ""))
            children = []

            # Multiple visual assets on same page → image_set with children
            if len(page_assets) > 1:
                kind = "image_set"
                for i, a in enumerate(sorted(page_assets, key=lambda x: x.get("id", ""))):
                    letter = chr(ord('a') + i)
                    child_id = f"{source_id}_{letter}"
                    children.append(child_id)
                    a["parentAssetId"] = source_id

            # Infer label from page text
            text = page_texts.get(page, "")
            label = f"Documento {doc_num}"
            for m in _DOC_LABEL_PATTERN.finditer(text):
                if int(m.group(1)) == doc_num and m.group(2):
                    label = f"Documento {doc_num} ({m.group(2)})"
                    break

            source = {
                "sourceId": source_id,
                "groupId": gid,
                "label": label,
                "kind": kind,
                "pageStart": page,
                "pageEnd": page,
                "description": _build_description(page_assets, text),
                "children": children,
                "assetRefs": [a["id"] for a in page_assets],
            }
            sources.append(source)

    return sources


# ══════════════════════════════════════════════════════════════════
# STEP 5: Resolve sourceRefs
# ══════════════════════════════════════════════════════════════════

def _resolve_scoped_refs(questions: list[dict], sources: list[dict]):
    """Resolve 'documento 1', 'documentos 1 e 2', 'imagem B' in question text within its group."""
    # Index: (groupId, doc_num_str) → source
    source_index: dict[tuple[str, str], dict] = {}
    for s in sources:
        m = re.search(r'_(\d+)$', s["sourceId"])
        if m:
            source_index[(s["groupId"], m.group(1))] = s

    # Group sources by groupId
    group_sources: dict[str, list[dict]] = defaultdict(list)
    for s in sources:
        group_sources[s["groupId"]].append(s)

    for q in questions:
        gid = q.get("groupId")
        if not gid:
            continue

        text = q.get("statement") or ""
        if not text.strip():
            continue

        source_refs = []
        doc_nums = set()

        # Match singular: "documento 1", "documento 2"
        for pat in _SOURCE_REF_PATTERNS:
            doc_nums.update(pat.findall(text))

        # Match plural: "documentos 1 e 2", "documentos 1, 2 e 3",
        # "cada um dos documentos 1, 2 e 3"
        for plural_m in re.finditer(r'documentos?\s+((?:\d+[\s,e]*)+)', text, re.IGNORECASE):
            doc_nums.update(re.findall(r'\d+', plural_m.group(1)))

        # "dos dois documentos" / "dos três documentos" / "cada um dos documentos" / "dos documentos apresentados"
        if not doc_nums and re.search(r'cada um dos documentos|dos documentos apresentados|dos dois documentos|dos três documentos', text, re.IGNORECASE):
            for s in group_sources.get(gid, []):
                source_refs.append({"sourceId": s["sourceId"], "childId": None, "mode": "full_group"})

        child_letters = [c.upper() for c in _CHILD_REF_PATTERN.findall(text)]

        for doc_num in sorted(doc_nums):
            source = source_index.get((gid, doc_num))
            if not source:
                continue

            if child_letters and source["children"]:
                for letter in child_letters:
                    child_id = f"{source['sourceId']}_{letter.lower()}"
                    if child_id in source["children"]:
                        source_refs.append({
                            "sourceId": source["sourceId"],
                            "childId": child_id,
                            "mode": "specific_child",
                        })
                n_children = len(source["children"])
                all_letters = {chr(ord('a') + i).upper() for i in range(n_children)}
                if all_letters and set(child_letters) >= all_letters:
                    source_refs.insert(0, {"sourceId": source["sourceId"], "childId": None, "mode": "full_group"})
            else:
                source_refs.append({"sourceId": source["sourceId"], "childId": None, "mode": "full_group"})

        if source_refs:
            q["sourceRefs"] = source_refs

    # Fallback: if a group has exactly 1 source and questions have no refs, auto-associate
    group_sources = defaultdict(list)
    for s in sources:
        group_sources[s["groupId"]].append(s)

    for q in questions:
        if q.get("sourceRefs"):
            continue
        gid = q.get("groupId")
        if gid and len(group_sources.get(gid, [])) == 1:
            sole_source = group_sources[gid][0]
            q["sourceRefs"] = [{"sourceId": sole_source["sourceId"], "childId": None, "mode": "full_group"}]


# ══════════════════════════════════════════════════════════════════
# FALLBACK for non-grouped exams
# ══════════════════════════════════════════════════════════════════

def _simple_source_grouping(output: dict, assets: list[dict], questions: list[dict]) -> dict:
    """Fallback for exams without Grupo structure."""
    pages_with_questions = {q["sourcePage"] for q in questions}
    source_pages = {a["page"] for a in assets
                    if a["page"] not in pages_with_questions
                    and a.get("type") != "embedded_image"}
    if not source_pages:
        return output

    source_groups = []
    for page in sorted(source_pages):
        page_assets = [a for a in assets if a["page"] == page and a.get("type") != "embedded_image"]
        if not page_assets:
            continue
        gid = f"source_group_p{page}"
        source_groups.append({
            "id": gid, "type": "source_group", "sourceType": "mixed",
            "page": page, "label": f"Documento p{page}",
            "description": _build_description(page_assets, ""),
            "children": [a["id"] for a in page_assets], "crops": None,
        })
        for a in page_assets:
            a["parentAssetId"] = gid

    output["sourceGroups"] = source_groups
    return output


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _infer_kind(assets: list[dict], page_text: str) -> str:
    """Infer document kind from assets and page text."""
    if not assets:
        # No visual assets — likely a text source
        if re.search(r'[Dd]ocumento\s+\d+', page_text):
            return "text_source"
        return "image"

    types = {a.get("type", "") for a in assets}
    if len(assets) > 1:
        return "image_set"
    if "table" in types:
        return "table"
    if "graph" in types or "chart" in types:
        return "graph"
    if "map" in types:
        return "map"
    if "text_source" in types or "document_excerpt" in types:
        return "text_source"
    # For History, single visual assets are historical images regardless of detected type
    return "image"


def _build_description(assets: list[dict], page_text: str) -> str:
    """Build description from assets or page text."""
    descs = [a.get("description", "") for a in assets if a.get("description")]
    if descs:
        return "; ".join(descs[:3])
    # Try first meaningful line from page text
    for line in page_text.split("\n"):
        line = line.strip()
        if len(line) > 20 and not line.startswith("Prova"):
            return line[:200]
    return f"{len(assets)} elemento(s)"



# ══════════════════════════════════════════════════════════════════
# STEP 6: Link embedded images to sources
# ══════════════════════════════════════════════════════════════════

def _link_embedded_images(assets: list[dict], sources: list[dict]):
    """Replace bbox-crop assetRefs with embedded_image assets when available.

    Embedded images are the real raster images extracted from the PDF —
    much better quality than bbox-estimated context crops for paintings,
    caricatures, photos, etc.
    """
    # Index embedded images by page
    embedded_by_page: dict[int, list[dict]] = defaultdict(list)
    for a in assets:
        if a.get("type") == "embedded_image" and a.get("crop", {}).get("url"):
            embedded_by_page[a["page"]].append(a)

    for source in sources:
        page = source.get("pageStart")
        if not page:
            continue

        page_embedded = sorted(embedded_by_page.get(page, []), key=lambda a: a["id"])
        if not page_embedded:
            continue

        # If source is image_set and embedded count matches children count, map 1:1
        if source["kind"] == "image_set" and source["children"]:
            if len(page_embedded) == len(source["children"]):
                source["assetRefs"] = [e["id"] for e in page_embedded]
                source["_embedded"] = True
        # Single image source: use the embedded image
        elif source["kind"] == "image" and len(page_embedded) >= 1:
            source["assetRefs"] = [page_embedded[0]["id"]]
            source["_embedded"] = True


# ══════════════════════════════════════════════════════════════════
# STEP 7: Generate media field on questions
# ══════════════════════════════════════════════════════════════════

def _generate_media(questions: list[dict], sources: list[dict], assets: list[dict], exam_id: str):
    """Generate a `media` list on each question with resolved final asset URLs.

    This is the single source of truth for what the frontend/importer should display.
    """
    asset_map = {a["id"]: a for a in assets}

    def _get_url(asset_id: str) -> str | None:
        a = asset_map.get(asset_id)
        if not a:
            return None
        return a.get("crop", {}).get("url") or a.get("crops", {}).get("context", {}).get("url")

    source_map = {s["sourceId"]: s for s in sources}

    for q in questions:
        media = []

        if q.get("sourceRefs"):
            for ref in q["sourceRefs"]:
                src = source_map.get(ref.get("sourceId", ""))
                if not src:
                    continue

                if ref.get("childId") and src.get("assetRefs"):
                    # Specific child — find by letter index
                    letter = (ref["childId"].split("_")[-1] or "a")
                    idx = ord(letter[0]) - ord('a') if letter.isalpha() else 0
                    if 0 <= idx < len(src["assetRefs"]):
                        url = _get_url(src["assetRefs"][idx])
                        if url:
                            media.append({"type": "image", "url": url, "sourceId": src["sourceId"], "label": f"Imagem {letter.upper()}"})
                elif src.get("assetRefs"):
                    # Full source — show all assets
                    for i, aid in enumerate(src["assetRefs"]):
                        url = _get_url(aid)
                        if url:
                            letter = chr(ord('a') + i)
                            label = src.get("label", "")
                            if len(src["assetRefs"]) > 1:
                                label = f"{label} - {letter.upper()}" if label else letter.upper()
                            media.append({"type": "image", "url": url, "sourceId": src["sourceId"], "label": label})
                elif src.get("crops", {}).get("full", {}).get("url"):
                    # Text source with full crop
                    media.append({"type": "document", "url": src["crops"]["full"]["url"], "sourceId": src["sourceId"], "label": src.get("label", "")})

        # Fallback: direct assetRefs/imageRefs
        if not media:
            for aid in (q.get("imageRefs", []) + q.get("assetRefs", [])):
                url = _get_url(aid)
                if url:
                    media.append({"type": "image", "url": url, "assetId": aid})

        if media:
            q["media"] = media
