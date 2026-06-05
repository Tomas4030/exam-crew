"""Portuguese exam normalizer.

Keep this module subject-specific. Do not put Historia rules here.
"""
from __future__ import annotations

import re
from typing import Any


def normalize_portugues(output: dict, extraction: dict | None = None) -> dict:
    """Apply deterministic repairs for Portuguese national exams."""
    _split_embedded_grupo_iii(output)
    _repair_grupo_iii_composition(output, extraction)
    _strip_embedded_group_iii_from_other_questions(output)
    _normalize_group_metadata(output)
    _remove_legacy_duplicate_questions(output)
    _collapse_multiple_grupo_iii_questions(output)
    _repair_composition_question(output)
    _strip_inline_options_from_selection_statements(output)
    _repair_multi_blank_structure(output, extraction)
    _repair_missing_choice_options(output, extraction)
    _attach_visual_assets_to_composition(output)
    _recover_missing_questions_from_scoring(output, extraction)
    _repair_points_from_scoring_text(output, extraction)
    _sort_questions(output)
    _refresh_stats(output)
    return output


def _split_embedded_grupo_iii(output: dict) -> None:
    questions = output.get("questions") or []
    if any(q.get("groupId") == "grupo_iii" for q in questions):
        return

    for q in list(questions):
        text = _question_all_text(q)
        match = re.search(r"\bGRUPO\s+III\b", text, re.IGNORECASE)
        if not match:
            continue

        composition = _extract_grupo_iii_statement(text[match.start():])
        if not composition:
            continue

        for key in _TEXT_KEYS:
            value = q.get(key)
            if isinstance(value, str):
                q[key] = _strip_after_grupo_iii(value)

        q.setdefault("warnings", []).append({
            "type": "portuguese_embedded_group_iii_split",
            "message": "Removed embedded Grupo III text from this question.",
        })

        new_question = {
            "questionId": "grupo_iii_q1",
            "number": "1",
            "type": "open_answer",
            "sourcePage": q.get("sourcePage"),
            "statement": composition,
            "sourceTextRaw": composition,
            "rawText": composition,
            "blanks": None,
            "options": [],
            "maxSelections": None,
            "imageRefs": [],
            "tableRefs": [],
            "assetRefs": [],
            "visualDependency": False,
            "confidence": 0.9,
            "needsHumanReview": False,
            "warnings": [],
            "parentQuestion": None,
            "subQuestions": [],
            "mathHeavy": False,
            "hasGraph": False,
            "hasDiagram": False,
            "hasTable": False,
            "calculatorAllowed": None,
            "points": None,
            "isMandatory": True,
            "region": q.get("region"),
            "groupId": "grupo_iii",
            "group": "Grupo III",
            "displayNumber": "Grupo III, item 1",
            "sourceRefs": [],
            "media": [],
            "statementPlain": composition,
            "statementLatex": composition,
            "statementRaw": composition,
            "statementFormatted": composition,
            "statementPlainFormatted": composition,
            "statementLatexFormatted": composition,
        }
        questions.append(new_question)
        output.setdefault("warnings", []).append({
            "type": "portuguese_group_iii_recovered",
            "message": "Recovered Grupo III composition prompt from embedded text.",
        })
        return


def _strip_embedded_group_iii_from_other_questions(output: dict) -> None:
    repaired = 0
    for q in output.get("questions") or []:
        if q.get("groupId") == "grupo_iii":
            continue
        changed = False
        for key in _TEXT_KEYS:
            value = q.get(key)
            if isinstance(value, str) and re.search(r"\bGRUPO\s+III\b", value, re.IGNORECASE):
                q[key] = _strip_after_grupo_iii(value)
                changed = True
        if changed:
            repaired += 1
            q.setdefault("warnings", []).append({
                "type": "portuguese_embedded_group_iii_removed",
                "message": "Removed Grupo III text embedded in another question.",
            })
    if repaired:
        output.setdefault("warnings", []).append({
            "type": "portuguese_embedded_group_iii_removed",
            "message": f"Removed embedded Grupo III text from {repaired} question(s).",
        })


def _repair_grupo_iii_composition(output: dict, extraction: dict | None) -> None:
    questions = output.get("questions") or []
    extracted = _extract_grupo_iii_from_pages(extraction)

    composition_questions = [q for q in questions if _is_composition_prompt(_question_all_text(q))]
    observation_questions = [q for q in questions if q.get("groupId") == "grupo_iii" and _is_observation_artifact(q)]

    if extracted:
        target = next((q for q in questions if q.get("groupId") == "grupo_iii" and not _is_observation_artifact(q)), None)
        if target is None:
            target = next((q for q in composition_questions if q not in observation_questions), None)
        if target is None:
            target = _new_grupo_iii_question(extracted, source_page=_find_grupo_iii_page(extraction))
            questions.append(target)

        _set_question_text(target, extracted)
        target["questionId"] = "grupo_iii_q1"
        target["number"] = "1"
        target["type"] = "open_answer"
        target["groupId"] = "grupo_iii"
        target["group"] = "Grupo III"
        target["displayNumber"] = "Grupo III, item 1"
        target["options"] = []
        target["blanks"] = None
        target["maxSelections"] = None
        target["sourceRefs"] = []
        target["media"] = []
        target["points"] = target.get("points") or None

        removed = 0
        clean = []
        for q in questions:
            if q is target:
                clean.append(q)
                continue
            if q in observation_questions or _is_composition_prompt(_question_all_text(q)):
                removed += 1
                continue
            clean.append(q)
        output["questions"] = clean
        if removed:
            output.setdefault("warnings", []).append({
                "type": "portuguese_group_iii_duplicates_removed",
                "message": f"Removed {removed} duplicate/observation Grupo III candidate(s).",
            })
        return

    if observation_questions:
        output["questions"] = [q for q in questions if q not in observation_questions]
        output.setdefault("warnings", []).append({
            "type": "portuguese_group_iii_observations_removed",
            "message": f"Removed {len(observation_questions)} Grupo III observation artifact(s).",
        })


