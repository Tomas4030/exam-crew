"""Source grouping: group-scoped document/source detection and question linking.

For History (and similar document-heavy exams):
- Detects Grupo I/II/III/IV from page text
- Creates Source entities per document within each group
- Assigns composite questionIds (grupo_i_q1, grupo_ii_q1, etc.)
- Resolves "documento 1" references WITHIN the current group scope
- Handles composite documents (image sets A/B/C/D) as parent+children
"""
import re


# ── Group detection from raw page text ────────────────────────────
_GROUP_PATTERN = re.compile(
    r'(?:^|\n)\s*[Gg]rupo\s+(I{1,3}V?|IV|V?I{0,3})\b', re.MULTILINE
)

_ROMAN_TO_INT = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}

_DOC_LABEL_PATTERN = re.compile(
    r'[Dd]ocumento\s+(\d+)\s*(?:\(([^)]+)\))?', re.IGNORECASE
)

# Patterns for question items in History exams
_ITEM_PATTERN = re.compile(
    r'(?:^|\n)\s*(\d+)\.\s+', re.MULTILINE
)

# Source reference patterns (resolved within group scope)
_SOURCE_REF_PATTERNS = [
    re.compile(r'[Dd]ocumento\s+(\d+)', re.IGNORECASE),
    re.compile(r'[Dd]oc\.?\s*(\d+)', re.IGNORECASE),
]
_CHILD_REF_PATTERN = re.compile(r'[Ii]magem\s+([A-Z])', re.IGNORECASE)
_LINE_REF_PATTERN = re.compile(r'[Ll]inhas?\s+(\d+(?:\s*[-–a]\s*\d+)?)', re.IGNORECASE)


def apply_source_grouping(output: dict, subject_profile: dict) -> dict:
    """Main entry point: detect groups, sources, assign composite IDs, link refs.

    For non-source-grouping subjects, returns output unchanged.
    """
    if not subject_profile.get("has_source_grouping"):
        return output

    questions = output.get("questions", [])
    assets = output.get("assets", [])

    # Detect if this is a group-structured exam (Grupo I, II, III...)
    # by checking if questions already have group field from vision extraction
    has_explicit_groups = any(q.get("group") for q in questions)

    if not has_explicit_groups:
        # Try to detect groups from page raw text
        _detect_groups_from_text(questions, output)

    has_groups = any(q.get("group") for q in questions)
    if not has_groups:
        # Not a grouped exam — fall back to simple source page detection
        return _simple_source_grouping(output, assets, questions)

    # ── Group-scoped processing ───────────────────────────────────
    # Step 1: Assign groupId to all questions
    _assign_group_ids(questions)

    # Step 2: Generate composite questionIds
    _assign_composite_ids(questions)

    # Step 3: Detect source documents per group from assets
    sources = _detect_sources_per_group(assets, questions)

    # Step 4: Resolve question sourceRefs within group scope
    _resolve_scoped_refs(questions, sources)

    output["sources"] = sources
    return output


def _detect_groups_from_text(questions: list[dict], output: dict):
    """Detect group assignments from sourceTextRaw and page ordering."""
    # Build page→group mapping by scanning all page texts in order
    page_group = {}
    current_group = None

    # Get all unique pages from questions, sorted
    all_pages = sorted({q.get("sourcePage", 0) for q in questions})

    # Also check sourceTextRaw from questions (contains full page text)
    page_texts = {}
    for q in questions:
        page = q.get("sourcePage", 0)
        if page and q.get("sourceTextRaw"):
            page_texts[page] = q["sourceTextRaw"]

    for page in sorted(page_texts.keys()):
        text = page_texts[page]
        group_match = _GROUP_PATTERN.search(text)
        if group_match:
            current_group = f"Grupo {group_match.group(1)}"
        if current_group:
            page_group[page] = current_group

    # Assign groups to questions based on their page
    current_group = None
    for q in sorted(questions, key=lambda x: (x.get("sourcePage", 0), x.get("number", ""))):
        page = q.get("sourcePage", 0)
        if page in page_group:
            current_group = page_group[page]
        if current_group and not q.get("group"):
            q["group"] = current_group


