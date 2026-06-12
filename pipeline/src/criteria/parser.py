"""Deterministic parser for modern (native-text) Portuguese criteria PDFs.

Extracts, per item: official points, type, multiple-choice answer keys (with
Versão 1 / Versão 2), literal rawText, and best-effort content topics. Also
cross-checks the cotação / optional-pool table at the end of the document.

Modern PDFs (≈2015+) have a clean text layer, so this is reliable. Legacy
scanned PDFs are handled by the vision fallback in run.py.
"""
from __future__ import annotations

import re
from typing import Any

from .extractor import ExtractedCriteria

_ROMAN_TO_GID = {"I": "grupo_i", "II": "grupo_ii", "III": "grupo_iii"}
# Match longest roman first; tolerate a trailing footnote glyph merged into the
# header (e.g. "GRUPO IIP ... 56 pontos" in 2018) by not requiring a word boundary.
_GROUP_HEADER = re.compile(r"^GRUPO\s+(III|II|I)(?![IVX])", re.IGNORECASE)

# A criteria item line WITH content after the dot: "1.  ...  13 pontos".
# Used for chave-table boundary detection (bare "N." chave rows must NOT match).
_ITEM_LINE = re.compile(r"^(\d{1,2})\.\s")
# A prose item anchor: "N." (bare, legacy split items) or "N. ...".
_ITEM_ANCHOR = re.compile(r"^(\d{1,2})\.(\s|$)")
# Letter item anchor for the legacy Grupo I "B" mini-composition (2008-2017):
# "B. [dots] 30 pontos". Only valid when points follow (filtered by points_near).
_LETTER_ANCHOR = re.compile(r"^([A-E])\.(\s|$)")
# Legacy MC answer in prose criteria (2008-2010): "1. Resposta correcta: C ... 5 pontos"
_RESPOSTA_CORRECTA = re.compile(r"Resposta\s+correc?ta\s*:\s*\(?([A-D])\)?", re.IGNORECASE)
# Sub-item anchor for legacy pre-2015 format: "1.1. ..." (N.M. decimal notation).
# After _flatten(), lines like "1.1.\t......\t5 pontos" collapse to "1.1. 5 pontos".
_SUBITEM_ANCHOR = re.compile(r"^(\d{1,2}\.\d{1,2})\.")
# A cotação range line ("1. a 5. ... 40 pontos") — NOT an individual item.
_RANGE_LINE = re.compile(r"^\d{1,2}\.\s*a\s*\d{1,2}\.")
# Points appearing alone on a line (legacy split format: "4." then "8 pontos").
_POINTS_ALONE = re.compile(r"^(\d{1,3})\s*pontos\b", re.IGNORECASE)
_POINTS_IN_LINE = re.compile(r"(\d{1,3})\s*pontos\b", re.IGNORECASE)
# Inline MC answer: "Versão 1: (D);  Versão 2: (B)"
_INLINE_TWO_VERSIONS = re.compile(
    r"Vers[ãa]o\s*1\s*:\s*\(([A-D])\).{0,20}?Vers[ãa]o\s*2\s*:\s*\(([A-D])\)",
    re.IGNORECASE,
)
# Inline single answer right after the number: "1.  (C)"
_INLINE_SINGLE = re.compile(r"^\d{1,2}\.\s*\(([A-D])\)")
_LETTER_ONLY = re.compile(r"^\(?([A-D])\)?$")
# Item number alone on a line — chave table row header.
# Supports both flat "N." (modern) and decimal "N.M." (pre-2015 legacy).
_ITEM_NUM_ONLY = re.compile(r"^(\d{1,2}(?:\.\d{1,2})?)\.$")
# "Versão 1 ‒ B, C e E" / "Versão 2 ‒ a) ... ; b) ..." (rich answer keys, any dash glyph)
_VERSION_ANSWER = re.compile(
    r"Vers[ãa]o\s*([12])\s*[:‒–—\-]\s*(.+)$",
    re.IGNORECASE,
)
# A pure single-letter answer "(B)" or "B"
_SINGLE_LETTER_ANSWER = re.compile(r"^\(?([A-D])\)?$")
# A multi-select answer "B, C e E" / "A, C e D" (options can run A-F)
_MULTI_SELECT_ANSWER = re.compile(r"^[A-F](\s*(,|\be\b)\s*[A-F])+$", re.IGNORECASE)


