"""Normalizer: deterministic post-assembly corrections.

Runs BEFORE validator. Fixes things that can be computed from the data itself
without calling the LLM again:
- Reassociate figures by "Figura X" mentions in statements
- Normalize bbox_estimate → bbox
- Propagate calculatorAllowed from parent to children
- Default bbox for tables
- Fix hasDiagram/hasGraph from actual asset types
"""
import re


def normalize(output: dict) -> dict:
    """Apply deterministic corrections. Returns corrected output."""
    questions = output.get("questions", [])
    assets = output.get("assets", [])

    # ── 0. Remove fake questions with Roman numeral numbers ──────
    # These are propositions (I, II, III, IV) inside another question, not real questions
    _remove_roman_numeral_questions(questions)

    # ── 1. Reassociate figures by statement mentions ─────────────
    _repair_figure_associations(questions, assets)

    # ── 1b. Resolve source group references in questions ─────────
    _resolve_source_refs(questions, output.get("sourceGroups", []))

    # ── 2. Normalize bbox_estimate → bbox ────────────────────────
    for asset in assets:
        if asset.get("bbox_estimate") and not asset.get("bbox"):
            asset["bbox"] = asset["bbox_estimate"]
            asset["bboxSource"] = "estimated"

    # ── 3. Default bbox for tables without any bbox ──────────────
    for asset in assets:
        if asset.get("type") == "table" and not asset.get("bbox") and not asset.get("bbox_estimate"):
            asset["bbox"] = {"x_pct": 5, "y_pct": 20, "w_pct": 90, "h_pct": 30}
            asset["bboxSource"] = "default"

    # ── 4. Propagate calculatorAllowed parent → children ─────────
    parent_map = {q["questionId"]: q for q in questions if q.get("isGroup")}
    for q in questions:
        pid = q.get("parentQuestion")
        if pid and pid in parent_map:
            parent = parent_map[pid]
            # If parent says no calculator, children inherit
            if parent.get("calculatorAllowed") == False:
                q["calculatorAllowed"] = False
            # If child statement says no calculator, propagate up
            stmt = str(q.get("statement", ""))
            if "sem recorrer à calculadora" in stmt.lower() or "sem calculadora" in stmt.lower():
                q["calculatorAllowed"] = False
                parent["calculatorAllowed"] = False

    # ── 5. Recalculate hasDiagram/hasGraph from assetRefs ────────
    asset_map = {a["id"]: a for a in assets}
    for q in questions:
        all_refs = set(q.get("imageRefs", []) + q.get("tableRefs", []) + q.get("assetRefs", []))
        ref_types = [asset_map[r].get("type") for r in all_refs if r in asset_map]
        if any(t == "geometry_diagram" for t in ref_types):
            q["hasDiagram"] = True
        if any(t == "graph" for t in ref_types):
            q["hasGraph"] = True
        if all_refs:
            q["visualDependency"] = True

    return output


def _repair_figure_associations(questions: list[dict], assets: list[dict]):
    """Reassociate figures based on 'Figura X' mentions in question statements.

    Logic:
    - For each question, find which figures it mentions (Figura 1, Figura 2, etc.)
    - For each asset that is a figure, find which questions mention it
    - Fix nearQuestion on the asset
    - Fix imageRefs on questions (remove wrong, add correct)
    """
    # Build figure mention map: question → set of figure numbers mentioned
    q_mentions: dict[str, set[str]] = {}
    for q in questions:
        text = (q.get("statement") or "") + " " + (q.get("rawText") or "")
        fig_nums = set(re.findall(r'[Ff]igura\s+(\d+)', text))
        if fig_nums:
            q_mentions[q["questionId"]] = fig_nums

    # Build asset lookup: figure_number → asset(s)
    fig_assets: dict[str, list[dict]] = {}
    for asset in assets:
        match = re.match(r'figura_(\d+)', asset["id"])
        if match:
            fig_assets.setdefault(match.group(1), []).append(asset)

    # For each figure asset, find the correct question(s) that mention it
    for fig_num, asset_list in fig_assets.items():
        # Find questions that mention this figure
        mentioning_qs = [qid for qid, mentions in q_mentions.items() if fig_num in mentions]

        for asset in asset_list:
            aid = asset["id"]

            # Fix nearQuestion on asset
            if mentioning_qs:
                # Use the question number (not ID) of the first mentioning question
                for q in questions:
                    if q["questionId"] in mentioning_qs:
                        asset["nearQuestion"] = q["number"]
                        break

            # Remove this asset from questions that DON'T mention it
            for q in questions:
                if q["questionId"] in mentioning_qs:
                    continue
                # Remove from imageRefs if wrongly assigned
                if aid in q.get("imageRefs", []):
                    q["imageRefs"].remove(aid)
                if aid in q.get("assetRefs", []):
                    q["assetRefs"].remove(aid)

            # Add to questions that DO mention it
            for q in questions:
                if q["questionId"] not in mentioning_qs:
                    continue
                if aid not in q.get("imageRefs", []):
                    q["imageRefs"].append(aid)
                if aid not in q.get("assetRefs", []):
                    q["assetRefs"].append(aid)
                q["visualDependency"] = True



