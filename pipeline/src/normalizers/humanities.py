"""Humanities normalizer: rules for Português, História, Filosofia, Geografia.

Runs AFTER crop_assets and source_grouping, so sources/assets/crops already exist.
This normalizer:
1. Ensures image_set sources have virtual children A/B/C/D.
2. Generates full source crops for Grupo I from rendered pages.
3. Generates childCrops for "conjunto documental" sources.
4. Parses mixed refs like "imagem A do documento 1 e documentos 2 e 3".
5. Rebuilds media[] from scratch (removes stale entries like page12_img3.png).
"""
import re
from pathlib import Path

from PIL import Image

from ..config import OUTPUT_DIR
from ..utils.doc_refs import doc_nums_from_source_refs, resolve_doc_numbers
from ..utils.multiblank import repair_multiblank_question_from_page


# ── Regex patterns ────────────────────────────────────────────────
# "imagem A do documento 1"
_CHILD_OF_DOC_RE = re.compile(
    r'\bimagem\s+([A-Z])\s+(?:do|da)\s+documento\s+(\d+)\b', re.IGNORECASE
)
# "documento 1, imagem A" / "documento 1 — imagem A"
_DOC_CHILD_RE = re.compile(
    r'\bdocumento\s+(\d+)\s*[,;:\-–—]?\s*imagem\s+([A-Z])\b', re.IGNORECASE
)
# "documento 1", "documentos 2 e 3", "documentos 1, 2 e 3"
_DOC_REF_RE = re.compile(r'\bdocumentos?\s+((?:\d+[\s,;e]+)*\d+)', re.IGNORECASE)
# "documentos 1 a 5" / "documentos de 1 a 4" / "docs. 1-4"
_RANGE_RE = re.compile(
    r'\bdocumentos?\s+(?:de\s+)?(\d+)\s*(?:a|ao|-|–)\s*(\d+)\b',
    re.IGNORECASE,
)
# "a partir dos documentos de 1 a N" — range na mesma frase
_RANGE_FROM_RE = re.compile(
    r'a\s+partir\s+dos\s+documentos\s+de\s+(\d+)\s+a\s+(\d+)',
    re.IGNORECASE,
)
# "cada um dos documentos" / "dos documentos apresentados" / "dados disponíveis nos documentos"
_ALL_DOCS_RE = re.compile(
    r'cada um dos documentos'
    r'|dos documentos apresentados'
    r'|dos dois documentos'
    r'|dos tr[eê]s documentos'
    r'|dados dispon[ií]veis nos documentos'
    r'|a partir dos documentos(?!\s+de\s+\d)',  # "a partir dos documentos" sem range
    re.IGNORECASE,
)


def normalize_humanities(output: dict, extraction: dict | None = None) -> dict:
    """Main entry point."""
    sources = output.get("sources", [])
    assets = output.get("assets", [])
    exam_id = output.get("exam_id", "")

    _ensure_virtual_children(sources, assets)
    _generate_full_source_crop_grupo_i(output, extraction, exam_id)
    _generate_label_based_document_crops(output, extraction, exam_id)
    _generate_child_crops(output, extraction, exam_id)
    _attach_intro_group_visuals(output, extraction, exam_id)
    _attach_implicit_group_i_document(output, extraction)
    _repair_multi_blank_questions(output, extraction)
    _repair_multi_select_questions(output)
    _repair_history_interaction_types(output)
    _remove_history_line_number_artifacts(output)
    _repair_history_text_typos(output)
    _normalize_source_labels(output)
    _repair_known_history_points(output)
    _repair_document_refs(output)
    _strip_cross_group_refs(output)
    _rebuild_all_media(output)

    return output


def _strip_cross_group_refs(output: dict) -> None:
    """Remove sourceRefs where sourceId belongs to a different group than the question.

    This is the BLOCKER 'wrong_cross_group_image_source' from the audit.
    """
    for q in output.get("questions", []):
        gid = q.get("groupId")
        if not gid:
            continue
        refs = q.get("sourceRefs") or []
        clean = [
            ref for ref in refs
            if str(ref.get("sourceId", "")).startswith(gid + "_")
        ]
        if len(clean) < len(refs):
            removed = [r["sourceId"] for r in refs if r not in clean]
            q["sourceRefs"] = clean
            q.setdefault("warnings", []).append({
                "type": "cross_group_ref_stripped",
                "message": f"Removed cross-group sourceRefs: {removed}",
            })
            q["needsHumanReview"] = True


def _repair_multi_blank_questions(output: dict, extraction: dict | None) -> None:
    """Convert malformed open_answer questions into multi_blank_choice when pattern is clear."""
    if not output.get("questions"):
        return

    pages_map = {
        p.get("page"): p
        for p in (extraction or {}).get("pages", [])
        if isinstance(p, dict) and p.get("page")
    }

    repaired = 0
    for q in output.get("questions", []):
        page = pages_map.get(q.get("sourcePage")) or {}
        if repair_multiblank_question_from_page(q, page):
            repaired += 1

    if repaired:
        output.setdefault("warnings", []).append({
            "type": "history_multiblank_repaired",
            "message": f"Repaired {repaired} História multi_blank_choice question(s).",
        })


def _repair_multi_select_questions(output: dict) -> None:
    """Convert História prompts that ask for two selected options into multi_select."""
    repaired = 0
    for q in output.get("questions", []):
        if q.get("type") == "multi_select" and q.get("options"):
            q.setdefault("maxSelections", 2)
            continue
        if q.get("type") != "open_answer":
            continue

        prompt_text = _question_prompt_text(q)
        if not _looks_like_choose_two_prompt(prompt_text):
            continue

        text = _combined_question_text(q)
        options = _extract_roman_options(text) or _extract_letter_options(text)
        if len(options) < 4:
            continue

        q["type"] = "multi_select"
        q["options"] = options
        q["maxSelections"] = 2
        q.setdefault("disciplineData", {})["selectionMode"] = "choose_two"
        _strip_embedded_multi_select_options(q, options)
        repaired += 1

    if repaired:
        output.setdefault("warnings", []).append({
            "type": "history_multi_select_repaired",
            "message": f"Repaired {repaired} História choose-two question(s).",
        })