def _assign_group_ids(questions: list[dict]):
    """Convert group labels to normalized groupIds."""
    for q in questions:
        group = q.get("group")
        if group:
            # "Grupo II" → "grupo_ii"
            q["groupId"] = group.lower().replace(" ", "_")


def _assign_composite_ids(questions: list[dict]):
    """Replace simple q1/q2 IDs with grupo_i_q1, grupo_ii_q1, etc."""
    for q in questions:
        group_id = q.get("groupId")
        number = q.get("number", "")
        if group_id and number:
            new_id = f"{group_id}_q{number.replace('.', '_')}"
            old_id = q["questionId"]
            q["questionId"] = new_id
            q["displayNumber"] = f"{q.get('group', '')}, item {number}"
            # Update parent/child references
            for other in questions:
                if other.get("parentQuestion") == old_id:
                    other["parentQuestion"] = new_id
                other["subQuestions"] = [
                    new_id if s == old_id else s for s in other.get("subQuestions", [])
                ]


def _detect_sources_per_group(assets: list[dict], questions: list[dict]) -> list[dict]:
    """Detect source documents from assets, scoped by group.

    Assets on pages without questions that fall between group boundaries
    are assigned to the group whose questions follow them.
    """
    sources = []
    pages_with_questions = {q["sourcePage"] for q in questions}

    # Build group page ranges: which pages belong to which group
    group_pages = {}  # groupId → list of question pages
    for q in questions:
        gid = q.get("groupId")
        if gid:
            group_pages.setdefault(gid, []).append(q["sourcePage"])

    # Sort groups by their first page
    sorted_groups = sorted(group_pages.items(), key=lambda x: min(x[1]))

    # For each asset on a non-question page, assign to the group whose questions come after
    source_assets = [a for a in assets if a["page"] not in pages_with_questions
                     and a.get("type") != "embedded_image"]

    for asset in source_assets:
        page = asset["page"]
        assigned_group = None
        for gid, pages in sorted_groups:
            if page < min(pages):
                # This asset page is before this group's questions
                assigned_group = gid
                break
            elif page <= max(pages):
                assigned_group = gid
                break
        if not assigned_group and sorted_groups:
            # After all groups — assign to last
            assigned_group = sorted_groups[-1][0]

        if assigned_group:
            asset["_groupId"] = assigned_group

    # Group source assets by (groupId, page) and try to detect document labels
    from collections import defaultdict
    group_page_assets = defaultdict(list)
    for a in source_assets:
        gid = a.get("_groupId")
        if gid:
            group_page_assets[(gid, a["page"])].append(a)

    # Build Source entities
    doc_counter = defaultdict(int)  # groupId → next doc number
    for (gid, page), page_assets in sorted(group_page_assets.items()):
        doc_counter[gid] += 1
        doc_num = doc_counter[gid]

        # Try to infer label from asset descriptions
        label = _infer_doc_label(page_assets, doc_num)
        kind = _infer_doc_kind(page_assets)

        source_id = f"{gid}_documento_{doc_num}"

        # Detect children (A, B, C, D sub-images)
        children = []
        if len(page_assets) > 1 and kind == "image_set":
            for i, a in enumerate(sorted(page_assets, key=lambda x: x.get("id", ""))):
                letter = chr(ord('a') + i)
                child_id = f"{source_id}_{letter}"
                children.append(child_id)
                a["parentAssetId"] = source_id

        source = {
            "sourceId": source_id,
            "groupId": gid,
            "label": label,
            "kind": kind,
            "pageStart": page,
            "pageEnd": page,
            "description": _build_source_description(page_assets),
            "children": children,
            "assetRefs": [a["id"] for a in page_assets],
        }
        sources.append(source)

    return sources


