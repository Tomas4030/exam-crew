from __future__ import annotations

import re


def looks_like_multi_blank_choice(text: str) -> bool:
    t = (text or "").lower()
    return (
        "complete o texto seguinte" in t
        and (
            "opção adequada para cada espaço" in t
            or "opcao adequada para cada espaco" in t
            or "cada espaço" in t
            or "cada espaco" in t
        )
        and re.search(r"\ba\)", t)
        and re.search(r"\bb\)", t)
    )


def extract_blank_markers(text: str) -> list[str]:
    markers = []
    for letter in ("a", "b", "c", "d", "e", "f"):
        if re.search(rf"\b{letter}\)", text or "", flags=re.IGNORECASE):
            markers.append(f"{letter})")
    return markers


def _clean_multiblank_option_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("\u0007", "").replace("\x07", "").replace("\x00", "").replace("\ufffd", "")
    value = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    value = re.sub(r"\s+", " ", value).strip().strip(" .;")
    value = value.replace("iImperador", "imperador").replace("IImperador", "imperador")
    value = value.replace("lImperador", "imperador").replace("iimperador", "imperador")
    value = value.replace("limperador", "imperador")
    value = re.sub(r"^Imperador\b", "imperador", value)
    return value.strip()


def _split_numbered_options(cell: str) -> list[dict]:
    """
    Parte uma string que pode ter várias opções coladas.
    '1. czar Nicolau II 2. imperador Francisco José 3. kaiser Guilherme II'
    -> [{"letter": "1", "text": "czar Nicolau II"}, ...]
    """
    if not cell:
        return []
    text = (
        str(cell)
        .replace("\u00a0", " ")
        .replace("\u2002", " ")
        .replace("\t", " ")
        .replace("\u0007", "")
        .replace("\x07", "")
        .replace("\x00", "")
        .replace("\ufffd", "")
    )
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.findall(r"([1-9])\.\s*(.*?)(?=\s+[1-9]\.\s+|$)", text, flags=re.DOTALL)
    out = []
    for num, value in parts:
        value = _clean_multiblank_option_text(value)
        if value:
            out.append({"letter": num, "text": value})
    return out


def extract_multiblank_options_from_page_text(page_text: str, markers: list[str]) -> list[dict]:
    if not page_text or not markers:
        return []

    compact = re.sub(r"[ \t]+", " ", page_text.replace("\u00a0", " ").replace("\u2002", " ").replace("\t", " ").replace("\u0007", "").replace("\x07", "").replace("\x00", "").replace("\ufffd", ""))

    header = re.search(r"\ba\)\s*b\)\s*c\)\s*d\)", compact, flags=re.IGNORECASE)
    if not header:
        return []

    zone = compact[header.end():]

    # Parar antes da próxima pergunta.
    next_q = re.search(r"(?m)^\s+\d{1,2}\.\s+[A-ZÁÉÍÓÚÂÊÔÃÕÀÇ]", zone)
    if next_q:
        zone = zone[:next_q.start()]

    entries = re.findall(r"([1-9])\.\s*(.*?)(?=\s+[1-9]\.\s+|$)", zone, flags=re.DOTALL)

    cleaned = []
    for num, value in entries:
        value = _clean_multiblank_option_text(value)
        if value and len(value) <= 90:
            cleaned.append({"letter": num, "text": value})

    marker_count = len(markers)
    if len(cleaned) < marker_count * 2:
        return []

    per_blank = len(cleaned) // marker_count
    if per_blank < 2:
        return []

    numbers = [item["letter"] for item in cleaned[: marker_count * per_blank]]
    row_wise = False
    if len(numbers) >= marker_count * 2:
        first_row = numbers[:marker_count]
        second_row = numbers[marker_count: marker_count * 2]
        row_wise = (
            len(set(first_row)) == 1
            and len(set(second_row)) == 1
            and first_row[0] != second_row[0]
        )

    blanks = []
    if row_wise:
        for col_idx, marker in enumerate(markers):
            options = []
            for row_idx in range(per_blank):
                item_idx = row_idx * marker_count + col_idx
                if item_idx < len(cleaned):
                    options.append(cleaned[item_idx])
            blanks.append({"number": marker, "options": options})
    else:
        idx = 0
        for marker in markers:
            blanks.append({"number": marker, "options": cleaned[idx: idx + per_blank]})
            idx += per_blank
    return blanks


def extract_multiblank_options_from_tables(page: dict, markers: list[str]) -> list[dict]:
    tables = page.get("tables") or []

    for table in tables:
        rows = table.get("rows") or []
        if len(rows) < 2:
            continue

        header_joined = " ".join(str(c or "").strip().lower() for c in rows[0])
        if not all(m.lower() in header_joined for m in markers[: min(4, len(markers))]):
            continue

        blanks = []
        for col_idx, marker in enumerate(markers):
            options = []
            for row in rows[1:]:
                if col_idx >= len(row):
                    continue
                cell = str(row[col_idx] or "").strip()
                if not cell:
                    continue
                parts = _split_numbered_options(cell)
                if parts:
                    options.extend(parts)
                else:
                    options.append({"letter": str(len(options) + 1), "text": cell})

            if options:
                blanks.append({"number": marker, "options": options})

        if blanks:
            return blanks

    return []


def repair_multiblank_question_from_page(q: dict, page: dict) -> bool:
    text = f"{q.get('statement', '')}\n{q.get('rawText', '')}"

    existing_blanks = q.get("blanks") or []
    has_valid_blanks = q.get("type") == "multi_blank_choice" and bool(existing_blanks)
    if has_valid_blanks:
        for blank in existing_blanks:
            if not isinstance(blank, dict):
                has_valid_blanks = False
                break
            if not blank.get("number"):
                has_valid_blanks = False
                break
            if not isinstance(blank.get("options"), list) or not blank.get("options"):
                has_valid_blanks = False
                break
    if has_valid_blanks:
        return False

    if not looks_like_multi_blank_choice(text):
        return False

    markers = extract_blank_markers(text)
    if not markers:
        return False

    # Texto da página costuma preservar melhor a ordem para História.
    blanks = extract_multiblank_options_from_page_text(page.get("text", ""), markers)
    if not blanks:
        blanks = extract_multiblank_options_from_tables(page, markers)

    if not blanks:
        q.setdefault("warnings", []).append({
            "type": "missing_multiblank_options",
            "message": "Question looks like multi_blank_choice, but options table could not be extracted.",
        })
        q["needsHumanReview"] = True
        return False

    q["type"] = "multi_blank_choice"
    q["blanks"] = blanks
    q["options"] = []
    q["needsHumanReview"] = False
    q.setdefault("warnings", []).append({
        "type": "multiblank_repaired",
        "message": "Question converted to multi_blank_choice from page text/table.",
    })
    return True
