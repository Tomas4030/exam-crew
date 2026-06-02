from __future__ import annotations

from __future__ import annotations

import re

from .multiblank import repair_multiblank_question_from_page


QUESTION_START_RE = re.compile(
    r"(?m)^\s*(\d{1,2})(?:\.)\s+(.+)"
)
LETTER_MARKER_RE = re.compile(r"\b([a-f])\)\s*_*\b", re.IGNORECASE)
TABLE_HEADER_RE = re.compile(r"^\s*([a-f])\)\s*$", re.IGNORECASE)
TABLE_OPTION_RE = re.compile(r"^\s*(\d{1,2})[.)]?\s+(.+?)\s*$")


def _extract_multiple_choice_options(block: str) -> list[dict]:
    """Extrai opções (A)...(D) de texto com multiple choice."""
    options = []
    matches = list(re.finditer(r"\(([A-D])\)\s*([^\n(]+)", block, re.IGNORECASE))
    if not matches:
        matches = list(re.finditer(r"(?m)^\s*([A-D])\s*[-–—]\s*(.+)$", block, re.IGNORECASE))
    for m in matches:
        letter = m.group(1).upper()
        text = re.sub(r"\s+", " ", m.group(2)).strip()
        if text and not any(o.get("letter") == letter for o in options):
            options.append({"letter": letter, "text": text})
    return options if len(options) >= 2 else []


def extract_questions_from_text_pages(extraction: dict, subject_profile: dict | None = None) -> list[dict]:
    """
    Fallback deterministico:
    se a visao/IA devolver 0 perguntas, tentar recuperar perguntas do texto nativo do PDF.

    Nao tenta fazer tudo perfeito.
    Objetivo: evitar questions=[].
    """
    questions = []

    for page in extraction.get("pages", []):
        page_num = page.get("page")
        text = page.get("text") or ""

        if not page_num or not text.strip():
            continue

        lowered = text.lower()

        # Ignorar capa/instrucoes iniciais, exceto se ja aparecer Grupo I.
        if page_num <= 2 and "grupo i" not in lowered:
            continue

        # Nao transformar criterios em perguntas.
        if "criterios de classificacao" in lowered:
            continue

        # Nao usar a pagina de cotacoes como perguntas.
        if "cotacoes" in lowered and "grupo" in lowered:
            continue

        matches = list(QUESTION_START_RE.finditer(text))

        if not matches:
            continue

        for idx, match in enumerate(matches):
            number = match.group(1)

            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)

            block = text[start:end].strip()

            # Evitar falsos positivos pequenos.
            if len(block) < 40:
                continue

            q_type = "open_answer"
            blanks = []
            options = []

            if re.search(r"\([A-D]\)", block) or re.search(r"(?m)^\s*[A-D]\s*(?:-|\u2013|\))", block):
                q_type = "multiple_choice"
                options = _extract_multiple_choice_options(block)
            elif _looks_like_multi_blank_choice(block):
                q_type = "multi_blank_choice"
                blanks = _extract_blanks_from_page(page, block)

            q = {
                "questionId": f"q{number}_p{page_num}",
                "number": number,
                "type": q_type,
                "sourcePage": page_num,
                "statement": block,
                "rawText": block,
                "options": options,
                "blanks": blanks,
                "imageRefs": [],
                "tableRefs": [],
                "assetRefs": [],
                "sourceRefs": [],
                "visualDependency": False,
                "confidence": 0.55,
                "needsHumanReview": True,
                "warnings": [{
                    "type": "text_fallback_extracted",
                    "message": "Question extracted by deterministic text fallback because vision returned no questions.",
                }],
                "parentQuestion": None,
                "subQuestions": [],
                "mathHeavy": False,
                "hasGraph": False,
                "hasDiagram": False,
                "hasTable": False,
                "calculatorAllowed": True,
                "points": None,
            }

            repair_multiblank_question_from_page(q, page)
            questions.append(q)

    # Deduplicar por pagina + numero
    seen = set()
    deduped = []

    for q in questions:
        key = (q["sourcePage"], q["number"])
        if key in seen:
            continue

        seen.add(key)
        deduped.append(q)

    return deduped