_ROMAN_NUMERALS = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}


def _remove_roman_numeral_questions(questions: list[dict]):
    """Remove questions whose number is a Roman numeral (I, II, III...).

    These are propositions inside multi_blank_choice questions (e.g. Q13),
    not real standalone questions. Remove them from the list in-place.
    """
    to_remove = []
    for i, q in enumerate(questions):
        num = q.get("number", "").strip()
        if num.upper() in _ROMAN_NUMERALS and not q.get("parentQuestion"):
            to_remove.append(i)

    # Remove in reverse order to preserve indices
    for i in reversed(to_remove):
        questions.pop(i)


def _resolve_source_refs(questions: list[dict], source_groups: list[dict]):
    """Resolve remaining textual references (documento X, imagem B) to sourceRefs.

    This complements source_grouping.py — catches any references that the
    source_grouping step might have missed (e.g. questions added during retry).
    """
    if not source_groups:
        return

    # Build lookup
    group_by_doc_num: dict[str, dict] = {}
    for sg in source_groups:
        num_match = re.search(r'(\d+)', sg.get("label", ""))
        if num_match:
            group_by_doc_num[num_match.group(1)] = sg

    for q in questions:
        # Skip if already has sourceRefs
        if q.get("sourceRefs"):
            continue

        text = (q.get("statement") or "") + " " + (q.get("rawText") or "")
        if not text.strip():
            continue

        # Check for document references
        doc_nums = re.findall(r'[Dd]ocumento\s+(\d+)', text)
        doc_nums += re.findall(r'[Dd]oc\.?\s*(\d+)', text)

        source_refs = []
        for doc_num in set(doc_nums):
            sg = group_by_doc_num.get(doc_num)
            if not sg:
                continue

            # Check for specific child references
            child_letters = re.findall(r'[Ii]magem\s+([A-Z])', text, re.IGNORECASE)
            child_letters += re.findall(r'[Ff]igura\s+([A-Z])', text, re.IGNORECASE)
            child_letters = list(set(c.upper() for c in child_letters))

            if child_letters:
                for letter in child_letters:
                    child_id = _find_child_in_group(sg, letter)
                    if child_id:
                        source_refs.append({"sourceId": sg["id"], "childId": child_id, "mode": "specific_child"})
                        if child_id not in q.get("assetRefs", []):
                            q.setdefault("assetRefs", []).append(child_id)
            else:
                source_refs.append({"sourceId": sg["id"], "childId": None, "mode": "full_group"})

            if sg["id"] not in q.get("assetRefs", []):
                q.setdefault("assetRefs", []).append(sg["id"])

        if source_refs:
            q["sourceRefs"] = source_refs


def _find_child_in_group(source_group: dict, letter: str) -> str | None:
    """Find a child ID by letter in a source group."""
    letter_lower = letter.lower()
    for child_id in source_group.get("children", []):
        if f"_{letter_lower}_" in child_id or child_id.endswith(f"_{letter_lower}"):
            return child_id
    return None
