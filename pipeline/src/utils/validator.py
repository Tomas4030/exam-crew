"""Post-processing validator: enforces hard rules on assembled output.

Rules:
- All question IDs unique
- All asset IDs unique
- sourcePage exists and valid
- imageRefs/tableRefs/assetRefs point to existing assets
- parentQuestion points to existing question
- No question number gaps without warning
- No status "completed" with critical errors
- mathHeavy → needsHumanReview if confidence < 0.9
- Assets without bbox → warning
- Hallucination detection for assets without text reference
"""
import re


def _looks_corrupt_math_text(text: str) -> bool:
    suspicious = ("□", "�", "\u001f", "\u001e", "^ h", "] g", " b l", "[45::47;5u")
    if any(s in text for s in suspicious):
        return True
    tokens = re.findall(r'\S+', text or "")
    if len(tokens) <= 8:
        return False
    one_char = sum(1 for t in tokens if len(t) == 1)
    return (one_char / len(tokens)) > 0.35


def validate_and_fix(output: dict, extraction: dict = None) -> dict:
    """Apply hard validation rules. Returns corrected output."""
    warnings = output.get("warnings", [])
    questions = output.get("questions", [])
    assets = output.get("assets", [])
    total_pages = output.get("metadata", {}).get("total_pages", 0)

    # ── Rule 1: Unique question IDs ──────────────────────────────
    seen_qids = {}
    for q in questions:
        qid = q["questionId"]
        if qid in seen_qids:
            # Fix: append page
            new_id = f"{qid}_p{q.get('sourcePage', 0)}"
            q["questionId"] = new_id
            # Update references
            for other in questions:
                if other.get("parentQuestion") == qid:
                    other["parentQuestion"] = new_id
                other["subQuestions"] = [new_id if s == qid else s for s in other.get("subQuestions", [])]
        seen_qids[q["questionId"]] = True

    # ── Rule 2: Unique asset IDs ─────────────────────────────────
    seen_aids = {}
    for asset in assets:
        aid = asset["id"]
        if aid in seen_aids:
            new_id = f"{aid}_{len(seen_aids)}"
            # Update references in questions
            for q in questions:
                q["imageRefs"] = [new_id if r == aid else r for r in q.get("imageRefs", [])]
                q["tableRefs"] = [new_id if r == aid else r for r in q.get("tableRefs", [])]
                q["assetRefs"] = [new_id if r == aid else r for r in q.get("assetRefs", [])]
            asset["id"] = new_id
        seen_aids[asset["id"]] = True

    # ── Rule 3: Valid sourcePage ──────────────────────────────────
    for q in questions:
        raw_page = q.get("sourcePage")
        page = raw_page if isinstance(raw_page, int) else 0
        if page < 1 or (total_pages > 0 and page > total_pages):
            warnings.append({"type": "invalid_page", "message": f"Q{q['number']} has invalid sourcePage={raw_page}", "questionId": q["questionId"]})
        if q.get("region"):
            region = q.get("region", {})
            bbox = region.get("bbox") or []
            if region.get("page") != page or len(bbox) != 4:
                warnings.append({"type": "invalid_region", "message": f"Q{q['number']} has invalid region metadata", "questionId": q["questionId"]})

    # ── Rule 4: Asset references exist ───────────────────────────
    asset_ids = {a["id"] for a in assets}
    # Also accept sourceGroup IDs and source IDs as valid references
    for sg in output.get("sourceGroups", []):
        asset_ids.add(sg.get("id", ""))
    for src in output.get("sources", []):
        asset_ids.add(src.get("sourceId", ""))
    for q in questions:
        for ref_list_name in ("imageRefs", "tableRefs", "assetRefs"):
            for ref in q.get(ref_list_name, []):
                if ref not in asset_ids:
                    warnings.append({"type": "broken_ref", "message": f"Q{q['number']} references '{ref}' but asset not found", "questionId": q["questionId"], "assetId": ref})

    # ── Rule 5: parentQuestion exists ────────────────────────────
    all_qids = {q["questionId"] for q in questions}
    for q in questions:
        parent = q.get("parentQuestion")
        if parent and parent not in all_qids:
            warnings.append({"type": "broken_parent", "message": f"Q{q['number']} references parent '{parent}' which doesn't exist", "questionId": q["questionId"]})

    # ── Rule 6: Question number gaps ─────────────────────────────
    # If questions have group/section fields, skip gap detection (History-style exams
    # have repeated numbering across groups: Grupo I Q1-5, Grupo II Q1-3, etc.)
    has_groups = any(q.get("group") or q.get("groupId") for q in questions)
    main_numbers = sorted(set(
        int(q["number"]) for q in questions
        if q["number"].isdigit() and (
            not q.get("parentQuestion") or q.get("isGroup")
        )
    ))
    if not has_groups and main_numbers:
        # Always start from 1 — if Q1 is missing, detect it
        expected = list(range(1, main_numbers[-1] + 1))
        missing = [n for n in expected if n not in main_numbers]
        for m in missing:
            prev_q = max((n for n in main_numbers if n < m), default=None)
            next_q = min((n for n in main_numbers if n > m), default=None)
            if m == 1:
                msg = f"⚠️ CRITICAL: Question 1 not found — first question in exam missing"
            elif prev_q and next_q:
                msg = f"⚠️ CRITICAL: Question {m} missing between Q{prev_q} and Q{next_q} — extraction gap"
            else:
                msg = f"⚠️ CRITICAL: Question {m} not found in output — extraction failed"
            warnings.append({"type": "missing_question", "severity": "critical", "message": msg})

    # ── Rule 6b: Cross-check with PDF text for missing questions ──
    if extraction and not has_groups:
        numbers_in_pdf = set()
        for page in extraction.get("pages", []):
            text = page.get("text", "")
            for m in re.finditer(r'(?m)^\s*(\d{1,2})\.\s+\S', text):
                n = int(m.group(1))
                if 1 <= n <= 30:
                    numbers_in_pdf.add(n)
        numbers_in_json = {int(q["number"]) for q in questions if q["number"].isdigit()}
        pdf_missing = numbers_in_pdf - numbers_in_json
        for m in sorted(pdf_missing):
            warnings.append({
                "type": "missing_question",
                "severity": "critical",
                "message": f"⚠️ CRITICAL: Question {m} found in PDF text but not extracted"
            })

    # ── Rule 7: mathHeavy → needsHumanReview ─────────────────────
    for q in questions:
        if q.get("mathHeavy") and q.get("confidence", 1.0) < 0.9:
            q["needsHumanReview"] = True

    # ── Rule 8: Assets without bbox → warning ────────────────────
    no_bbox = [a for a in assets if not a.get("bbox") and not a.get("bbox_estimate")
               and a.get("type") not in ("table", "text_source", "document_excerpt", "formula_block", "embedded_image")]
    estimated_only = [a for a in assets if not a.get("bbox") and a.get("bbox_estimate")
                      and a.get("type") not in ("table", "text_source", "document_excerpt", "formula_block", "embedded_image")]
    if no_bbox:
        warnings.append({"type": "missing_bbox", "message": f"{len(no_bbox)} visual assets have no bounding box — crop unavailable"})
    if estimated_only:
        warnings.append({"type": "estimated_bbox_only", "message": f"{len(estimated_only)} assets have estimated bbox only — crop may need verification"})

    # ── Rule 9: Hallucination detection ──────────────────────────
    # Build set of assets that belong to source groups (not hallucinations)
    source_group_children = set()
    for sg in output.get("sourceGroups", []):
        source_group_children.update(sg.get("children", []))
        source_group_children.add(sg.get("id", ""))
    # Also include assets referenced by Source entities
    for src in output.get("sources", []):
        source_group_children.update(src.get("assetRefs", []))
    # Also detect assets with parentAssetId
    for asset in assets:
        if asset.get("parentAssetId"):
            source_group_children.add(asset["id"])

    for asset in assets:
        if asset.get("type") in ("embedded_image",):
            continue  # Real images from PDF are never hallucinated
        # Skip assets that are part of source groups
        if asset["id"] in source_group_children:
            continue
        # Check if any question references this asset
        aid = asset["id"]
        referenced = any(
            aid in q.get("imageRefs", []) + q.get("tableRefs", []) + q.get("assetRefs", [])
            for q in questions
        )
        if not referenced:
            # Check if any child of this asset is referenced (parent tables shouldn't be hallucination)
            child_referenced = any(
                any(ref.startswith(aid + "_") for ref in q.get("imageRefs", []) + q.get("tableRefs", []) + q.get("assetRefs", []))
                for q in questions
            )
            # Check linkedQuestions
            if not asset.get("linkedQuestions") and not child_referenced:
                # Check if it's on a source page (page with no questions)
                pages_with_questions = {q["sourcePage"] for q in questions}
                if asset.get("page") not in pages_with_questions:
                    # Source material on a document page — not hallucination
                    warnings.append({"type": "source_asset_pending_reference", "message": f"Asset '{aid}' (page {asset.get('page')}) is on a source page — pending question linkage", "assetId": aid})
                else:
                    asset["hallucination_risk"] = True
                    warnings.append({"type": "possible_hallucination", "message": f"Asset '{aid}' (page {asset.get('page')}) not referenced by any question", "assetId": aid})

    # ── Rule 10: Merge assetRefs from imageRefs + tableRefs ──────
    for q in questions:
        all_refs = set(q.get("imageRefs", []) + q.get("tableRefs", []) + q.get("assetRefs", []))
        q["assetRefs"] = sorted(all_refs)
        q["visualDependency"] = len(all_refs) > 0
        # Recalculate hasDiagram from actual asset types
        q_asset_types = [a.get("type") for a in assets if a["id"] in all_refs]
        if any(t == "geometry_diagram" for t in q_asset_types):
            q["hasDiagram"] = True
        if any(t == "graph" for t in q_asset_types):
            q["hasGraph"] = True

    # ── Rule 10b: Missing table data ─────────────────────────────
    for q in questions:
        if q.get("hasTable") or q.get("tableRefs"):
            for table_id in q.get("tableRefs", []):
                table_asset = next((a for a in assets if a["id"] == table_id), None)
                # Embedded images used as table visuals don't have rows — skip them
                if table_asset and table_asset.get("type") == "embedded_image":
                    continue
                if not table_asset or not table_asset.get("rows"):
                    q["needsHumanReview"] = True
                    q.setdefault("warnings", []).append({
                        "type": "missing_table_data",
                        "message": f"Q{q['number']} references {table_id}, but table data was not extracted"
                    })
                    warnings.append({
                        "type": "missing_table_data",
                        "questionId": q["questionId"],
                        "message": f"Q{q['number']} references {table_id} — table rows not extracted"
                    })

    # ── Rule 10cc: Corrupt math text in multiple choice ──────────
    for q in questions:
        if q.get("type") != "multiple_choice" or not q.get("mathHeavy"):
            continue
        stmt = q.get("statement", "") or ""
        if _looks_corrupt_math_text(stmt):
            q["needsHumanReview"] = True
            q.setdefault("warnings", []).append({
                "type": "corrupt_math_text",
                "message": "Math-heavy multiple choice has corrupted extracted text; requires vision repair."
            })
            warnings.append({
                "type": "corrupt_math_text",
                "questionId": q["questionId"],
                "message": f"Q{q['number']} math text appears corrupted"
            })

    # ── Rule 10c: Wrong asset reference (figure on wrong question) ──
    for q in questions:
        text = (q.get("statement") or "") + " " + (q.get("rawText") or "")
        mentioned_figs = set(re.findall(r'[Ff]igura\s+(\d+)', text))
        if not mentioned_figs:
            continue
        for asset_id in list(q.get("assetRefs", [])):
            fig_match = re.match(r'figura_(\d+)', asset_id)
            if not fig_match:
                continue
            if fig_match.group(1) not in mentioned_figs:
                warnings.append({
                    "type": "wrong_asset_reference",
                    "questionId": q["questionId"],
                    "assetId": asset_id,
                    "message": f"Q{q['number']} mentions Figura {', '.join(mentioned_figs)} but references {asset_id}"
                })

    # ── Rule 10d: Suspicious points for open questions ──────────
    for q in questions:
        pts = q.get("points")
        if pts and pts < 8 and q.get("type") not in ("multiple_choice", "group"):
            q.setdefault("warnings", []).append({
                "type": "suspicious_points",
                "message": f"Q{q['number']} is {q.get('type', 'open')} but has only {pts} points — verify scoring"
            })
            warnings.append({
                "type": "suspicious_points",
                "questionId": q["questionId"],
                "message": f"Q{q['number']} ({q.get('type', 'open')}) has unusually low points: {pts}"
            })

    # ── Rule 10e: Visual questions must have crop ─────────────────
    asset_map = {a["id"]: a for a in assets}
    for q in questions:
        refs = q.get("imageRefs", []) + q.get("tableRefs", [])
        for ref in refs:
            asset = asset_map.get(ref)
            if not asset:
                continue
            crop = asset.get("crop", {})
            if crop.get("status") != "success":
                q["needsHumanReview"] = True
                q.setdefault("warnings", []).append({
                    "type": "missing_asset_crop",
                    "severity": "high",
                    "message": f"Q{q['number']} references {ref} but no crop image exists"
                })

    # ── Rule 10f: Remove false table assets (no data, no references) ──
    referenced_ids = set()
    for q in questions:
        referenced_ids.update(q.get("imageRefs", []))
        referenced_ids.update(q.get("tableRefs", []))
        referenced_ids.update(q.get("assetRefs", []))
    assets[:] = [a for a in assets if not (
        a.get("id", "").startswith("tabela_")
        and not a.get("rows")
        and not a.get("columns")
        and a["id"] not in referenced_ids
    )]

    # ── Rule 11: Fix stats ───────────────────────────────────────
    groups = [q for q in questions if q.get("isGroup")]
    non_group = [q for q in questions if not q.get("isGroup")]
    main_qs = [q for q in non_group if not q.get("parentQuestion")]
    sub_qs = [q for q in non_group if q.get("parentQuestion")]

    output["metadata"]["stats"] = {
        "mainQuestions": len(main_qs) + len(groups),
        "answerableItems": len(non_group),
        "jsonNodes": len(questions),
        "groups": len(groups),
        "subQuestions": len(sub_qs),
    }

    # ── Rule 12: Determine processingStatus ──────────────────────
    has_missing_pages = len(output.get("missingPages", [])) > 0
    has_missing_questions = any(w["type"] == "missing_question" for w in warnings)
    has_hallucinations = any(a.get("hallucination_risk") for a in assets)
    has_broken_refs = any(w["type"] in ("broken_ref", "broken_parent") for w in warnings)
    has_wrong_refs = any(w["type"] == "wrong_asset_reference" for w in warnings)
    has_missing_table = any(w["type"] == "missing_table_data" for w in warnings)
    has_math_review = any(q.get("mathHeavy") and q.get("needsHumanReview") for q in questions)
    has_text_quality_issue = any(
        q.get("textQuality", {}).get("status") in ("needs_review", "corrupt") and q.get("textQuality", {}).get("requiresMathReview")
        for q in questions
    )
    any_review = any(q.get("needsHumanReview") for q in questions)

    # Check: real main questions (digit numbers, no parent) with points:null
    real_main_qs = [q for q in questions if q["number"].isdigit() and not q.get("parentQuestion")]
    missing_points_qs = [q for q in real_main_qs if q.get("points") is None and not q.get("isGroup")]
    has_missing_points = len(missing_points_qs) > 0
    if has_missing_points:
        warnings.append({
            "type": "missing_points_critical",
            "severity": "high",
            "message": f"{len(missing_points_qs)} main question(s) have no points assigned: {', '.join('Q' + q['number'] for q in missing_points_qs)}"
        })

    # Check: mainQuestions count mismatch (expected = max question number)
    # Skip for grouped exams where numbering resets per group
    if main_numbers and not has_groups:
        expected_count = main_numbers[-1]  # e.g. if max is 15, expect 15 main questions
        actual_count = len(main_numbers)
        if actual_count != expected_count:
            warnings.append({
                "type": "question_count_mismatch",
                "severity": "high",
                "message": f"Expected {expected_count} main questions (1-{expected_count}), found {actual_count}"
            })

    # Strict: only "completed" if ALL checks pass
    all_figures_correct = not has_wrong_refs
    no_critical_warnings = not any(w.get("severity") == "critical" for w in warnings)
    no_high_warnings = not any(w.get("severity") == "high" for w in warnings)

    if has_missing_pages:
        output["processingStatus"] = "partial_failed"
    elif has_missing_questions or not no_critical_warnings:
        output["processingStatus"] = "needs_review"
    elif has_missing_points or not no_high_warnings:
        output["processingStatus"] = "needs_review"
    elif has_hallucinations or has_broken_refs or has_wrong_refs or has_missing_table:
        output["processingStatus"] = "needs_review"
    elif has_text_quality_issue:
        output["processingStatus"] = "needs_review"
    elif has_math_review or any_review:
        output["processingStatus"] = "completed_with_warnings"
    elif no_bbox or estimated_only:
        output["processingStatus"] = "completed_with_warnings"
    else:
        output["processingStatus"] = "completed"

    # needsHumanReview: true only for statuses that genuinely need human intervention
    if output["processingStatus"] in ("partial_failed", "needs_review"):
        output["needsHumanReview"] = True
    elif output["processingStatus"] == "completed_with_warnings":
        # Only flag for review if there are high/critical severity warnings
        has_severe = any(w.get("severity") in ("critical", "high") for w in warnings)
        output["needsHumanReview"] = has_severe
    else:
        output["needsHumanReview"] = False

    output["warnings"] = warnings

    return output