def _new_grupo_iii_question(statement: str, source_page: int | None = None) -> dict:
    return {
        "questionId": "grupo_iii_q1",
        "number": "1",
        "type": "open_answer",
        "sourcePage": source_page,
        "statement": statement,
        "sourceTextRaw": statement,
        "rawText": statement,
        "blanks": None,
        "options": [],
        "maxSelections": None,
        "imageRefs": [],
        "tableRefs": [],
        "assetRefs": [],
        "visualDependency": False,
        "confidence": 0.9,
        "needsHumanReview": False,
        "warnings": [],
        "parentQuestion": None,
        "subQuestions": [],
        "mathHeavy": False,
        "hasGraph": False,
        "hasDiagram": False,
        "hasTable": False,
        "calculatorAllowed": None,
        "points": None,
        "isMandatory": True,
        "groupId": "grupo_iii",
        "group": "Grupo III",
        "displayNumber": "Grupo III, item 1",
        "sourceRefs": [],
        "media": [],
        "statementPlain": statement,
        "statementLatex": statement,
        "statementRaw": statement,
        "statementFormatted": statement,
        "statementPlainFormatted": statement,
        "statementLatexFormatted": statement,
    }


def _normalize_group_metadata(output: dict) -> None:
    for q in output.get("questions") or []:
        qid = str(q.get("questionId") or "")
        if qid.startswith("grupo_i_"):
            q["groupId"] = "grupo_i"
            q["group"] = "Grupo I"
        elif qid.startswith("grupo_ii_"):
            q["groupId"] = "grupo_ii"
            q["group"] = "Grupo II"
        elif qid.startswith("grupo_iii_"):
            q["groupId"] = "grupo_iii"
            q["group"] = "Grupo III"
        elif re.match(r"^q[12]_\d+$", qid):
            q["groupId"] = "grupo_ii"
            q["group"] = "Grupo II"

        if q.get("groupId") and q.get("number"):
            roman = {"grupo_i": "I", "grupo_ii": "II", "grupo_iii": "III"}.get(q["groupId"], "")
            if roman:
                q["displayNumber"] = f"Grupo {roman}, item {q['number']}"


def _remove_legacy_duplicate_questions(output: dict) -> None:
    questions = output.get("questions") or []
    clean = []
    seen = set()
    removed = 0
    for q in questions:
        qid = str(q.get("questionId") or "")
        text = _normalized_text(_question_prompt_text(q))
        if _is_scoring_artifact_text(text):
            removed += 1
            continue
        if _is_observation_artifact(q):
            removed += 1
            continue
        if q.get("groupId") == "grupo_ii" and re.search(r"\bresponda\s+(?:aos?|de forma)", text):
            removed += 1
            continue
        key = (q.get("groupId"), q.get("number"), text[:180])
        if text and key in seen:
            removed += 1
            continue
        seen.add(key)
        clean.append(q)
    if removed:
        output["questions"] = clean
        output.setdefault("warnings", []).append({
            "type": "portuguese_legacy_duplicates_removed",
            "message": f"Removed {removed} duplicate/container question(s).",
        })


def _collapse_multiple_grupo_iii_questions(output: dict) -> None:
    questions = output.get("questions") or []
    grupo_iii = [q for q in questions if q.get("groupId") == "grupo_iii"]
    if len(grupo_iii) <= 1:
        return

    def score(q: dict) -> tuple[int, int]:
        text = _question_prompt_text(q)
        return (
            2 if _is_composition_prompt(text) else 0,
            len(text),
        )

    keeper = max(grupo_iii, key=score)
    removed = 0
    clean = []
    for q in questions:
        if q.get("groupId") == "grupo_iii" and q is not keeper:
            removed += 1
            continue
        clean.append(q)

    keeper["questionId"] = "grupo_iii_q1"
    keeper["number"] = "1"
    keeper["groupId"] = "grupo_iii"
    keeper["group"] = "Grupo III"
    keeper["displayNumber"] = "Grupo III, item 1"
    output["questions"] = clean
    if removed:
        output.setdefault("warnings", []).append({
            "type": "portuguese_multiple_compositions_collapsed",
            "message": f"Kept the best Grupo III composition and removed {removed} duplicate candidate(s).",
        })


def _repair_composition_question(output: dict) -> None:
    for q in output.get("questions") or []:
        text = _question_all_text(q).lower()
        if q.get("groupId") == "grupo_iii" or "texto de opinião" in text or "texto de opiniao" in text:
            q["type"] = "open_answer"
            q["options"] = []
            q["blanks"] = None
            q["maxSelections"] = None
            q.setdefault("disciplineData", {})["answerMode"] = "composition"
            q.setdefault("disciplineData", {})["minWords"] = _extract_min_words(text)


def _strip_inline_options_from_selection_statements(output: dict) -> None:
    repaired = 0
    for q in output.get("questions") or []:
        qtype = q.get("type")
        if qtype not in {"multiple_choice", "multi_select"}:
            continue
        options = q.get("options") or []
        if not options:
            continue
        text = _question_prompt_text(q)
        stripped = _strip_letter_option_lines(text)
        if stripped and stripped != text:
            _set_question_text(q, stripped)
            repaired += 1

        if qtype == "multi_select":
            wanted = _infer_max_selections(stripped)
            if wanted:
                q["maxSelections"] = wanted
    if repaired:
        output.setdefault("warnings", []).append({
            "type": "portuguese_inline_options_stripped",
            "message": f"Removed duplicated inline options from {repaired} selection question(s).",
        })


def _attach_visual_assets_to_composition(output: dict) -> None:
    assets = output.get("assets") or []
    visual_assets = [asset for asset in assets if _asset_visual_path(asset)]
    if not visual_assets:
        return

    attached = 0
    for q in output.get("questions") or []:
        if q.get("groupId") != "grupo_iii":
            continue
        text = _normalized_text(_question_prompt_text(q))
        if not re.search(r"\b(cartoon|imagem|figura|ilustra[cç][aã]o|refloresta)", text):
            continue
        asset = _best_visual_asset_for_question(q, visual_assets)
        rel = _asset_visual_path(asset)
        if not rel:
            continue
        url = _asset_visual_url(asset) or f"/api/exams/{output.get('exam_id')}/assets/{rel.removeprefix('assets/')}"
        q.setdefault("assetRefs", [])
        if asset.get("id") not in q["assetRefs"]:
            q["assetRefs"].append(asset.get("id"))
        q["visualDependency"] = True
        q["media"] = [{
            "type": "image",
            "url": url,
            "relativePath": rel,
            "assetId": asset.get("id"),
            "label": asset.get("label") or "Imagem",
        }]
        attached += 1

    if attached:
        output.setdefault("warnings", []).append({
            "type": "portuguese_composition_visual_attached",
            "message": f"Attached visual asset to {attached} Portuguese composition question(s).",
        })