def _repair_history_interaction_types(output: dict) -> None:
    """Convert old Historia association/ordering prompts away from open textareas."""
    repaired = 0
    for q in output.get("questions", []):
        if q.get("type") != "open_answer":
            continue
        text = _combined_question_text(q)
        low = text.lower()

        if re.search(r"\bassocie\b", low) and re.search(r"\bcoluna\s+[abi12i]+\b", low):
            q["type"] = "matching"
            columns = _extract_matching_columns(text)
            if columns:
                q["matchColumns"] = columns
            q.setdefault("disciplineData", {})["interactionMode"] = "matching"
            repaired += 1
            continue

        if re.search(r"\bordene\s+cronologicamente\b", low):
            q["type"] = "ordering"
            items = _extract_ordering_items(text)
            if items:
                q["orderingItems"] = items
            q.setdefault("disciplineData", {})["interactionMode"] = "ordering"
            repaired += 1

    if repaired:
        output.setdefault("warnings", []).append({
            "type": "history_interaction_type_repaired",
            "message": f"Repaired {repaired} Historia matching/ordering question(s).",
        })


def _extract_matching_columns(text: str) -> dict | None:
    left = _extract_column_items(text, letters=True)
    right = _extract_column_items(text, letters=False)
    if not left or not right:
        return None
    return {"left": left, "right": right}


def _extract_column_items(text: str, letters: bool) -> list[dict]:
    marker = r"[a-e]" if letters else r"\d{1,2}"
    matches = list(re.finditer(
        rf"(?ms)\(({marker})\)\s*(.*?)(?=\n\s*\((?:[a-e]|\d{{1,2}})\)\s*|\Z)",
        text,
        re.IGNORECASE,
    ))
    items = []
    seen = set()
    for match in matches:
        key = match.group(1).strip()
        is_letter = bool(re.match(r"^[a-e]$", key, re.IGNORECASE))
        if is_letter != letters or key in seen:
            continue
        value = _clean_option_text(match.group(2))
        if value:
            items.append({"key": key.lower() if letters else key, "text": value})
            seen.add(key)
    return items


def _extract_ordering_items(text: str) -> list[dict]:
    if re.search(r"\bimagens?\s+A,\s*B,\s*C\s+e\s+D\b", text, re.IGNORECASE):
        return [{"key": letter, "text": f"Imagem {letter}"} for letter in ("A", "B", "C", "D")]

    image_letters = sorted(set(letter.upper() for letter in re.findall(r"\bimagens?\s+([A-D])\b", text, re.IGNORECASE)))
    if len(image_letters) >= 2:
        return [{"key": letter, "text": f"Imagem {letter}"} for letter in image_letters]

    options = _extract_letter_options(text)
    if options:
        return [{"key": opt["letter"], "text": opt["text"]} for opt in options]
    return []


def _remove_history_line_number_artifacts(output: dict) -> None:
    """Remove line-number artifacts such as q95 extracted from document text."""
    questions = output.get("questions", [])
    clean = []
    removed = 0
    for q in questions:
        number = str(q.get("number") or "").strip()
        if number.isdigit() and int(number) > 30 and q.get("groupId"):
            removed += 1
            continue
        clean.append(q)
    if removed:
        output["questions"] = clean
        stats = output.setdefault("metadata", {}).setdefault("stats", {})
        if isinstance(stats, dict):
            stats["answerableItems"] = len(clean)
            stats["mainQuestions"] = len(clean)
        output.setdefault("warnings", []).append({
            "type": "history_line_number_artifact_removed",
            "message": f"Removed {removed} line-number artifact question(s).",
        })


def _combined_question_text(q: dict) -> str:
    parts = [
        str(q.get("statement") or ""),
        str(q.get("statementPlain") or ""),
        str(q.get("sourceTextRaw") or ""),
        str(q.get("rawText") or ""),
    ]
    return "\n".join(part for part in parts if part).replace("\x07", " ")


def _question_prompt_text(q: dict) -> str:
    parts = [
        str(q.get("statement") or ""),
        str(q.get("statementPlain") or ""),
        str(q.get("rawText") or ""),
    ]
    return "\n".join(part for part in parts if part).replace("\x07", " ")


def _looks_like_choose_two_prompt(text: str) -> bool:
    low = text.lower()
    if not re.search(r"\b(duas|2)\b", low):
        return False
    if "complete o texto" in low:
        return False
    return bool(
        re.search(r"\bidentifique\s+as\s+duas\b", low)
        or re.search(r"\bselecione\s+as\s+duas\b", low)
        or "duas opções selecionadas" in low
        or "duas opcoes selecionadas" in low
        or "alíneas que identificam as duas" in low
        or "alineas que identificam as duas" in low
    )


def _extract_roman_options(text: str) -> list[dict]:
    matches = list(re.finditer(
        r"(?ms)(?:^|\n)\s*(IV|V|III|II|I)\.\s*(.*?)(?=\n\s*(?:IV|V|III|II|I)\.\s*|\n\s*(?:Identifique|Selecione|Escreva|No quadro|QUADRO)\b|\Z)",
        text,
    ))
    options = []
    seen = set()
    for match in matches:
        letter = match.group(1).strip()
        if letter in seen:
            continue
        option_text = _clean_option_text(match.group(2))
        if option_text:
            options.append({"letter": letter, "text": option_text})
            seen.add(letter)
    roman_order = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
    options.sort(key=lambda opt: roman_order.get(opt["letter"], 99))
    return options if len(options) >= 4 else []


def _extract_letter_options(text: str) -> list[dict]:
    matches = list(re.finditer(
        r"(?ms)(?:^|\n)\s*([a-e])\)\s*(.*?)(?=\n\s*[a-e]\)\s*|\Z)",
        text,
    ))
    options = []
    seen = set()
    for match in matches:
        letter = match.group(1).strip()
        if letter in seen:
            continue
        option_text = _clean_option_text(match.group(2))
        if option_text:
            options.append({"letter": letter, "text": option_text})
            seen.add(letter)
    options.sort(key=lambda opt: opt["letter"])
    return options if len(options) >= 4 else []