def _resolve_scoped_refs(questions: list[dict], sources: list[dict]):
    """Resolve 'documento 1', 'imagem B' references within the question's group."""
    # Index sources by (groupId, doc_number)
    source_index = {}
    for s in sources:
        gid = s["groupId"]
        num_match = re.search(r'(\d+)$', s["sourceId"])
        if num_match:
            source_index[(gid, num_match.group(1))] = s

    for q in questions:
        text = (q.get("statement") or "") + " " + (q.get("sourceTextRaw") or "")
        if not text.strip():
            continue

        gid = q.get("groupId")
        if not gid:
            continue

        source_refs = []

        # Find document references
        doc_nums = set()
        for pattern in _SOURCE_REF_PATTERNS:
            doc_nums.update(pattern.findall(text))

        # Find child references (imagem A, B, etc.)
        child_letters = [c.upper() for c in _CHILD_REF_PATTERN.findall(text)]

        for doc_num in doc_nums:
            source = source_index.get((gid, doc_num))
            if not source:
                continue

            if child_letters and source["children"]:
                # Specific child references
                for letter in child_letters:
                    child_id = f"{source['sourceId']}_{letter.lower()}"
                    if child_id in source["children"]:
                        source_refs.append({
                            "sourceId": source["sourceId"],
                            "childId": child_id,
                            "mode": "specific_child",
                        })
                # If ALL children referenced, also add full_group
                all_letters = {chr(ord('a') + i).upper() for i in range(len(source["children"]))}
                if set(child_letters) >= all_letters:
                    source_refs.insert(0, {"sourceId": source["sourceId"], "childId": None, "mode": "full_group"})
            else:
                # Full document reference
                source_refs.append({"sourceId": source["sourceId"], "childId": None, "mode": "full_group"})

        if source_refs:
            q["sourceRefs"] = source_refs


def _simple_source_grouping(output: dict, assets: list[dict], questions: list[dict]) -> dict:
    """Fallback: simple source page detection for non-grouped exams."""
    pages_with_questions = {q["sourcePage"] for q in questions}
    source_pages = {a["page"] for a in assets
                    if a["page"] not in pages_with_questions
                    and a.get("type") != "embedded_image"}

    if not source_pages:
        return output

    # Build source groups per page (legacy behavior)
    source_groups = []
    for page in sorted(source_pages):
        page_assets = [a for a in assets if a["page"] == page and a.get("type") != "embedded_image"]
        if not page_assets:
            continue
        group_id = f"source_group_p{page}"
        source_groups.append({
            "id": group_id,
            "type": "source_group",
            "sourceType": "mixed",
            "page": page,
            "label": _infer_doc_label(page_assets, 0),
            "description": _build_source_description(page_assets),
            "children": [a["id"] for a in page_assets],
            "crops": None,
        })
        for a in page_assets:
            a["parentAssetId"] = group_id

    output["sourceGroups"] = source_groups
    return output


# ── Helpers ───────────────────────────────────────────────────────

def _infer_doc_label(assets: list[dict], doc_num: int) -> str:
    """Infer document label from asset descriptions."""
    for a in assets:
        desc = a.get("description", "")
        match = _DOC_LABEL_PATTERN.search(desc)
        if match:
            label = f"Documento {match.group(1)}"
            if match.group(2):
                label += f" ({match.group(2)})"
            return label
    return f"Documento {doc_num}" if doc_num else "Documento"


def _infer_doc_kind(assets: list[dict]) -> str:
    """Infer document kind from asset types."""
    types = {a.get("type", "") for a in assets}
    if len(assets) > 1 and all(t in ("image", "historical_source", "map") for t in types):
        return "image_set"
    if "table" in types:
        return "table"
    if "graph" in types or "chart" in types:
        return "graph"
    if "map" in types:
        return "map"
    if "text_source" in types or "document_excerpt" in types:
        return "text_source"
    if len(assets) == 1:
        t = assets[0].get("type", "")
        if t in ("image", "historical_source"):
            return "image"
        return t or "mixed"
    return "mixed"


def _build_source_description(assets: list[dict]) -> str:
    """Build description from asset list."""
    descs = [a.get("description", "") for a in assets if a.get("description")]
    if descs:
        return "; ".join(descs[:3])
    return f"{len(assets)} elemento(s) documental(is)"