def _repair_missing_choice_options(output: dict, extraction: dict | None = None) -> None:
    repaired = 0
    for q in output.get("questions") or []:
        if q.get("type") not in {"multiple_choice", "multi_select"}:
            continue
        if q.get("options"):
            continue
        text = _question_prompt_text(q)
        options = _extract_letter_options(text)
        if len(options) < 3:
            block = _extract_question_block_from_pages(q.get("number"), extraction, require_options=True)
            options = _extract_letter_options(block)
            if len(options) >= 3:
                _set_question_text(q, block)
        if len(options) >= 3:
            q["options"] = options
            repaired += 1
    if repaired:
        output.setdefault("warnings", []).append({
            "type": "portuguese_choice_options_repaired",
            "message": f"Extracted options for {repaired} choice question(s).",
        })


def _repair_multi_blank_structure(output: dict, extraction: dict | None = None) -> None:
    repaired = 0
    for q in output.get("questions") or []:
        if q.get("type") != "multi_blank_choice":
            continue

        blanks = q.get("blanks") if isinstance(q.get("blanks"), list) else []
        if _valid_multi_blank_blanks(blanks):
            q["blanks"] = _normalize_multi_blank_blanks(blanks)
            q["options"] = []
            q["maxSelections"] = len(q["blanks"])
            continue

        text = _question_prompt_text(q)
        parsed = _parse_multi_blank_options(text)
        if not _valid_multi_blank_blanks(parsed):
            block = _extract_question_block_from_pages(q.get("number"), extraction, require_options=False)
            parsed = _parse_multi_blank_options(block)
            if _valid_multi_blank_blanks(parsed):
                _set_question_text(q, _strip_multi_blank_option_table(block))

        if _valid_multi_blank_blanks(parsed):
            q["blanks"] = _normalize_multi_blank_blanks(parsed)
            q["options"] = []
            q["maxSelections"] = len(q["blanks"])
            if text:
                stripped = _strip_multi_blank_option_table(text)
                if stripped and stripped != text:
                    _set_question_text(q, stripped)
            repaired += 1

    if repaired:
        output.setdefault("warnings", []).append({
            "type": "portuguese_multiblank_repaired",
            "message": f"Rebuilt blanks/options for {repaired} multi_blank_choice question(s).",
        })


def _recover_missing_questions_from_scoring(output: dict, extraction: dict | None) -> None:
    if not extraction:
        return
    entries = _parse_portuguese_scoring(extraction)
    if not entries:
        return

    questions = output.setdefault("questions", [])
    existing = {(q.get("groupId") or "", str(q.get("number") or "")) for q in questions}
    recovered = 0

    for entry in entries:
        gid = entry["group"]
        number = str(entry["number"])
        if (gid, number) in existing:
            continue

        block = ""
        if gid == "grupo_i" and number == "5":
            block = _extract_group_i_b_block(extraction)
        if not block:
            block = _extract_question_block_from_pages(number, extraction, require_options=False)
        if not block or len(block) < 20:
            continue

        options = _extract_letter_options(block)
        qtype = "multiple_choice" if len(options) >= 3 else "open_answer"
        roman = {"grupo_i": "I", "grupo_ii": "II", "grupo_iii": "III"}.get(gid, "")
        question = {
            "questionId": f"{gid}_q{number.replace('.', '_')}_recovered",
            "number": number,
            "type": qtype,
            "sourcePage": None,
            "statement": block,
            "statementPlain": block,
            "statementLatex": block,
            "statementRaw": block,
            "statementFormatted": block,
            "statementPlainFormatted": block,
            "statementLatexFormatted": block,
            "sourceTextRaw": block,
            "rawText": block,
            "options": options,
            "blanks": None,
            "maxSelections": None,
            "imageRefs": [],
            "tableRefs": [],
            "assetRefs": [],
            "sourceRefs": [],
            "media": [],
            "visualDependency": False,
            "confidence": 0.78,
            "needsHumanReview": False,
            "warnings": [{"type": "portuguese_recovered_from_pdf_text", "message": "Recovered missing question from extracted PDF text."}],
            "points": entry["points"],
            "isMandatory": True,
            "groupId": gid,
            "group": f"Grupo {roman}",
            "displayNumber": f"Grupo {roman}, item {number}",
        }
        questions.append(question)
        existing.add((gid, number))
        recovered += 1

    if recovered:
        output.setdefault("warnings", []).append({
            "type": "portuguese_missing_questions_recovered",
            "message": f"Recovered {recovered} missing question(s) from scoring/text.",
        })


def _repair_points_from_scoring_text(output: dict, extraction: dict | None) -> None:
    entries = _parse_portuguese_scoring(extraction)
    if not entries:
        return

    _store_portuguese_scoring_policy(output, entries)
    by_key = {(entry["group"], str(entry["number"])): entry["points"] for entry in entries}
    applied = 0
    for q in output.get("questions") or []:
        key = (q.get("groupId") or "", str(q.get("number") or ""))
        entry = next((item for item in entries if (item["group"], str(item["number"])) == key), None)
        points = by_key.get(key)
        if points is None:
            continue
        if q.get("points") != points:
            q["points"] = points
            applied += 1
        if entry:
            q["isMandatory"] = bool(entry.get("isMandatory", True))
            if entry.get("optionalPoolId"):
                q.setdefault("disciplineData", {})["optionalPoolId"] = entry["optionalPoolId"]

    if applied:
        output.setdefault("warnings", []).append({
            "type": "portuguese_points_repaired",
            "message": f"Applied Portuguese scoring table to {applied} question(s).",
        })


def _store_portuguese_scoring_policy(output: dict, entries: list[dict[str, Any]]) -> None:
    if not entries:
        return

    items = []
    for entry in entries:
        group = str(entry.get("group") or "")
        number = str(entry.get("number") or "")
        points = entry.get("points")
        if not group or not number or points is None:
            continue
        item = {
            "groupId": group,
            "number": number,
            "points": points,
            "isMandatory": bool(entry.get("isMandatory", True)),
        }
        if entry.get("optionalPoolId"):
            item["optionalPoolId"] = entry["optionalPoolId"]
        items.append(item)

    if not items:
        return

    mandatory_points = sum(int(item["points"]) for item in items if item.get("isMandatory"))
    optional_items = [item for item in items if not item.get("isMandatory")]
    optional_points = sum(int(item["points"]) for item in optional_items)
    optional_each = _common_point_value(optional_items)
    choose = _infer_optional_choose(optional_items, mandatory_points)
    output.setdefault("metadata", {})["scoringPolicy"] = {
        "source": "cotacoes",
        "totalPoints": 200,
        "rawSubtotal": mandatory_points + optional_points,
        "mandatorySubtotal": mandatory_points,
        "optionalPoolSubtotal": optional_points,
        "optionalPool": {
            "choose": choose,
            "from": len(optional_items),
            "pointsEach": optional_each,
        } if optional_items else None,
        "items": items,
    }