def _clean_option_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.replace("\x07", " ")).strip(" .\n\t")
    return f"{cleaned}." if cleaned else ""


def _strip_embedded_multi_select_options(q: dict, options: list[dict]) -> None:
    option_letters = {str(opt.get("letter") or "") for opt in options}
    if not option_letters:
        return
    roman = option_letters <= {"I", "II", "III", "IV", "V"}
    pattern = (
        r"(?ms)(?:^|\n)\s*(?:IV|V|III|II|I)\.\s*.*?(?=\n\s*(?:Identifique|Selecione|Escreva)\b|\Z)"
        if roman else
        r"(?ms)(?:^|\n)\s*[a-e]\)\s*.*?(?=\n\s*(?:Identifique|Selecione|Escreva)\b|\Z)"
    )
    for key in ("statement", "statementPlain", "statementLatex", "statementFormatted", "statementPlainFormatted", "statementLatexFormatted"):
        value = q.get(key)
        if not isinstance(value, str):
            continue
        cleaned = re.sub(pattern, "\n", value)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if cleaned:
            q[key] = cleaned


def _repair_history_text_typos(output: dict) -> None:
    for q in output.get("questions", []):
        context = _combined_question_text(q).lower()
        if "estética" not in context and "estetica" not in context and "arte" not in context:
            continue
        for blank in q.get("blanks") or []:
            for opt in blank.get("options") or []:
                text = opt.get("text")
                if isinstance(text, str):
                    opt["text"] = re.sub(r"\bclassista\b", "classicista", text, flags=re.IGNORECASE)


def _normalize_source_labels(output: dict) -> None:
    for source in output.get("sources", []):
        label = source.get("label")
        if isinstance(label, str):
            source["label"] = re.sub(r"\s*\(linhas?\s+\d+\s*[-–]\s*\d+\)\s*$", "", label, flags=re.IGNORECASE).strip()


def _repair_known_history_points(output: dict) -> None:
    metadata = output.get("metadata") or {}
    year = str(metadata.get("year") or "")
    phase = str(metadata.get("phase") or "").lower()
    subject = str(metadata.get("subject") or "").lower()
    if year != "2024" or "2" not in phase or "hist" not in subject:
        return

    canonical = {
        ("grupo_iv", "1"): 14,
        ("grupo_iv", "2"): 14,
        ("grupo_iv", "3"): 20,
        ("grupo_iv", "4"): 14,
        ("grupo_iv", "5"): 22,
    }
    repaired = 0
    for q in output.get("questions", []):
        key = (str(q.get("groupId") or ""), str(q.get("number") or ""))
        if key in canonical and q.get("points") != canonical[key]:
            q["points"] = canonical[key]
            repaired += 1
    if repaired:
        output.setdefault("warnings", []).append({
            "type": "history_points_repaired",
            "message": f"Repaired {repaired} História point value(s) from canonical scoring.",
        })


def _normalize_table_rows(table: object) -> list[list]:
    if isinstance(table, dict):
        for key in ("rows", "cells", "data", "matrix"):
            value = table.get(key)
            if isinstance(value, list):
                if value and isinstance(value[0], list):
                    return value
                if key == "cells":
                    return [value]
    if isinstance(table, list) and table and isinstance(table[0], list):
        return table
    return []


def _cell_text(cell: object) -> str:
    if isinstance(cell, dict):
        return str(cell.get("text") or cell.get("value") or cell.get("content") or "").strip()
    return str(cell or "").strip()


# ══════════════════════════════════════════════════════════════════
# VIRTUAL CHILDREN
# ══════════════════════════════════════════════════════════════════

def _ensure_virtual_children(sources: list[dict], assets: list[dict]):
    """For image_set sources without children, create virtual child IDs."""
    for src in sources:
        if src.get("kind") != "image_set":
            continue
        if src.get("children"):
            continue
        refs = src.get("assetRefs", [])
        if len(refs) < 2:
            continue
        src["children"] = [f"{src['sourceId']}_{chr(ord('a') + i)}" for i in range(len(refs))]


# ══════════════════════════════════════════════════════════════════
# FULL SOURCE CROP FOR GRUPO I
# ══════════════════════════════════════════════════════════════════

def _generate_full_source_crop_grupo_i(output: dict, extraction: dict | None, exam_id: str):
    """Generate a full-page source crop for grupo_i_documento_1 from the rendered page."""
    source = next((s for s in output.get("sources", []) if s.get("sourceId") == "grupo_i_documento_1"), None)
    if not source:
        return

    page_num = source.get("pageStart")
    if not page_num:
        return

    # Already has a good full/source crop?
    crops = source.setdefault("crops", {})
    if crops.get("full", {}).get("status") == "success":
        crops["best"] = crops["full"]
        return

    # Find the rendered page image
    page_image_path = _get_page_image(extraction, page_num)
    if not page_image_path or not Path(page_image_path).exists():
        return

    # Generate full source crop (trim header/footer margins)
    output_base = OUTPUT_DIR / exam_id
    sources_dir = output_base / "assets" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(page_image_path)
    w, h = img.size
    # Trim header/footer but keep wide horizontal margins for legends
    cropped = img.crop((int(w * 0.02), int(h * 0.08), int(w * 0.985), int(h * 0.92)))

    filename = "grupo_i_documento_1_full.png"
    path = sources_dir / filename
    cropped.save(path)

    crop_info = {
        "status": "success",
        "method": "full_page_source",
        "relativePath": f"assets/sources/{filename}",
        "url": f"/api/exams/{exam_id}/assets/sources/{filename}",
        "width": cropped.width,
        "height": cropped.height,
    }
    crops["full"] = crop_info
    crops["best"] = crop_info


# ══════════════════════════════════════════════════════════════════
# CHILD CROPS FOR CONJUNTO DOCUMENTAL
# ══════════════════════════════════════════════════════════════════

