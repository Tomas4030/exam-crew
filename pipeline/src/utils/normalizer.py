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
