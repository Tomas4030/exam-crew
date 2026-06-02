from __future__ import annotations

import re


def looks_like_multi_blank_choice(text: str) -> bool:
    """
    Deteta perguntas do tipo:
    'Complete o texto seguinte, selecionando a opção adequada para cada espaço.'
    """
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
    """
    Retorna ['a)', 'b)', 'c)', 'd)'] se esses marcadores existirem.
    """
    markers = []

    for letter in ("a", "b", "c", "d", "e", "f"):
        if re.search(rf"\b{letter}\)", text or "", flags=re.IGNORECASE):
            markers.append(f"{letter})")

    return markers


def extract_multiblank_options_from_page_text(page_text: str, markers: list[str]) -> list[dict]:
    """
    Extrai opções a partir do texto completo da página.

    Suporta o caso do História A 2025:
    a) b) c) d)
    1. czar Nicolau II
    2. imperador Francisco José
    3. kaiser Guilherme II
    1. socialista
    2. demoliberal
    3. marxista
    ...
    """
    if not page_text or not markers:
        return []

    text = (
        page_text
        .replace("\u00a0", " ")
        .replace("\u2002", " ")
        .replace("\t", " ")
    )

    # Cortar a partir da zona dos cabeçalhos a) b) c) d)
    header = re.search(
        r"\ba\)\s*b\)\s*c\)\s*d\)",
        re.sub(r"[ \t]+", " ", text),
        flags=re.IGNORECASE,
    )

    if header:
        compact = re.sub(r"[ \t]+", " ", text)
        zone = compact[header.start():]
    else:
        # fallback: começa na primeira linha onde aparece a)
        m = re.search(r"\ba\)", text, flags=re.IGNORECASE)
        zone = text[m.start():] if m else text

    # Captura entradas numeradas: 1. texto / 2. texto / 3. texto
    entries = re.findall(
        r"([1-9])\.\s+(.+?)(?=\s+[1-9]\.\s+|\n\s*[1-9]\.\s+|$)",
        zone,
        flags=re.DOTALL,
    )

    cleaned: list[tuple[str, str]] = []

    for num, value in entries:
        value = re.sub(r"\s+", " ", value).strip()
        value = value.strip(" .;")

        if not value:
            continue

        # Evita apanhar blocos gigantes por erro.
        if len(value) > 90:
            continue

        # Evita apanhar linhas de instrução como opção.
        low = value.lower()
        if "complete o texto" in low or "folha de respostas" in low:
            continue

        cleaned.append((num, value))

    if len(cleaned) < len(markers) * 2:
        return []

    # Caso mais comum no texto extraído deste PDF:
    # primeiro vêm as 3 opções de a), depois as 3 de b), depois c), depois d).
    expected_per_blank = 3
    needed = len(markers) * expected_per_blank

    if len(cleaned) >= needed:
        blanks = []
        idx = 0

        for marker in markers:
            options = []

            for _ in range(expected_per_blank):
                if idx >= len(cleaned):
                    break

                num, value = cleaned[idx]
                options.append({
                    "letter": num,
                    "text": value,
                })
                idx += 1

            if options:
                blanks.append({
                    "number": marker,
                    "options": options,
                })

        if len(blanks) >= 2:
            return blanks

    return []


def extract_multiblank_options_from_tables(page: dict, markers: list[str]) -> list[dict]:
    """
    Tenta extrair opções usando tabelas detetadas pelo PyMuPDF.

    Se a tabela vier bem estruturada:
    a) | b) | c) | d)
    1... | 1... | 1... | 1...
    """
    tables = page.get("tables") or []

    for table in tables:
        rows = table.get("rows") or []

        if len(rows) < 2:
            continue

        header = [str(cell or "").strip().lower() for cell in rows[0]]
        header_joined = " ".join(header)

        if not all(marker.lower() in header_joined for marker in markers[: min(4, len(markers))]):
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

                m = re.match(r"^([1-9])\.\s*(.+)$", cell)
                if m:
                    options.append({
                        "letter": m.group(1),
                        "text": m.group(2).strip(),
                    })
                else:
                    options.append({
                        "letter": str(len(options) + 1),
                        "text": cell,
                    })

            if options:
                blanks.append({
                    "number": marker,
                    "options": options,
                })

        if blanks:
            return blanks

    return []


def repair_multiblank_question_from_page(q: dict, page: dict) -> bool:
    """
    Converte uma pergunta open_answer mal classificada em multi_blank_choice,
    se conseguir encontrar a tabela de opções na página.

    Retorna True se a pergunta foi convertida.
    """
    text = f"{q.get('statement', '')}\n{q.get('rawText', '')}"

    if q.get("type") == "multi_blank_choice" and q.get("blanks"):
        return False

    if not looks_like_multi_blank_choice(text):
        return False

    markers = extract_blank_markers(text)

    if not markers:
        return False

    blanks = extract_multiblank_options_from_tables(page, markers)

    if not blanks:
        blanks = extract_multiblank_options_from_page_text(page.get("text", ""), markers)

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