def _generate_label_based_document_crops(output: dict, extraction: dict | None, exam_id: str) -> None:
    """Split multiple Documento N sources on the same page using label positions."""
    if not extraction or not exam_id:
        return

    pages = {p.get("page"): p for p in extraction.get("pages", []) if isinstance(p, dict)}
    sources_by_page: dict[tuple[str, int], list[dict]] = {}

    for source in output.get("sources", []):
        page_num = source.get("pageStart")
        group_id = source.get("groupId")
        doc_num = _doc_num_from_source(source)
        if not page_num or not group_id or doc_num is None:
            continue
        sources_by_page.setdefault((group_id, int(page_num)), []).append(source)

    for (_group_id, page_num), sources in sources_by_page.items():
        if len(sources) < 2:
            continue

        page = pages.get(page_num)
        page_image_path = page.get("page_image_path") if page else None
        if not page or not page_image_path or not Path(page_image_path).exists():
            continue

        labels = _find_document_label_blocks(page, {_doc_num_from_source(s) for s in sources})
        if len(labels) < 2:
            continue

        try:
            img = Image.open(page_image_path)
        except Exception:
            continue

        output_base = OUTPUT_DIR / exam_id
        sources_dir = output_base / "assets" / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)

        for source in sources:
            doc_num = _doc_num_from_source(source)
            label = labels.get(doc_num)
            if not label:
                continue

            crop_box = _document_crop_box_from_labels(img.size, label, labels, page)
            if not crop_box:
                continue

            cropped = img.crop(crop_box)
            if cropped.width < 80 or cropped.height < 80:
                continue

            filename = f"{source['sourceId']}_full.png"
            path = sources_dir / filename
            cropped.save(path)

            crop_info = {
                "status": "success",
                "method": "history_document_label_split",
                "relativePath": f"assets/sources/{filename}",
                "url": f"/api/exams/{exam_id}/assets/sources/{filename}",
                "width": cropped.width,
                "height": cropped.height,
            }
            crops = source.setdefault("crops", {})
            crops["full"] = crop_info
            crops["best"] = crop_info


def _doc_num_from_source(source: dict) -> int | None:
    match = re.search(r"_documento_(\d+)$", str(source.get("sourceId") or ""))
    return int(match.group(1)) if match else None


def _find_document_label_blocks(page: dict, wanted: set[int | None]) -> dict[int, dict]:
    wanted_nums = {n for n in wanted if isinstance(n, int)}
    labels: dict[int, dict] = {}

    for block in page.get("blocks") or []:
        text = " ".join(str(block.get("text") or "").split())
        match = re.search(r"\bDocumento\s+(\d+)\b", text, re.IGNORECASE)
        bbox = block.get("bbox") or []
        if not match or len(bbox) != 4:
            continue
        doc_num = int(match.group(1))
        if wanted_nums and doc_num not in wanted_nums:
            continue
        labels[doc_num] = {"docNum": doc_num, "bbox": [float(v) for v in bbox]}

    return labels


def _document_crop_box_from_labels(
    image_size: tuple[int, int],
    label: dict,
    labels: dict[int, dict],
    page: dict,
) -> tuple[int, int, int, int] | None:
    img_w, img_h = image_size
    label_bbox = label.get("bbox") or []
    if len(label_bbox) != 4:
        return None

    all_boxes = [l["bbox"] for l in labels.values() if len(l.get("bbox") or []) == 4]
    if not all_boxes:
        return None

    page_w = max([595.0] + [b[2] for b in all_boxes])
    page_h = max([842.0] + [b[3] for b in all_boxes])
    scale_x = img_w / page_w
    scale_y = img_h / page_h

    x0, y0, x1, _y1 = label_bbox
    centers_x = [(b[0] + b[2]) / 2 for b in all_boxes]
    centers_y = [(b[1] + b[3]) / 2 for b in all_boxes]
    same_row = (max(centers_y) - min(centers_y) < 55) and (max(centers_x) - min(centers_x) > page_w * 0.22)

    top = max(0.0, y0 - 12)
    bottom = _first_question_y_after(page, y0) or (page_h * 0.94)

    if same_row:
        ordered = sorted(all_boxes, key=lambda b: (b[0] + b[2]) / 2)
        idx = ordered.index(label_bbox)
        left = 0.0 if idx == 0 else ((ordered[idx - 1][2] + x0) / 2)
        right = page_w if idx == len(ordered) - 1 else ((x1 + ordered[idx + 1][0]) / 2)
        left = max(0.0, left - page_w * 0.035)
        right = min(page_w, right + page_w * 0.035)
    else:
        ordered = sorted(all_boxes, key=lambda b: (b[1], b[0]))
        idx = ordered.index(label_bbox)
        left = page_w * 0.025
        right = page_w * 0.985
        if idx < len(ordered) - 1:
            bottom = min(bottom, max(top + 35, ordered[idx + 1][1] - 8))

    px_box = (
        max(0, int(left * scale_x)),
        max(0, int(top * scale_y)),
        min(img_w, int(right * scale_x)),
        min(img_h, int(bottom * scale_y)),
    )
    if px_box[2] <= px_box[0] or px_box[3] <= px_box[1]:
        return None
    return px_box


def _first_question_y_after(page: dict, y_start: float) -> float | None:
    candidates = []
    for block in page.get("blocks") or []:
        text = str(block.get("text") or "").strip()
        bbox = block.get("bbox") or []
        if len(bbox) != 4 or float(bbox[1]) <= y_start:
            continue
        if re.match(r"^\d{1,2}\.\s+", text):
            candidates.append(float(bbox[1]))
    return min(candidates) - 10 if candidates else None