def _common_point_value(items: list[dict[str, Any]]) -> int | None:
    values = []
    for item in items:
        try:
            values.append(int(item.get("points")))
        except (TypeError, ValueError):
            return None
    if not values:
        return None
    first = values[0]
    return first if all(value == first for value in values) else None


def _infer_optional_choose(optional_items: list[dict[str, Any]], mandatory_points: int) -> int | None:
    points_each = _common_point_value(optional_items)
    if not optional_items or not points_each:
        return None
    remaining = 200 - mandatory_points
    if remaining <= 0 or remaining % points_each:
        return None
    choose = remaining // points_each
    if 0 < choose <= len(optional_items):
        return choose
    return None


def _parse_portuguese_scoring(extraction: dict | None) -> list[dict[str, Any]]:
    if not extraction:
        return []
    pages = extraction.get("_processed_pages") or extraction.get("pages") or []
    scoring_pages = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_text = str(page.get("text") or "")
        page_upper = page_text.upper()
        if _has_scoring_heading(page_text) and "TOTAL" in page_upper:
            scoring_pages.append(page_text)
    scoring_text = scoring_pages[0] if scoring_pages else ""
    if not scoring_text:
        scoring_text = "\n".join(
            str(page.get("text") or "")
            for page in pages[-4:]
            if isinstance(page, dict) and _looks_like_scoring_text(str(page.get("text") or ""))
        )
    if not scoring_text:
        scoring_text = "\n".join(str(page.get("text") or "") for page in pages[-2:] if isinstance(page, dict))

    text = re.sub(r"[ \t]+", " ", scoring_text.replace("\x07", " "))
    if not _looks_like_scoring_text(text):
        return []

    modern = _parse_modern_portuguese_scoring(text)
    if modern:
        return modern

    textual_modern = _parse_textual_modern_portuguese_scoring(text)
    if textual_modern:
        return textual_modern

    grid = _parse_grid_portuguese_scoring(text)
    if grid:
        return grid

    legacy = _parse_legacy_portuguese_scoring(text)
    if legacy:
        return legacy

    entries: list[dict[str, Any]] = []
    group_aliases = (
        ("grupo_i", r"Grupo\s+I"),
        ("grupo_ii", r"Grupo\s+II"),
        ("grupo_iii", r"Grupo\s+III"),
    )
    for idx, (gid, pattern) in enumerate(group_aliases):
        start = re.search(pattern, text, re.IGNORECASE)
        if not start:
            continue
        next_start = None
        for _, next_pattern in group_aliases[idx + 1:]:
            m = re.search(next_pattern, text[start.end():], re.IGNORECASE)
            if m:
                next_start = start.end() + m.start()
                break
        block = text[start.end():next_start]
        entries.extend(_parse_group_scoring_block(gid, block))
    return entries


def _parse_modern_portuguese_scoring(text: str) -> list[dict[str, Any]]:
    low = text.lower()
    if "contribu" not in low or "classifica" not in low or "final" not in low:
        return []

    scoring_text = text
    heading_index = _find_scoring_heading_index(text)
    if heading_index >= 0:
        scoring_text = text[heading_index:]

    split = re.split(r"(?im)^\s*Destes\b", scoring_text, maxsplit=1)
    before_optional = split[0]
    optional_block = split[1] if len(split) > 1 else ""
    entries = _parse_modern_mandatory_scoring(before_optional)
    entries.extend(_parse_modern_optional_scoring(optional_block))
    return _dedupe_entries(entries)


def _parse_grid_portuguese_scoring(text: str) -> list[dict[str, Any]]:
    lines = _scoring_lines(text)
    if "Item" not in lines or not any("Cotação" in line or "Cotacao" in line for line in lines):
        return []

    entries: list[dict[str, Any]] = []
    roman_indexes = [(idx, line) for idx, line in enumerate(lines) if line in {"I", "II", "III"}]
    if len(roman_indexes) < 2:
        return []

    for pos, (idx, roman) in enumerate(roman_indexes):
        next_idx = roman_indexes[pos + 1][0] if pos + 1 < len(roman_indexes) else len(lines)
        block = lines[idx + 1:next_idx]
        gid = _roman_to_group(roman)
        if gid == "grupo_iii":
            point = _last_points_before_total(block)
            if point:
                entries.append({"group": gid, "number": "1", "points": point})
            continue

        range_match = re.search(r"(?is)(\d{1,2})\.\s*a\s*(\d{1,2})\..*?(\d+)\s*[x×]\s*(\d+)\s*pontos", "\n".join(block))
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            points_each = int(range_match.group(4))
            if 0 < points_each <= 100 and start <= end:
                for number in range(start, end + 1):
                    entries.append({"group": gid, "number": str(number), "points": points_each, "isMandatory": True})
                continue

        item_numbers: list[str] = []
        point_values: list[int] = []
        seen_points = False
        for line in block:
            if re.match(r"^\d{1,3}$", line):
                seen_points = True
                value = int(line)
                if 0 < value <= 100:
                    point_values.append(value)
                continue
            if not seen_points and (m := re.match(r"^(\d{1,2})\.$", line)):
                item_numbers.append(m.group(1))

        if item_numbers and point_values:
            for number, point in zip(item_numbers, point_values[:len(item_numbers)]):
                entries.append({"group": gid, "number": number, "points": point, "isMandatory": True})

    return _dedupe_entries(entries)


def _parse_legacy_portuguese_scoring(text: str) -> list[dict[str, Any]]:
    if not re.search(r"GRUPO\s+I", text, re.IGNORECASE):
        return []

    entries: list[dict[str, Any]] = []
    group_blocks = {
        "grupo_i": _extract_scoring_group_block(text, "I"),
        "grupo_ii": _extract_scoring_group_block(text, "II"),
        "grupo_iii": _extract_scoring_group_block(text, "III"),
    }

    for match in re.finditer(r"(?im)^\s*(\d{1,2})\.\s*.*?\n\s*(\d{1,3})\s+pontos?\b", group_blocks["grupo_i"]):
        point = int(match.group(2))
        if 0 < point <= 100:
            entries.append({"group": "grupo_i", "number": match.group(1), "points": point, "isMandatory": True})

    b_match = re.search(r"(?im)^\s*B\s*[\.\s]+.*?\n\s*(\d{1,3})\s+pontos?\b", group_blocks["grupo_i"])
    if b_match:
        point = int(b_match.group(1))
        if 0 < point <= 100:
            entries.append({"group": "grupo_i", "number": "5", "points": point, "isMandatory": True})

    for match in re.finditer(r"(?im)^\s*(\d)\.(\d)\.\s*.*?\n\s*(\d{1,3})\s+pontos?\b", group_blocks["grupo_ii"]):
        point = int(match.group(3))
        if 0 < point <= 100:
            entries.append({"group": "grupo_ii", "number": f"{match.group(1)}.{match.group(2)}", "points": point, "isMandatory": True})

    point = _last_points_before_total(_scoring_lines(group_blocks["grupo_iii"]))
    if point:
        entries.append({"group": "grupo_iii", "number": "1", "points": point, "isMandatory": True})

    return _dedupe_entries(entries)