def _clean_answer(text: str) -> str:
    """Strip trailing footnote markers / stray punctuation from an answer string."""
    text = text.strip()
    # Drop a trailing footnote like " 1 Vide ..." accidentally captured.
    text = re.split(r"\s+\d\s+Vide\b", text)[0].strip()
    return text.rstrip(" .;")


def _infer_selection_type(answer: str) -> str:
    """Best-effort question type from the shape of a criteria answer string."""
    a = answer.strip()
    if _SINGLE_LETTER_ANSWER.match(a):
        return "multiple_choice"
    if _MULTI_SELECT_ANSWER.match(a):
        return "multi_select"
    if re.search(r"\b[a-e]\)", a):  # "a) ... ; b) ..."
        return "multi_blank_choice"
    return "multiple_choice"


def _flatten(extracted: ExtractedCriteria) -> list[tuple[int, str]]:
    """Return [(page_num, line)] across all pages, trimmed, dot-leaders collapsed."""
    out: list[tuple[int, str]] = []
    for page in extracted.pages:
        for raw in page.text.splitlines():
            line = re.sub(r"\.{4,}", " ", raw)  # collapse dot leaders
            line = re.sub(r"[ \t]+", " ", line).strip()
            if line:
                out.append((page.page, line))
    return out


_SPECIFIC_CRITERIA_MARKER = re.compile(r"CRIT[ÉE]RIOS\s+ESPEC[ÍI]FICOS", re.IGNORECASE)


def _section_bounds(lines: list[tuple[int, str]]) -> dict[str, tuple[int, int]]:
    """Map groupId -> (start_idx, end_idx) over the flat line list.

    2008-2010 PDFs open with a COTAÇÕES table that repeats the GRUPO headers
    (with distribution values, no answers) BEFORE the real criteria sections.
    The real sections always follow the "CRITÉRIOS ESPECÍFICOS DE CLASSIFICAÇÃO"
    marker, so group headers before that marker are ignored whenever headers
    exist after it.
    """
    marker_idx = 0
    for idx, (_, line) in enumerate(lines):
        if _SPECIFIC_CRITERIA_MARKER.search(line):
            marker_idx = idx
            break

    def collect(from_idx: int) -> list[tuple[int, str]]:
        marks: list[tuple[int, str]] = []
        for idx in range(from_idx, len(lines)):
            m = _GROUP_HEADER.match(lines[idx][1])
            if m:
                gid = _ROMAN_TO_GID.get(m.group(1).upper())
                if gid and (not marks or marks[-1][1] != gid):
                    marks.append((idx, gid))
        return marks

    marks = collect(marker_idx)
    if not marks:
        marks = collect(0)  # no headers after the marker — fall back to the whole doc

    bounds: dict[str, tuple[int, int]] = {}
    for i, (start, gid) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(lines)
        # Only the first occurrence of each group defines its body.
        bounds.setdefault(gid, (start, end))
    return bounds