def _generate_child_crops(output: dict, extraction: dict | None, exam_id: str):
    """For sources labeled 'conjunto documental', split into A/B/C/D child crops."""
    output_base = OUTPUT_DIR / exam_id
    sources_dir = output_base / "assets" / "sources"
    assets_map = {a.get("id"): a for a in output.get("assets", [])}

    for source in output.get("sources", []):
        text = f"{source.get('label', '')} {source.get('description', '')}".lower()
        if "conjunto documental" not in text:
            continue
        if source.get("childCrops"):
            continue

        # Try embedded assets first (avoids quadrant crop pollution)
        child_crops = _create_child_crops_from_asset_refs(output, source, assets_map, output_base)
        if child_crops:
            source["kind"] = "image_set"
            source["children"] = list(child_crops.keys())
            source["childCrops"] = child_crops
            source.setdefault("crops", {})["children"] = child_crops
            continue

        # Fallback: quadrant split of full crop or page image
        full_path = _resolve_crop_path(source, output_base)
        if not full_path:
            page_num = source.get("pageStart")
            page_img = _get_page_image(extraction, page_num) if page_num else None
            if page_img and Path(page_img).exists():
                full_path = Path(page_img)
            else:
                continue

        if not full_path.exists():
            continue

        sources_dir.mkdir(parents=True, exist_ok=True)
        img = Image.open(full_path)
        child_crops = {}
        children = []

        for letter, box in _quadrant_boxes(img.size).items():
            child_id = f"{source['sourceId']}_{letter.lower()}"
            filename = f"{child_id}.png"
            path = sources_dir / filename
            crop = img.crop(box)
            crop.save(path)
            child_crops[child_id] = {
                "status": "success",
                "method": "conjunto_documental_quadrant",
                "relativePath": f"assets/sources/{filename}",
                "url": f"/api/exams/{exam_id}/assets/sources/{filename}",
                "width": crop.width,
                "height": crop.height,
            }
            children.append(child_id)

        source["kind"] = "image_set"
        source["children"] = children
        source["childCrops"] = child_crops


def _create_child_crops_from_asset_refs(
    output: dict, source: dict, assets_map: dict, output_base: Path
) -> dict:
    """Use embedded assets (page8_img0..3) as A/B/C/D crops instead of quadrant split."""
    asset_refs = source.get("assetRefs") or []
    if len(asset_refs) < 4:
        return {}
    asset_refs = sorted(asset_refs, key=lambda aid: _asset_position_key(assets_map.get(aid) or {}))

    exam_id = output.get("exam_id", "")
    sources_dir = output_base / "assets" / "sources"
    child_crops = {}

    for idx, letter in enumerate(["a", "b", "c", "d"]):
        asset = assets_map.get(asset_refs[idx])
        if not asset:
            return {}  # abort if any asset missing

        # Find the actual image file
        src_path = None
        for rel in [
            (asset.get("crops") or {}).get("best", {}).get("relativePath"),
            (asset.get("crops") or {}).get("visual", {}).get("relativePath"),
            (asset.get("crop") or {}).get("relativePath"),
            asset.get("relativePath"),
            f"assets/{asset.get('id')}.png",
        ]:
            if rel:
                candidate = output_base / rel
                if candidate.exists():
                    src_path = candidate
                    break

        if not src_path:
            return {}  # abort if any file missing

        sources_dir.mkdir(parents=True, exist_ok=True)
        child_id = f"{source['sourceId']}_{letter}"
        filename = f"{child_id}.png"
        out_path = sources_dir / filename

        try:
            img = Image.open(src_path)
            img.save(out_path)
        except Exception:
            return {}

        child_crops[child_id] = {
            "status": "success",
            "method": "embedded_asset_child_crop",
            "relativePath": f"assets/sources/{filename}",
            "url": f"/api/exams/{exam_id}/assets/sources/{filename}",
            "width": img.width,
            "height": img.height,
        }

    return child_crops


def _asset_position_key(asset: dict) -> tuple[float, float, str]:
    bbox = asset.get("bbox") or asset.get("bbox_estimate") or {}
    if isinstance(bbox, dict):
        y = float(bbox.get("y", bbox.get("y_pct", 9999)) or 9999)
        x = float(bbox.get("x", bbox.get("x_pct", 9999)) or 9999)
    elif isinstance(bbox, (list, tuple)) and len(bbox) >= 2:
        x = float(bbox[0])
        y = float(bbox[1])
    else:
        x = 9999.0
        y = 9999.0
    return (y, x, str(asset.get("id") or ""))


def _quadrant_boxes(size: tuple[int, int]) -> dict[str, tuple[int, int, int, int]]:
    """Split image into 4 quadrants. C/D start lower to avoid A/B legends."""
    w, h = size
    mid_x = w // 2
    overlap = int(w * 0.018)
    top_bottom = int(h * 0.36)
    lower_top = int(h * 0.36)
    return {
        "A": (0,                       int(h * 0.04), min(w, mid_x + overlap), top_bottom),
        "B": (max(0, mid_x - overlap), int(h * 0.04), w,                       top_bottom),
        "C": (0,                       lower_top,      min(w, mid_x + overlap), int(h * 0.86)),
        "D": (max(0, mid_x - overlap), lower_top,      w,                       int(h * 0.86)),
    }


# ══════════════════════════════════════════════════════════════════
# ATTACH INTRO GROUP VISUALS (Grupo I)
# ══════════════════════════════════════════════════════════════════

def _attach_intro_group_visuals(output: dict, extraction: dict | None, exam_id: str) -> None:
    """Attach intro image/document to Q1/Q2 using full source crop from rendered page."""
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

    # Check if grupo_i_documento_1 already exists (created by source_grouping or _generate_full_source_crop_grupo_i)
    source = next((s for s in sources if s.get("sourceId") == "grupo_i_documento_1"), None)

    if not source:
        # Create from nearest asset before questions
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
        page_num = asset.get("page")

        # Generate full source crop from rendered page (NOT the tight context/visual crop)
        crop_info = _create_full_source_crop(extraction, exam_id, page_num)

        source = {
            "sourceId": source_id,
            "groupId": "grupo_i",
            "label": "Documento 1",
            "kind": "image",
            "pageStart": page_num,
            "pageEnd": page_num,
            "assetRefs": [asset.get("id")],
            "crops": {"best": crop_info, "full": crop_info} if crop_info else {},
        }
        sources.append(source)

    for q in first_questions:
        q["group"] = q.get("group") or "Grupo I"
        q["sourceRefs"] = [{"sourceId": source["sourceId"], "childId": None, "mode": "full_group"}]
        q["visualDependency"] = True