def _parse_modern_mandatory_scoring(block: str) -> list[dict[str, Any]]:
    lines = _scoring_lines(block)
    group_tokens = [line.lower() for line in lines if line in {"I", "II", "III"}]
    if not group_tokens:
        return []

    item_numbers = [int(m.group(1)) for line in lines if (m := re.match(r"^(\d{1,2})\.$", line))]
    points = [int(line) for line in lines if re.match(r"^\d{1,3}$", line)]
    points = _drop_subtotal(points)

    if not item_numbers or not points:
        return []

    runs = _split_item_runs(item_numbers)
    entries: list[dict[str, Any]] = []
    group_ids = [_roman_to_group(token) for token in group_tokens]

    point_index = 0
    for gid, run in zip(group_ids, runs):
        for item in run:
            if point_index >= len(points):
                break
            entries.append({"group": gid, "number": str(item), "points": points[point_index], "isMandatory": True})
            point_index += 1

    # Modern Portuguese tables often omit item "1." under Grupo III because it is
    # the single composition item; the remaining point value belongs to it.
    if "grupo_iii" in group_ids and not any(e["group"] == "grupo_iii" for e in entries):
        if point_index < len(points):
            entries.append({"group": "grupo_iii", "number": "1", "points": points[point_index], "isMandatory": True})

    return entries


def _parse_modern_optional_scoring(block: str) -> list[dict[str, Any]]:
    if not block:
        return []
    match = re.search(r"(\d+)\s*[x×]\s*(\d+)\s*pontos", block, re.IGNORECASE)
    if not match:
        return []
    points_each = int(match.group(2))
    lines = _scoring_lines(block)
    group_tokens = [line.lower() for line in lines if line in {"I", "II", "III"}]
    item_numbers = [int(m.group(1)) for line in lines if (m := re.match(r"^(\d{1,2})\.$", line))]
    runs = _split_item_runs(item_numbers)
    entries: list[dict[str, Any]] = []
    for gid, run in zip([_roman_to_group(token) for token in group_tokens], runs):
        for item in run:
            entries.append({
                "group": gid,
                "number": str(item),
                "points": points_each,
                "isMandatory": False,
                "optionalPoolId": "portuguese_optional_pool_1",
            })
    return entries


def _parse_textual_modern_portuguese_scoring(text: str) -> list[dict[str, Any]]:
    if not re.search(r"Grupo\s+I", text, re.IGNORECASE) or "Item" not in text:
        return []

    heading_index = _find_scoring_heading_index(text)
    scoring_text = text[heading_index:] if heading_index >= 0 else text
    split = re.split(r"(?is)\bDos\s+restantes\b", scoring_text, maxsplit=1)
    mandatory = split[0]
    optional = split[1] if len(split) > 1 else ""

    entries: list[dict[str, Any]] = []
    for gid, roman in (("grupo_i", "I"), ("grupo_ii", "II")):
        block = _extract_scoring_group_block(mandatory, roman)
        for match in re.finditer(r"(?is)Item\s+(\d{1,2})\.?.*?(\d{1,3})\s+pontos?\b", block):
            point = int(match.group(2))
            if 0 < point <= 100:
                entries.append({"group": gid, "number": match.group(1), "points": point, "isMandatory": True})

    group_iii = _extract_scoring_group_block(mandatory, "III")
    item_unique = re.search(r"(?is)Item\s+(?:único|unico).*?(\d{1,3})\s+pontos?\b", group_iii)
    if item_unique:
        point = int(item_unique.group(1))
        if 0 < point <= 100:
            entries.append({"group": "grupo_iii", "number": "1", "points": point, "isMandatory": True})

    opt_match = re.search(r"(\d+)\s*[x×]\s*(\d+)\s*pontos", optional, re.IGNORECASE)
    if opt_match:
        points_each = int(opt_match.group(2))
        for gid, roman in (("grupo_i", "I"), ("grupo_ii", "II")):
            block_match = re.search(rf"(?is)Grupo\s+{roman}\s+Itens?\s+(.+?)(?=Grupo\s+(?:I|II|III)|SUBTOTAL|TOTAL|$)", optional)
            if not block_match:
                continue
            for raw in re.findall(r"\b(\d{1,2})\.", block_match.group(1)):
                entries.append({
                    "group": gid,
                    "number": raw,
                    "points": points_each,
                    "isMandatory": False,
                    "optionalPoolId": "portuguese_optional_pool_1",
                })

    return _dedupe_entries(entries)


def _scoring_lines(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line).strip().rstrip()
        for line in (text or "").splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]