def _looks_like_multi_blank_choice(block: str) -> bool:
    lowered = block.lower()
    if "opcao adequada para cada espaco" in lowered:
        return True
    if "opção adequada para cada espaço" in lowered:
        return True
    if "cada um dos casos" in lowered and len(LETTER_MARKER_RE.findall(block)) >= 3:
        return True
    return len(set(m.lower() for m in LETTER_MARKER_RE.findall(block))) >= 3


def _extract_blanks_from_page(page: dict, block: str) -> list[dict]:
    tables = page.get("tables") or []

    from_tables = _extract_blanks_from_tables(tables)
    if from_tables:
        return from_tables

    from_text = _extract_blanks_from_text(block)
    if from_text:
        return from_text

    # Fallback minimo com placeholders, para renderizar UI correta.
    letters = sorted(set(m.lower() for m in LETTER_MARKER_RE.findall(block)))
    if not letters:
        letters = ["a", "b", "c", "d"]
    return [{"blankId": letter, "label": f"{letter})", "options": []} for letter in letters]


def _extract_blanks_from_tables(tables: list) -> list[dict]:
    merged: dict[str, dict] = {}

    for table in tables:
        rows = _normalize_table_rows(table)
        if not rows:
            continue

        header = rows[0]
        col_map: dict[int, str] = {}
        for idx, cell in enumerate(header):
            raw = _cell_text(cell)
            m = TABLE_HEADER_RE.match(raw)
            if m:
                col_map[idx] = m.group(1).lower()

        if not col_map:
            continue

        for letter in col_map.values():
            merged.setdefault(letter, {"blankId": letter, "label": f"{letter})", "options": []})

        for row in rows[1:]:
            for col_idx, letter in col_map.items():
                if col_idx >= len(row):
                    continue
                raw = _cell_text(row[col_idx])
                m_opt = TABLE_OPTION_RE.match(raw)
                if not m_opt:
                    continue
                option_no = m_opt.group(1)
                option_text = m_opt.group(2).strip()
                if not option_text:
                    continue
                option_id = f"{letter}{option_no}"
                if not any(o.get("id") == option_id for o in merged[letter]["options"]):
                    merged[letter]["options"].append({
                        "id": option_id,
                        "label": option_no,
                        "text": option_text,
                    })

    if not merged:
        return []

    ordered = []
    for letter in sorted(merged.keys()):
        item = merged[letter]
        item["options"].sort(key=lambda o: int(o.get("label", "0")))
        ordered.append(item)
    return ordered


def _extract_blanks_from_text(block: str) -> list[dict]:
    # Exemplo:
    # a)
    # 1. texto
    # 2. texto
    lines = [ln.rstrip() for ln in block.splitlines()]
    blanks: dict[str, dict] = {}
    current_letter: str | None = None

    for line in lines:
        letter_match = re.match(r"^\s*([a-f])\)\s*(?:_+)?\s*$", line, re.IGNORECASE)
        if letter_match:
            current_letter = letter_match.group(1).lower()
            blanks.setdefault(current_letter, {
                "blankId": current_letter,
                "label": f"{current_letter})",
                "options": [],
            })
            continue

        if not current_letter:
            continue

        opt_match = TABLE_OPTION_RE.match(line.strip())
        if not opt_match:
            continue

        opt_no = opt_match.group(1)
        opt_text = opt_match.group(2).strip()
        if not opt_text:
            continue

        option_id = f"{current_letter}{opt_no}"
        if not any(o.get("id") == option_id for o in blanks[current_letter]["options"]):
            blanks[current_letter]["options"].append({
                "id": option_id,
                "label": opt_no,
                "text": opt_text,
            })

    if not blanks:
        return []

    ordered = []
    for letter in sorted(blanks.keys()):
        item = blanks[letter]
        item["options"].sort(key=lambda o: int(o.get("label", "0")))
        ordered.append(item)
    return ordered


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
        return str(
            cell.get("text")
            or cell.get("value")
            or cell.get("content")
            or ""
        ).strip()
    return str(cell or "").strip()