def _parse_grupo_i_style(lines: list[tuple[int, str]], start: int, end: int, gid: str) -> list[dict[str, Any]]:
    """Parse a section where each item is introduced by 'N. ...' (Grupo I / III prose)."""
    items: list[dict[str, Any]] = []

    def points_near(idx: int, limit: int) -> int | None:
        """Points on the item line, or alone on the next few lines (split format).

        Extended lookahead (up to 5 lines) to handle rubric-style criteria where
        the point value appears one or two lines after the item header.
        """
        m = _POINTS_IN_LINE.search(lines[idx][1])
        if m:
            return int(m.group(1))
        for k in range(idx + 1, min(idx + 6, limit)):
            nxt = lines[k][1]
            if _ITEM_ANCHOR.match(nxt) or _SUBITEM_ANCHOR.match(nxt):
                break
            pm = _POINTS_ALONE.match(nxt)
            if pm:
                return int(pm.group(1))
            # Also catch inline "N pontos" within the lookahead lines.
            pm2 = _POINTS_IN_LINE.search(nxt)
            if pm2:
                return int(pm2.group(1))
        return None

    # Find item anchors. An anchor is "N." or "N. ..." (bare numbers allowed, to
    # catch legacy split items like "4." / "8 pontos"), not a cotação range
    # ("N. a M."), and must have points on or just after its line — this filters
    # out stray numbered lines inside descriptors / chave rows.
    #
    # Pre-2015 legacy format uses sub-item notation "N.M." (e.g. 2011–2013):
    #   "1.1. [dots] 5 pontos"
    # When sub-items are detected, they replace the parent-level anchors so each
    # sub-item becomes its own criteria entry with the correct number (e.g. "1.1").
    anchors: list[int] = []
    subitem_anchors: list[int] = []
    for idx in range(start, end):
        _, line = lines[idx]
        if _RANGE_LINE.match(line):
            continue
        if _SUBITEM_ANCHOR.match(line):
            if points_near(idx, end) is not None:
                subitem_anchors.append(idx)
        elif _ITEM_ANCHOR.match(line) or _LETTER_ANCHOR.match(line):
            if points_near(idx, end) is not None:
                anchors.append(idx)

    # Prefer sub-item anchors when they exist (pre-2015 N.M. format).
    if subitem_anchors:
        anchors = subitem_anchors

    use_subitem = bool(subitem_anchors)

    for a_i, idx in enumerate(anchors):
        page, line = lines[idx]
        if use_subitem:
            num_m_s = _SUBITEM_ANCHOR.match(line)
            number = num_m_s.group(1) if num_m_s else line.split(".")[0].strip()
        else:
            num_m = _ITEM_ANCHOR.match(line) or _LETTER_ANCHOR.match(line)
            number = num_m.group(1) if num_m else line.split(".")[0].strip()

        block_end = anchors[a_i + 1] if a_i + 1 < len(anchors) else end
        points = points_near(idx, block_end)
        raw_lines = [lines[j][1] for j in range(idx, block_end)]
        pages = sorted({lines[j][0] for j in range(idx, block_end)})
        raw_text = "\n".join(raw_lines).strip()

        correct = None
        item_type = "open_answer"
        two = _INLINE_TWO_VERSIONS.search(line)
        resposta = _RESPOSTA_CORRECTA.search(line)
        if two:
            correct = {"v1": two.group(1).upper(), "v2": two.group(2).upper()}
            item_type = "multiple_choice"
        elif resposta:
            correct = {"v1": resposta.group(1).upper()}
            item_type = "multiple_choice"
        else:
            single = _INLINE_SINGLE.match(line)
            if single:
                correct = {"v1": single.group(1).upper()}
                item_type = "multiple_choice"
            else:
                # Multi-line "Versão N ‒ <answer>" form (rich keys: multi_select,
                # multi_blank sequences, or a plain letter on its own line).
                version_answers: dict[str, str] = {}
                for rl in raw_lines:
                    vm = _VERSION_ANSWER.search(rl)
                    if vm:
                        ans = _clean_answer(vm.group(2))
                        if ans:
                            version_answers[f"v{vm.group(1)}"] = ans
                if version_answers:
                    # Normalize a parenthesized single letter to a bare letter.
                    for k, v in list(version_answers.items()):
                        lm = _SINGLE_LETTER_ANSWER.match(v)
                        if lm:
                            version_answers[k] = lm.group(1).upper()
                    correct = version_answers
                    item_type = _infer_selection_type(next(iter(version_answers.values())))

        items.append({
            "groupId": gid,
            "number": number,
            "points": points,
            "type": item_type,
            "correctAnswer": correct,
            "rawText": raw_text,
            "sourcePages": pages,
            "contentTopics": _extract_content_topics(raw_lines),
            "confidence": 0.95,
        })
    return items


def _extract_content_topics(raw_lines: list[str]) -> list[str]:
    """Best-effort: bullet topics between 'Devem ser abordados...' and 'Aspetos de'."""
    topics: list[str] = []
    capturing = False
    buf: list[str] = []
    for line in raw_lines:
        low = line.lower()
        if "devem ser abordados" in low or "deve ser abordado" in low or "tópicos seguintes" in low:
            capturing = True
            continue
        if capturing and low.startswith("aspetos de"):
            break
        if capturing:
            # Topic bullets often start with the dash glyph or hyphen.
            cleaned = line.lstrip("−–- ").strip()
            if not cleaned:
                if buf:
                    topics.append(" ".join(buf).strip())
                    buf = []
                continue
            if line[:1] in "−–-" and buf:
                topics.append(" ".join(buf).strip())
                buf = [cleaned]
            else:
                buf.append(cleaned)
    if buf:
        topics.append(" ".join(buf).strip())
    return [t for t in topics if len(t) > 4][:12]