# ══════════════════════════════════════════════════════════════════
# IMPLICIT GROUP I DOCUMENT (no "Documento 1" label in PDF)
# ══════════════════════════════════════════════════════════════════

def _attach_implicit_group_i_document(output: dict, extraction: dict | None) -> None:
    """Create grupo_i_documento_1 when questions mention 'documento' but no source exists.

    Handles exams like 2022 where the table/document has no explicit label.
    """
    if not extraction:
        return

    questions = output.get("questions", [])
    sources = output.setdefault("sources", [])

    group_i_qs = [
        q for q in questions
        if (q.get("group") or "").strip().lower() == "grupo i"
        and not q.get("sourceRefs")
        and "documento" in f"{q.get('statement', '')} {q.get('rawText', '')}".lower()
    ]
    if not group_i_qs:
        return

    source_id = "grupo_i_documento_1"
    if any(s.get("sourceId") == source_id for s in sources):
        for q in group_i_qs:
            q["sourceRefs"] = [{"sourceId": source_id, "childId": None, "mode": "full_group"}]
            q["visualDependency"] = True
        return

    doc_page_num = _find_group_i_document_page(output, extraction, group_i_qs)
    if not doc_page_num:
        return

    pages = extraction.get("pages", [])
    doc_page = next((p for p in pages if p.get("page") == doc_page_num), None)
    if not doc_page:
        return

    crop_info = _create_unlabelled_doc_crop(output, extraction, doc_page)

    sources.append({
        "sourceId": source_id,
        "groupId": "grupo_i",
        "label": "Documento 1",
        "kind": "table_source",
        "pageStart": doc_page_num,
        "pageEnd": doc_page_num,
        "assetRefs": [],
        "crops": {"best": crop_info, "full": crop_info} if crop_info else {},
    })

    for q in group_i_qs:
        q["sourceRefs"] = [{"sourceId": source_id, "childId": None, "mode": "full_group"}]
        q["visualDependency"] = True


def _find_group_i_document_page(output: dict, extraction: dict, group_i_qs: list[dict]) -> int | None:
    """Find the real page of the Grupo I document (not the cover page)."""
    pages_by_num = {
        int(p.get("page")): p
        for p in extraction.get("pages", [])
        if p.get("page") is not None
    }

    # 1. Prefer the page where the question was found. Older História A exams
    # put the Grupo I document on page 2; skipping early pages can select the
    # final scoring page because it also contains "GRUPO I".
    candidates = [
        int(q["sourcePage"]) for q in group_i_qs
        if (q.get("sourcePage") or 0) > 1
        and not _is_scoring_page(pages_by_num.get(int(q.get("sourcePage") or 0), {}))
    ]
    if candidates:
        return min(candidates)

    # 2. Scan extraction pages for "grupo i" + table keywords (skip cover/instructions)
    table_kws = ("norte", "centro", "sul", "total", "senhorio", "distribuição", "localização", "titulares")
    for p in sorted(extraction.get("pages", []), key=lambda x: x.get("page", 0)):
        pnum = p.get("page", 0)
        if pnum <= 1 or _is_scoring_page(p):
            continue
        text = (p.get("text") or "").lower()
        if "grupo i" in text and any(kw in text for kw in table_kws):
            return int(pnum)

    # 3. Fallback: first non-scoring page after cover that has "grupo i"
    for p in sorted(extraction.get("pages", []), key=lambda x: x.get("page", 0)):
        pnum = p.get("page", 0)
        if pnum <= 1 or _is_scoring_page(p):
            continue
        if "grupo i" in (p.get("text") or "").lower():
            return int(pnum)

    return None


def _is_scoring_page(page: dict | None) -> bool:
    text = ((page or {}).get("text") or "").lower()
    if not text:
        return False
    return (
        "cotações" in text
        or "cotacoes" in text
        or "cotação" in text
        or "cotacao" in text
    )


def _create_unlabelled_doc_crop(output: dict, extraction: dict, page_info: dict) -> dict | None:
    """Crop the document/table area from a page, stopping before the first question."""
    page_image_path = page_info.get("page_image_path")
    if not page_image_path or not Path(page_image_path).exists():
        return None

    exam_id = output.get("exam_id", "")
    output_base = OUTPUT_DIR / exam_id
    sources_dir = output_base / "assets" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    try:
        img = Image.open(page_image_path)
    except Exception:
        return None

    w, h = img.size

    # Try to find where question 1 starts from PDF blocks
    bottom_frac = 0.88
    for block in page_info.get("blocks", []):
        text = (block.get("text") or "").strip()
        if re.match(r"^1[\.\s]", text):
            bbox = block.get("bbox") or []
            if len(bbox) == 4:
                y_px = float(bbox[1]) * (200 / 72)
                frac = y_px / h
                if 0.2 < frac < 0.95:
                    bottom_frac = max(0.25, frac - 0.02)
                    break

    cropped = img.crop((int(w * 0.03), int(h * 0.04), int(w * 0.97), int(h * bottom_frac)))

    filename = "grupo_i_documento_1_full.png"
    out_path = sources_dir / filename
    cropped.save(out_path)

    return {
        "status": "success",
        "method": "history_unlabelled_doc_crop",
        "relativePath": f"assets/sources/{filename}",
        "url": f"/api/exams/{exam_id}/assets/sources/{filename}",
        "width": cropped.width,
        "height": cropped.height,
    }


def _dedupe_refs(refs: list[dict]) -> list[dict]:
    seen: set = set()
    out = []
    for ref in refs:
        key = (ref.get("sourceId"), ref.get("childId"), ref.get("mode"))
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


# ══════════════════════════════════════════════════════════════════
# REPAIR DOCUMENT REFS
# ══════════════════════════════════════════════════════════════════