def _split_item_runs(items: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    current: list[int] = []
    previous = 0
    for item in items:
        if current and item <= previous:
            runs.append(current)
            current = []
        current.append(item)
        previous = item
    if current:
        runs.append(current)
    return runs


def _drop_subtotal(points: list[int]) -> list[int]:
    clean = list(points)
    while len(clean) > 1 and clean[-1] == sum(clean[:-1]):
        clean.pop()
    return clean


def _extract_scoring_group_block(text: str, roman: str) -> str:
    pattern = rf"GRUPO\s+{roman}\b"
    start = re.search(pattern, text, re.IGNORECASE)
    if not start:
        return ""
    next_match = re.search(r"\bGRUPO\s+(?:I|II|III)\b", text[start.end():], re.IGNORECASE)
    end = start.end() + next_match.start() if next_match else len(text)
    return text[start.end():end]


def _last_points_before_total(lines: list[str]) -> int | None:
    usable: list[int] = []
    for line in lines:
        if re.search(r"\bTOTAL\b", line, re.IGNORECASE):
            break
        for raw in re.findall(r"\b(\d{1,3})\s+pontos?\b", line, re.IGNORECASE):
            value = int(raw)
            if 0 < value <= 100:
                usable.append(value)
        if re.match(r"^\d{1,3}$", line):
            value = int(line)
            if 0 < value <= 100:
                usable.append(value)
    return usable[-1] if usable else None


def _roman_to_group(token: str) -> str:
    return {"i": "grupo_i", "ii": "grupo_ii", "iii": "grupo_iii"}.get(token.lower(), "")


def _parse_group_scoring_block(group_id: str, block: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    if group_id == "grupo_iii":
        item_unique = re.search(r"(?is)item\s+(?:Ãºnico|unico).*?(\d{1,3})\s*pontos?\b", block)
        if item_unique:
            point = int(item_unique.group(1))
            if 0 < point <= 100:
                return [{"group": group_id, "number": "1", "points": point, "isMandatory": True}]

    # Common line format: "1. 13 pontos" / "1 13" / "Item 1 13 pontos".
    for match in re.finditer(
        r"(?im)(?:^|\n)\s*(?:item\s*)?(\d{1,2})[.\s]+(?:[^\n]*?\s)?(\d{1,3})\s*pontos?\b",
        block,
    ):
        item = match.group(1)
        points = int(match.group(2))
        if 0 < points <= 100:
            entries.append({"group": group_id, "number": item, "points": points, "isMandatory": True})

    if entries:
        return _dedupe_entries(entries)

    # Fallback for compact tables where item numbers and points appear as columns.
    numbers = [int(n) for n in re.findall(r"\b(?:item\s*)?(\d{1,2})\b", block, re.IGNORECASE)]
    block_without_total = re.split(r"\bTOTAL\b", block, maxsplit=1, flags=re.IGNORECASE)[0]
    points = [int(p) for p in re.findall(r"\b(\d{1,3})\s*pontos?\b", block_without_total, re.IGNORECASE)]
    if group_id == "grupo_iii" and not points:
        points = [int(p) for p in re.findall(r"\b(\d{2,3})\b", block_without_total)]

    if group_id == "grupo_iii" and points:
        usable = [point for point in points if 0 < point <= 100]
        if usable:
            return [{"group": group_id, "number": "1", "points": usable[-1], "isMandatory": True}]

    usable_items = [n for n in numbers if 1 <= n <= 20]
    for item, point in zip(usable_items, points):
        if 0 < point <= 100:
            entries.append({"group": group_id, "number": str(item), "points": point, "isMandatory": True})
    return _dedupe_entries(entries)


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    clean = []
    for entry in entries:
        key = (entry["group"], entry["number"])
        if key in seen:
            continue
        seen.add(key)
        clean.append(entry)
    return clean


def _sort_questions(output: dict) -> None:
    order = {"grupo_i": 1, "grupo_ii": 2, "grupo_iii": 3}
    output["questions"] = sorted(
        output.get("questions") or [],
        key=lambda q: (
            order.get(q.get("groupId") or "", 99),
            int(str(q.get("number") or "999").split(".", 1)[0]) if str(q.get("number") or "").split(".", 1)[0].isdigit() else 999,
            q.get("sourcePage") or 999,
        ),
    )


def _refresh_stats(output: dict) -> None:
    questions = output.get("questions") or []
    stats = output.setdefault("metadata", {}).setdefault("stats", {})
    if isinstance(stats, dict):
        stats["mainQuestions"] = len(questions)
        stats["answerableItems"] = len(questions)
        stats["jsonNodes"] = len(questions)


def _extract_grupo_iii_statement(text: str) -> str:
    text = re.sub(r"(?is)^.*?\bGRUPO\s+III\b", "", text, count=1).strip()
    text = re.sub(r"(?is)\bFIM\b.*$", "", text).strip()
    text = re.sub(r"(?is)\bCOTAÇÕES\b.*$", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_grupo_iii_from_pages(extraction: dict | None) -> str:
    if not extraction:
        return ""
    pages = extraction.get("_processed_pages") or extraction.get("pages") or []
    for page in pages:
        if not isinstance(page, dict):
            continue
        text = str(page.get("text") or "")
        if re.search(r"\bGRUPO\s+III\b", text, re.IGNORECASE):
            statement = _extract_grupo_iii_statement(text)
            statement = re.sub(r"(?is)\bObserva[cç][oõ]es\s*:.*$", "", statement).strip()
            if _is_composition_prompt(statement):
                return statement
    return ""


def _find_grupo_iii_page(extraction: dict | None) -> int | None:
    if not extraction:
        return None
    pages = extraction.get("_processed_pages") or extraction.get("pages") or []
    for page in pages:
        if isinstance(page, dict) and re.search(r"\bGRUPO\s+III\b", str(page.get("text") or ""), re.IGNORECASE):
            try:
                return int(page.get("page") or 0) or None
            except (TypeError, ValueError):
                return None
    return None


def _strip_after_grupo_iii(text: str) -> str:
    return re.sub(r"(?is)\bGRUPO\s+III\b.*$", "", text).strip()


def _question_all_text(q: dict) -> str:
    return "\n".join(str(q.get(key) or "") for key in _TEXT_KEYS).replace("\x07", " ")


def _question_prompt_text(q: dict) -> str:
    keys = (
        "statement",
        "statementPlain",
        "statementLatex",
        "statementRaw",
        "statementFormatted",
        "statementPlainFormatted",
        "statementLatexFormatted",
        "rawText",
    )
    return "\n".join(str(q.get(key) or "") for key in keys).replace("\x07", " ")


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _extract_letter_options(text: str) -> list[dict[str, str]]:
    matches = list(re.finditer(r"(?s)(?:^|\s)\(([A-Da-d])\)\s*", text or ""))
    if len(matches) < 3:
        return []

    options: list[dict[str, str]] = []
    for idx, match in enumerate(matches):
        letter = match.group(1).upper()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        value = re.sub(r"\s+", " ", text[start:end]).strip()
        value = re.sub(r"\s*(?:GRUPO\s+[IVX]+|COTAÇÕES|FIM)\b.*$", "", value, flags=re.IGNORECASE).strip()
        if value:
            options.append({"letter": letter, "text": value})
    return options


def _strip_letter_option_lines(text: str) -> str:
    if not text:
        return ""
    pattern = re.compile(r"(?s)(?:^|\s)(?:[A-Ea-e]\.|\([A-Ea-e]\))\s+")
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return text

    first = matches[0]
    last = matches[-1]
    tail_start = len(text)
    tail_patterns = (
        r"\bIdentifique\b",
        r"\bSelecione\b",
        r"\bEscreva\b",
        r"\bIndique\b",
    )
    for marker in tail_patterns:
        marker_match = re.search(marker, text[last.end():], re.IGNORECASE)
        if marker_match:
            tail_start = last.end() + marker_match.start()
            break

    prefix = text[:first.start()].strip()
    suffix = text[tail_start:].strip() if tail_start < len(text) else ""
    cleaned = "\n".join(part for part in (prefix, suffix) if part)
    return re.sub(r"[ \t]+\n", "\n", cleaned).strip()


def _parse_multi_blank_options(text: str) -> list[dict[str, Any]]:
    if not text:
        return []

    clean = text.replace("\x07", " ")
    blanks = _blank_ids_from_text(clean)
    if len(blanks) < 2:
        return []

    column_options = _parse_multi_blank_columns(clean, blanks)
    if _valid_multi_blank_blanks(column_options):
        return column_options

    section_options = _parse_multi_blank_sections(clean, blanks)
    if _valid_multi_blank_blanks(section_options):
        return section_options

    return []


def _blank_ids_from_text(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"(?<!\w)([a-z])\)", text or "", re.IGNORECASE):
        blank = match.group(1).lower()
        if blank not in found:
            found.append(blank)
    return found[:4]


def _parse_multi_blank_columns(text: str, blanks: list[str]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = {blank: [] for blank in blanks[:3]}
    lines = [line.rstrip() for line in (text or "").splitlines()]

    for line in lines:
        matches = list(re.finditer(r"(?<!\d)([1-5])[.)]\s+(.+?)(?=(?:\s{2,}|\t+)[1-5][.)]\s+|$)", line))
        if len(matches) < 2:
            continue
        for index, match in enumerate(matches[:len(groups)]):
            blank = blanks[index]
            value = _clean_multi_blank_option_text(match.group(2))
            if value:
                groups[blank].append({"letter": match.group(1), "text": value})

    return [
        {"number": f"{blank})", "options": _dedupe_options(options)}
        for blank, options in groups.items()
    ]


def _parse_multi_blank_sections(text: str, blanks: list[str]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = {blank: [] for blank in blanks}
    header_matches = list(re.finditer(r"(?im)^\s*([a-z])\)\s*$", text or ""))
    if len(header_matches) < 2:
        return []

    for index, match in enumerate(header_matches):
        blank = match.group(1).lower()
        if blank not in groups:
            continue
        start = match.end()
        end = header_matches[index + 1].start() if index + 1 < len(header_matches) else len(text)
        section = text[start:end]
        for option_match in re.finditer(r"(?im)^\s*([1-5])[.)]\s+(.+?)\s*$", section):
            value = _clean_multi_blank_option_text(option_match.group(2))
            if value:
                groups[blank].append({"letter": option_match.group(1), "text": value})

    return [
        {"number": f"{blank})", "options": _dedupe_options(options)}
        for blank, options in groups.items()
    ]


def _strip_multi_blank_option_table(text: str) -> str:
    if not text:
        return ""
    lines = text.replace("\x07", " ").splitlines()
    cut_index = None
    for index, line in enumerate(lines):
        header_count = len(re.findall(r"(?<!\w)[a-z]\)", line, re.IGNORECASE))
        numbered_count = len(re.findall(r"(?<!\d)[1-5][.)]\s+", line))
        if numbered_count >= 2:
            cut_index = index
            break
        if header_count >= 2:
            rest = "\n".join(lines[index + 1:index + 6])
            if (
                re.fullmatch(r"\s*(?:[a-z]\)\s*){2,}", line, re.IGNORECASE)
                or len(re.findall(r"(?m)^\s*[1-5][.)]\s+", rest)) >= 2
                or len(re.findall(r"(?<!\d)[1-5][.)]\s+", rest)) >= 2
            ):
                cut_index = index
                break
        if re.match(r"^\s*[a-z]\)\s*$", line, re.IGNORECASE):
            rest = "\n".join(lines[index + 1:index + 5])
            if len(re.findall(r"(?m)^\s*[1-5][.)]\s+", rest)) >= 2:
                cut_index = index
                break
    if cut_index is None:
        return text.strip()
    return "\n".join(lines[:cut_index]).strip()


def _clean_multi_blank_option_text(text: str) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    value = re.sub(r"\s*(?:GRUPO\s+[IVX]+|COTA\w+|FIM)\b.*$", "", value, flags=re.IGNORECASE).strip()
    return value.rstrip(" .")


def _valid_multi_blank_blanks(blanks: Any) -> bool:
    if not isinstance(blanks, list) or len(blanks) < 2:
        return False
    for blank in blanks:
        if not isinstance(blank, dict):
            return False
        options = blank.get("options")
        if not isinstance(options, list) or len(options) < 2:
            return False
    return True


def _normalize_multi_blank_blanks(blanks: list[dict]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, blank in enumerate(blanks):
        raw_number = str(blank.get("number") or blank.get("id") or blank.get("label") or "").strip()
        if not raw_number:
            raw_number = f"{chr(ord('a') + index)})"
        raw_number = raw_number.rstrip(".")
        if re.fullmatch(r"[a-zA-Z]", raw_number):
            raw_number = f"{raw_number.lower()})"
        options = []
        for option in blank.get("options") or []:
            if not isinstance(option, dict):
                continue
            letter = str(option.get("letter") or option.get("value") or "").strip()
            text = _clean_multi_blank_option_text(str(option.get("text") or option.get("label") or ""))
            if letter and text:
                options.append({"letter": letter, "text": text})
        normalized.append({"number": raw_number, "options": _dedupe_options(options)})
    return normalized


def _dedupe_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    clean: list[dict[str, str]] = []
    seen = set()
    for option in options:
        key = (str(option.get("letter") or ""), _normalized_text(str(option.get("text") or "")))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        clean.append({"letter": key[0], "text": str(option.get("text") or "").strip()})
    return clean


def _infer_max_selections(text: str) -> int | None:
    low = (text or "").lower()
    words = {
        "duas": 2,
        "dois": 2,
        "três": 3,
        "tres": 3,
        "quatro": 4,
    }
    for word, value in words.items():
        if re.search(rf"\b{word}\b", low):
            return value
    match = re.search(r"\b([2-4])\s+(?:afirmações|opções|letras)", low)
    return int(match.group(1)) if match else None


def _asset_visual_path(asset: dict) -> str:
    if asset.get("type") == "embedded_image":
        rel = asset.get("relativePath")
        if isinstance(rel, str) and rel.startswith("assets/"):
            return rel
    crops = asset.get("crops") or {}
    for key in ("best", "visual", "context"):
        crop = crops.get(key) or {}
        rel = crop.get("relativePath")
        if isinstance(rel, str) and rel.startswith("assets/"):
            return rel
    crop = asset.get("crop") or {}
    rel = crop.get("relativePath") if isinstance(crop, dict) else None
    if isinstance(rel, str) and rel.startswith("assets/"):
        return rel
    rel = asset.get("relativePath")
    return rel if isinstance(rel, str) and rel.startswith("assets/") else ""


def _asset_visual_url(asset: dict) -> str:
    if asset.get("type") == "embedded_image":
        url = asset.get("url")
        if isinstance(url, str):
            return url
    crops = asset.get("crops") or {}
    for key in ("best", "visual", "context"):
        crop = crops.get(key) or {}
        url = crop.get("url")
        if isinstance(url, str):
            return url
    crop = asset.get("crop") or {}
    url = crop.get("url") if isinstance(crop, dict) else None
    if isinstance(url, str):
        return url
    url = asset.get("url")
    return url if isinstance(url, str) else ""


def _best_visual_asset_for_question(q: dict, assets: list[dict]) -> dict:
    page = q.get("sourcePage")
    same_page = [asset for asset in assets if asset.get("page") == page]
    candidates = same_page or assets
    text = _normalized_text(_question_prompt_text(q))
    if "cartoon" in text:
        embedded = [asset for asset in candidates if asset.get("type") == "embedded_image"]
        if embedded:
            return embedded[0]
        cartoon = [asset for asset in candidates if "cartoon" in _normalized_text(str(asset.get("description") or asset.get("label") or ""))]
        if cartoon:
            return cartoon[0]
    return candidates[0]


def _extract_question_block_from_pages(number: Any, extraction: dict | None, require_options: bool = False) -> str:
    if number is None or not extraction:
        return ""
    raw_number = str(number).strip()
    if not raw_number:
        return ""
    pages = extraction.get("_processed_pages") or extraction.get("pages") or []
    escaped = re.escape(raw_number)
    first_part = raw_number.split(".", 1)[0]
    try:
        next_number = str(int(first_part) + 1)
    except ValueError:
        next_number = ""

    start_pattern = rf"(?m)^\s*{escaped}\.\s+"
    if raw_number.endswith(".0"):
        start_pattern = rf"(?m)^\s*{re.escape(first_part)}\.\s+"

    for page in pages:
        if not isinstance(page, dict):
            continue
        text = str(page.get("text") or "").replace("\x07", " ")
        start = re.search(start_pattern, text)
        if not start:
            continue
        tail = text[start.start():]
        end_match = re.search(
            rf"(?m)^\s*(?:{re.escape(next_number)}\.|GRUPO\s+[IVX]+|COTA\w+|FIM)\b",
            tail[start.end() - start.start():],
            re.IGNORECASE,
        )
        end = (start.end() - start.start()) + end_match.start() if end_match else len(tail)
        block = tail[:end].strip()
        if not require_options or _extract_letter_options(block):
            return block
    return ""


def _extract_group_i_b_block(extraction: dict | None) -> str:
    if not extraction:
        return ""
    pages = extraction.get("_processed_pages") or extraction.get("pages") or []
    for page in pages:
        if not isinstance(page, dict):
            continue
        text = str(page.get("text") or "").replace("\x07", " ")
        if not re.search(r"\bGRUPO\s+I\b", text, re.IGNORECASE) and "\nB\n" not in text:
            continue
        match = re.search(r"(?ims)^\s*B\s*$\s*(.+?)(?=^\s*(?:Observa\w*|GRUPO\s+II|COTA\w*|FIM)\b)", text)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return ""


def _set_question_text(q: dict, text: str) -> None:
    for key in (
        "statement",
        "statementPlain",
        "statementLatex",
        "statementRaw",
        "statementFormatted",
        "statementPlainFormatted",
        "statementLatexFormatted",
        "rawText",
    ):
        q[key] = text
    q["sourceTextRaw"] = text


def _is_composition_prompt(text: str) -> bool:
    low = (text or "").lower()
    return (
        "num texto" in low
        and ("duzent" in low or "200" in low)
        and (
            "defenda uma perspetiva" in low
            or "defenda uma perspectiva" in low
            or "apresente uma reflexão" in low
            or "apresente uma reflexao" in low
            or "desenvolva uma reflexão" in low
            or "desenvolva uma reflexao" in low
            or "apreciação crítica" in low
            or "apreciacao critica" in low
            or "texto de opinião" in low
            or "texto de opiniao" in low
        )
    )


def _is_observation_artifact(q: dict) -> bool:
    text = _question_prompt_text(q).lower().strip()
    return (
        text.startswith("1. para efeitos de contagem")
        or text.startswith("2. relativamente ao desvio")
        or ("extensão inferior a oitenta palavras" in text and "num texto" not in text)
        or ("extensao inferior a oitenta palavras" in text and "num texto" not in text)
    )


def _looks_like_scoring_text(text: str) -> bool:
    low = (text or "").lower()
    return ("cotação" in low or "cotacoes" in low or "cotações" in low or "pontos" in low) and "grupo" in low


def _has_scoring_heading(text: str) -> bool:
    return any(line.strip().upper().startswith("COTA") for line in (text or "").splitlines())


def _find_scoring_heading_index(text: str) -> int:
    offset = 0
    for line in (text or "").splitlines(keepends=True):
        clean = line.strip().upper()
        if clean.startswith("COTA") and "PONTOS" not in clean and len(clean) <= 20:
            return offset + line.index(line.lstrip())
        offset += len(line)
    return -1


def _is_scoring_artifact_text(text: str) -> bool:
    if not text:
        return False
    return bool(re.fullmatch(r"(?:\d{1,2}\.?\s*\.{5,}\s*\d{1,3}\s+pontos?\s*)+", text))


def _extract_min_words(text: str) -> int | None:
    match = re.search(r"mínimo\s+de\s+(\w+|\d+)", text, re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    words = {"cem": 100, "cento": 100, "duzentas": 200, "duzentos": 200, "trezentas": 300, "trezentos": 300}
    return words.get(raw.lower())


_TEXT_KEYS = (
    "statement",
    "statementPlain",
    "statementLatex",
    "statementRaw",
    "statementFormatted",
    "statementPlainFormatted",
    "statementLatexFormatted",
    "rawText",
    "sourceTextRaw",
)