def _parse_chave_table(lines: list[tuple[int, str]], start: int, end: int, gid: str) -> list[dict[str, Any]]:
    """Parse a vertical 'Chave' answer-key table (Grupo II style).

    Layout (one token per line):
        Chave / ITENS / VERSÃO 1 / VERSÃO 2 / PONTUAÇÃO
        1. / (C) / (B) / 13
        2. / (C) / (D) / 13 ...
    Also handles single-version tables (ITENS / CHAVE / PONTUAÇÃO) and
    mixed tables where some rows are MC (letter answer) and others are
    open-answer (text answer), e.g. 2016 items 8–10:
        8. / (Oração) subordinada (adverbial) consecutiva / 5
    """
    # Locate header to learn how many version columns exist.
    has_v2 = False
    header_end = start
    for idx in range(start, end):
        low = lines[idx][1].lower()
        if "versão 2" in low or "versao 2" in low:
            has_v2 = True
        if "pontuação" in low or "pontuacao" in low:
            header_end = idx + 1
            break

    items: list[dict[str, Any]] = []
    idx = header_end if header_end > start else start
    while idx < end:
        page, line = lines[idx]
        # A prose item line ("6. ....") after the table means the chave ended.
        if items and _ITEM_LINE.match(line) and not _RANGE_LINE.match(line):
            break
        num_m = _ITEM_NUM_ONLY.match(line)
        if not num_m:
            idx += 1
            continue
        number = num_m.group(1)
        v1 = v2 = None
        points = None
        j = idx + 1
        letters: list[str] = []
        text_tokens: list[str] = []
        while j < end:
            tok = lines[j][1]
            lm = _LETTER_ONLY.match(tok)
            if lm:
                letters.append(lm.group(1).upper())
                j += 1
                continue
            if re.match(r"^\d{1,3}$", tok):
                if points is not None:
                    break  # already have points — bare digit belongs to what follows
                points = int(tok)
                j += 1
                break
            # "N pontos" alone right after the item number (2019+ open items inside
            # the chave: "6." / "8 pontos" / answer text / "Níveis" rubric table).
            pa = _POINTS_ALONE.match(tok)
            if pa and points is None and not letters:
                points = int(pa.group(1))
                j += 1
                continue  # keep collecting the answer text that follows
            # A performance-level rubric ("Níveis / Descritores...") ends the row —
            # its level numbers (2/1) and per-level scores must NOT become points.
            if tok.lower() in ("níveis", "niveis", "descritores de desempenho"):
                break
            # Non-letter, non-number: could be an open-answer text token or
            # the start of the next row / end of table.
            if _ITEM_NUM_ONLY.match(tok):
                break  # Next item header — this row has no points; end table.
            if _ITEM_LINE.match(tok) and not _RANGE_LINE.match(tok):
                break  # Prose item — end of chave section.
            # If we already collected letters we won't see text answers;
            # anything else means the row is over.
            if letters:
                break
            # Collect as candidate open-answer text (skip noise lines).
            if tok:
                text_tokens.append(tok)
            j += 1

        if not letters and points is None:
            # No letter answer and no point value found — genuine end of table.
            break

        if letters:
            # MC item
            v1 = letters[0]
            if has_v2 and len(letters) > 1:
                v2 = letters[1]
            correct: dict | None = {"v1": v1}
            if v2:
                correct["v2"] = v2  # type: ignore[assignment]
            items.append({
                "groupId": gid,
                "number": number,
                "points": points,
                "type": "multiple_choice",
                "correctAnswer": correct if v1 else None,
                "rawText": "\n".join(lines[k][1] for k in range(idx, j)),
                "sourcePages": [page],
                "contentTopics": [],
                "confidence": 0.97 if v1 else 0.4,
            })
        else:
            # Open-answer item in chave table (text answer, e.g. 2016 items 8–10).
            raw_answer = " ".join(text_tokens).strip() if text_tokens else None
            items.append({
                "groupId": gid,
                "number": number,
                "points": points,
                "type": "open_answer",
                "correctAnswer": {"v1": raw_answer} if raw_answer else None,
                "rawText": "\n".join(lines[k][1] for k in range(idx, j)),
                "sourcePages": [page],
                "contentTopics": [],
                "confidence": 0.90,
            })
        idx = j
    return items