def _repair_document_refs(output: dict) -> None:
    """Parse mixed refs and rebuild sourceRefs for each question."""
    sources = output.get("sources", [])
    source_index = {}  # (groupId, doc_num_str) → source
    for s in sources:
        m = re.search(r'_(\d+)$', s.get("sourceId", ""))
        if m:
            source_index[(s.get("groupId", ""), m.group(1))] = s

    # Group sources by groupId for "all docs" fallback
    from collections import defaultdict
    group_sources: dict[str, list[dict]] = defaultdict(list)
    for s in sources:
        group_sources[s.get("groupId", "")].append(s)
    group_doc_nums: dict[str, list[int]] = defaultdict(list)
    for s in sources:
        m = re.search(r'_(\d+)$', s.get("sourceId", ""))
        if m:
            group_doc_nums[s.get("groupId", "")].append(int(m.group(1)))

    for q in output.get("questions", []):
        text = f"{q.get('statement', '')} {q.get('rawText', '')}"
        group_id = q.get("groupId") or ""
        if not group_id:
            group_label = (q.get("group") or "").lower().replace(" ", "_")
            if group_label:
                group_id = group_label
        if not group_id:
            continue

        expected_docs = resolve_doc_numbers(text, sorted(group_doc_nums.get(group_id, [])))
        new_refs = _parse_refs_from_text(text, group_id, source_index, group_sources)
        if new_refs:
            q["sourceRefs"] = _dedupe_refs(new_refs)
            q["visualDependency"] = True
            actual_docs = set(doc_nums_from_source_refs(q["sourceRefs"]))
            missing = sorted(set(expected_docs) - actual_docs)
            if missing:
                q.setdefault("warnings", []).append({
                    "type": "missing_required_documents",
                    "message": f"Question references document(s) {expected_docs}, but sourceRefs are missing {missing}.",
                    "expected": expected_docs,
                    "actual": sorted(actual_docs),
                })
                q["needsHumanReview"] = True
        elif expected_docs:
            q.setdefault("warnings", []).append({
                "type": "missing_required_documents",
                "message": f"Question references document(s) {expected_docs}, but no matching sources were found in {group_id}.",
                "expected": expected_docs,
                "actual": [],
            })
            q["needsHumanReview"] = True


def _parse_refs_from_text(text: str, group_id: str, source_index: dict,
                          group_sources: dict) -> list[dict]:
    """Parse document references from question text, handling mixed partial+full refs."""
    # 1. Find child-specific refs: "imagem A do documento 1" or "documento 1, imagem A"
    child_by_doc: dict[str, list[str]] = {}
    for m in _CHILD_OF_DOC_RE.finditer(text):
        letter, doc_num = m.group(1).upper(), m.group(2)
        child_by_doc.setdefault(doc_num, []).append(letter)
    for m in _DOC_CHILD_RE.finditer(text):
        doc_num, letter = m.group(1), m.group(2).upper()
        child_by_doc.setdefault(doc_num, []).append(letter)

    # 2. Find all doc numbers mentioned
    all_doc_nums = set()
    for m in _DOC_REF_RE.finditer(text):
        all_doc_nums.update(re.findall(r'\d+', m.group(1)))
    # Also catch standalone "documento N" not captured by the plural pattern
    for m in re.finditer(r'\bdocumento\s+(\d+)\b', text, re.IGNORECASE):
        all_doc_nums.add(m.group(1))

    # 3. "cada um dos documentos" → all docs in group
    if not all_doc_nums and _ALL_DOCS_RE.search(text):
        refs = []
        for s in group_sources.get(group_id, []):
            refs.append({"sourceId": s["sourceId"], "childId": None, "mode": "full_group"})
        return refs

    group_doc_nums = []
    for source in group_sources.get(group_id, []):
        m = re.search(r'_(\d+)$', source.get("sourceId", ""))
        if m:
            group_doc_nums.append(int(m.group(1)))
    resolved_doc_nums = resolve_doc_numbers(text, sorted(group_doc_nums))
    if resolved_doc_nums:
        all_doc_nums = {str(n) for n in resolved_doc_nums}

    if not all_doc_nums:
        return []

    # 4. Build refs: partial docs get specific_child, others get full_group
    refs = []
    for doc_num in sorted(all_doc_nums, key=lambda n: int(n)):
        source = source_index.get((group_id, doc_num))
        if not source:
            continue

        letters = child_by_doc.get(doc_num, [])
        if letters:
            # This doc has specific child references
            for letter in letters:
                child_id = f"{source['sourceId']}_{letter.lower()}"
                if source.get("children") and child_id in source["children"]:
                    refs.append({"sourceId": source["sourceId"], "childId": child_id, "mode": "specific_child"})
                elif source.get("childCrops") and child_id in source["childCrops"]:
                    refs.append({"sourceId": source["sourceId"], "childId": child_id, "mode": "specific_child"})
                else:
                    # Child doesn't exist → show full doc
                    if not any(r["sourceId"] == source["sourceId"] and not r.get("childId") for r in refs):
                        refs.append({"sourceId": source["sourceId"], "childId": None, "mode": "full_group"})
        else:
            # Full document reference
            if not any(r["sourceId"] == source["sourceId"] and not r.get("childId") for r in refs):
                refs.append({"sourceId": source["sourceId"], "childId": None, "mode": "full_group"})

    return refs


# ══════════════════════════════════════════════════════════════════
# REBUILD ALL MEDIA (removes stale entries)
# ══════════════════════════════════════════════════════════════════

def _rebuild_all_media(output: dict) -> None:
    """Rebuild q.media from sourceRefs for ALL questions with sourceRefs.

    This REPLACES any existing media, removing stale entries like page12_img3.png.
    """
    sources = {s.get("sourceId"): s for s in output.get("sources", [])}
    assets_map = {a.get("id"): a for a in output.get("assets", [])}
    exam_id = output.get("exam_id", "")

    for q in output.get("questions", []):
        refs = q.get("sourceRefs") or []
        if not refs:
            # Remove stale media if question has no sourceRefs
            if q.get("media"):
                q.pop("media", None)
            continue

        q["visualDependency"] = True
        is_grupo_i = "grupo_i" in (q.get("groupId") or "")
        media = []

        for ref in refs:
            source = sources.get(ref.get("sourceId"))
            if not source:
                continue

            child_id = ref.get("childId")

            # Specific child
            if child_id and ref.get("mode") == "specific_child":
                url = _resolve_child_url(source, child_id, assets_map, exam_id)
                if url:
                    letter = child_id.split("_")[-1].upper()
                    _append_once(media, {
                        "type": "source_image",
                        "url": url,
                        "sourceId": source.get("sourceId"),
                        "childId": child_id,
                        "label": f"{source.get('label', '')} — imagem {letter}",
                    })
                continue

            # Full source
            if is_grupo_i:
                url = _full_or_context_source_url(source, assets_map)
            else:
                url = _best_source_url(source)

            if url:
                _append_once(media, {
                    "type": "source",
                    "url": url,
                    "sourceId": source.get("sourceId"),
                    "label": source.get("label") or source.get("sourceId"),
                })

        # Always set media (even empty list clears stale)
        q["media"] = media if media else []


# ══════════════════════════════════════════════════════════════════
# FULL SOURCE CROP GENERATION
# ══════════════════════════════════════════════════════════════════

def _create_full_source_crop(extraction: dict | None, exam_id: str, page_num: int | None) -> dict | None:
    """Create a full-page source crop for a historical document from the rendered page.

    This avoids using assets/context/figura_X_pN.png which cuts the legend.
    """
    if not extraction or not exam_id or not page_num:
        return None

    page_image_path = _get_page_image(extraction, page_num)
    if not page_image_path or not Path(page_image_path).exists():
        return None

    output_base = OUTPUT_DIR / exam_id
    sources_dir = output_base / "assets" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    try:
        img = Image.open(page_image_path)
    except Exception:
        return None

    w, h = img.size
    # Wide crop: captures image + legend + bibliographic source
    cropped = img.crop((int(w * 0.02), int(h * 0.08), int(w * 0.985), int(h * 0.92)))

    filename = f"grupo_i_documento_1_full.png"
    path = sources_dir / filename
    cropped.save(path)

    return {
        "status": "success",
        "method": "history_full_page_source",
        "relativePath": f"assets/sources/{filename}",
        "url": f"/api/exams/{exam_id}/assets/sources/{filename}",
        "width": cropped.width,
        "height": cropped.height,
    }


# ══════════════════════════════════════════════════════════════════
# URL RESOLUTION HELPERS
# ══════════════════════════════════════════════════════════════════

def _resolve_child_url(source: dict, child_id: str, assets_map: dict, exam_id: str) -> str | None:
    """Resolve URL for a specific child of a source."""
    # 1. Try childCrops (generated by _generate_child_crops)
    child_crops = source.get("childCrops") or {}
    crop = child_crops.get(child_id)
    if isinstance(crop, dict) and (crop.get("url") or crop.get("relativePath")):
        return crop.get("url") or crop.get("relativePath")

    # 2. Try crops.children
    children_crops = (source.get("crops") or {}).get("children") or {}
    crop = children_crops.get(child_id)
    if isinstance(crop, dict) and (crop.get("url") or crop.get("relativePath")):
        return crop.get("url") or crop.get("relativePath")

    # 3. Fallback: resolve by index in assetRefs
    letter = child_id.split("_")[-1].lower()
    idx = ord(letter) - ord("a") if letter.isalpha() else -1
    asset_refs = source.get("assetRefs", [])
    if 0 <= idx < len(asset_refs):
        asset = assets_map.get(asset_refs[idx])
        if asset:
            return _context_url(asset) or _best_asset_url(asset)

    return None


def _full_or_context_source_url(source: dict, assets_map: dict) -> str | None:
    """For Grupo I: prefer full > context > best."""
    crops = source.get("crops") or {}
    for key in ("full", "best", "context", "document"):
        crop = crops.get(key)
        if isinstance(crop, dict):
            url = crop.get("url") or crop.get("relativePath")
            if url:
                return url
    # Try from assets
    for aid in source.get("assetRefs", []):
        asset = assets_map.get(aid)
        url = _context_url(asset) or _best_asset_url(asset)
        if url:
            return url
    return None


def _best_source_url(source: dict | None) -> str | None:
    if not source:
        return None
    crops = source.get("crops") or {}
    for key in ("best", "full", "document", "context", "visual"):
        crop = crops.get(key)
        if isinstance(crop, dict):
            url = crop.get("url") or crop.get("relativePath")
            if url:
                return url
    return None


def _full_source_url_by_id(sources: list[dict], source_id: str) -> str | None:
    """Get full/best crop URL from a source by ID."""
    src = next((s for s in sources if s.get("sourceId") == source_id), None)
    if not src:
        return None
    crops = src.get("crops") or {}
    for key in ("full", "best"):
        crop = crops.get(key)
        if isinstance(crop, dict):
            url = crop.get("url") or crop.get("relativePath")
            if url:
                return url
    return None


def _context_url(asset: dict | None) -> str | None:
    if not asset:
        return None
    crops = asset.get("crops") or {}
    crop = crops.get("context")
    if isinstance(crop, dict):
        return crop.get("url") or crop.get("relativePath")
    return None


def _best_asset_url(asset: dict | None) -> str | None:
    if not asset:
        return None
    crops = asset.get("crops") or {}
    for key in ("best", "context", "visual", "full"):
        crop = crops.get(key)
        if isinstance(crop, dict):
            url = crop.get("url") or crop.get("relativePath")
            if url:
                return url
    # Legacy
    crop = asset.get("crop")
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


def _resolve_crop_path(source: dict, output_base: Path) -> Path | None:
    """Find the actual file for a source's full/best crop."""
    crops = source.get("crops") or {}
    for key in ("full", "best", "document", "context"):
        crop = crops.get(key)
        if isinstance(crop, dict) and crop.get("relativePath"):
            p = output_base / crop["relativePath"]
            if p.exists():
                return p
    return None


def _get_page_image(extraction: dict | None, page_num: int) -> str | None:
    """Get rendered page image path from extraction data."""
    if not extraction:
        return None
    for p in extraction.get("pages", []):
        if p.get("page") == page_num:
            return p.get("page_image_path")
    return None


def _append_once(media: list[dict], item: dict) -> None:
    url = item.get("url")
    if url and not any(m.get("url") == url for m in media):
        media.append(item)