def _parse_grupo_iii(lines: list[tuple[int, str]], start: int, end: int) -> list[dict[str, Any]]:
    """Composition: single essay item; points = sum of parameter cotações (ETD + CL)."""
    # Stop before the cotação/optional-pool table if it falls inside this slice.
    real_end = end
    for idx in range(start, end):
        low = lines[idx][1].lower()
        if "cotação (em pontos)" in low or "cotacao (em pontos)" in low or low.startswith("total"):
            real_end = idx
            break

    param_points: list[int] = []
    for idx in range(start, real_end):
        line = lines[idx][1]
        low = line.lower()
        # Accept both modern ("correção") and pre-1990-agreement ("correcção") spellings,
        # and the 2008-2010 markers "(C)*" / "(F)**" used instead of (ETD)/(CL).
        if (
            "(etd)" in low or "(cl)" in low
            or "estruturação temática" in low
            or re.search(r"correc?ção lingu", low)
        ):
            pm = _POINTS_IN_LINE.search(line)
            if pm:
                param_points.append(int(pm.group(1)))
    pages = sorted({lines[idx][0] for idx in range(start, real_end)})
    raw_text = "\n".join(lines[idx][1] for idx in range(start, real_end)).strip()
    total = sum(param_points) if param_points else None
    return [{
        "groupId": "grupo_iii",
        "number": "1",
        "points": total,
        "type": "essay",
        "correctAnswer": None,
        "rawText": raw_text,
        "sourcePages": pages,
        "contentTopics": [],
        "confidence": 0.9 if total else 0.5,
        "parameterPoints": param_points or None,
    }]


def _parse_cross_check(lines: list[tuple[int, str]]) -> dict[str, Any]:
    """Pull the cotação table totals / optional-pool formula for auditing."""
    text = "\n".join(line for _, line in lines)
    out: dict[str, Any] = {}
    total_m = re.search(r"TOTAL\s+(\d{2,3})\b", text)
    if total_m:
        out["total"] = int(total_m.group(1))
    pool_m = re.search(r"(\d+)\s*[x×]\s*(\d+)\s*pontos", text, re.IGNORECASE)
    if pool_m:
        out["optionalPool"] = {"perItem": int(pool_m.group(2)), "count": int(pool_m.group(1))}
    choose_m = re.search(r"os\s+(\d+)\s+iten[s]?\s+cuj", text, re.IGNORECASE)
    if choose_m:
        out["optionalChoose"] = int(choose_m.group(1))
    return out


def parse_criteria_text(extracted: ExtractedCriteria) -> dict[str, Any]:
    """Parse a native-text criteria document into structured items + answer keys."""
    lines = _flatten(extracted)
    bounds = _section_bounds(lines)

    items: list[dict[str, Any]] = []
    if "grupo_i" in bounds:
        s, e = bounds["grupo_i"]
        items += _parse_grupo_i_style(lines, s, e, "grupo_i")
    if "grupo_ii" in bounds:
        s, e = bounds["grupo_ii"]
        # Grupo II mixes a Chave answer-key table (MC items) with prose items
        # (open answers, e.g. items 6/7 in 2018). Parse both and merge: the chave
        # is authoritative for the items it covers.
        chave = _parse_chave_table(lines, s, e, "grupo_ii")
        prose = _parse_grupo_i_style(lines, s, e, "grupo_ii")
        by_num: dict[str, dict] = {}
        for it in prose:
            by_num[it["number"]] = it
        for it in chave:  # chave overrides prose for MC items
            by_num[it["number"]] = it
        items += sorted(by_num.values(), key=lambda x: (len(x["number"]), x["number"]))
    if "grupo_iii" in bounds:
        s, e = bounds["grupo_iii"]
        items += _parse_grupo_iii(lines, s, e)

    # Build answer keys (per version) from items that carry a correctAnswer.
    versions: dict[str, list[dict[str, str]]] = {"1": [], "2": []}
    for it in items:
        ca = it.get("correctAnswer")
        if not ca:
            continue
        if ca.get("v1"):
            versions["1"].append({"groupId": it["groupId"], "number": it["number"], "correctAnswer": ca["v1"]})
        if ca.get("v2"):
            versions["2"].append({"groupId": it["groupId"], "number": it["number"], "correctAnswer": ca["v2"]})

    answer_keys = []
    if versions["1"]:
        answer_keys.append({"version": "1", "default": True, "items": versions["1"]})
    if versions["2"]:
        answer_keys.append({"version": "2", "default": False, "items": versions["2"]})

    return {
        "items": items,
        "answerKeys": answer_keys,
        "crossCheck": _parse_cross_check(lines),
    }
