"""Resolve the official Critérios de Classificação PDF URL for a given exam.

The exam statement carries metadata.year ("2022"), metadata.phase ("1ª Fase"),
metadata.subject and metadata.sourceUrl. The criteria PDF lives at a sibling
path on examesnacionais.com.pt; the filename is normally the exam filename plus
a "_Criterios" suffix, but spelling has drifted over the years
("Portugues_639_Criterios.pdf", "Portugues639_Criterios.pdf",
"Portugues_Criterios.pdf", "Historia-A_Criterios.pdf", …).

Resolution strategy:
    1. Derive candidates from the exam's own sourceUrl (same folder, same stem,
       known criteria suffixes) — works for EVERY subject without a table.
    2. Add subject-specific known stems for when the sourceUrl is missing.
    3. Probe candidates in order and return the first 200/206.
"""
from __future__ import annotations

import re

import httpx

BASE = "https://www.examesnacionais.com.pt/exames-nacionais/12ano"

# Suffix spellings observed across years, most common first.
_CRITERIA_SUFFIXES = ["_Criterios", "Criterios", "-Criterios", "_criterios"]

# Known exam-file stems per normalized subject, used when sourceUrl is absent.
# The first stem is the most common spelling on examesnacionais.com.pt.
_SUBJECT_STEMS: dict[str, list[str]] = {
    "portugues": ["Portugues_639", "Portugues639", "Portugues"],
    "matematica a": ["Matematica-A", "Matematica_635", "MatematicaA_635", "Matematica"],
    "matematica b": ["Matematica-B", "Matematica_735"],
    "macs": ["MACS_835", "MACS"],
    "historia a": ["Historia-A", "HistoriaA_623", "Historia_623"],
    "historia b": ["Historia-B", "HistoriaB_723"],
    "fisica e quimica": ["Fisica-Quimica-A", "FisicaQuimicaA_715", "FQA_715"],
    "biologia e geologia": ["Biologia-Geologia", "BiologiaGeologia_702"],
    "geografia a": ["Geografia-A", "GeografiaA_719"],
    "filosofia": ["Filosofia_714", "Filosofia"],
    "economia a": ["Economia-A", "EconomiaA_712"],
    "geometria descritiva": ["Geometria-Descritiva-A", "GDA_708"],
    "desenho a": ["Desenho-A", "DesenhoA_706"],
    "ingles": ["Ingles_550", "Ingles"],
    "frances": ["Frances_517", "Frances"],
    "espanhol": ["Espanhol_547", "Espanhol"],
    "alemao": ["Alemao_501", "Alemao"],
    "latim a": ["Latim-A", "LatimA_734"],
    "literatura portuguesa": ["Literatura-Portuguesa", "LiteraturaPortuguesa_732"],
}

_USER_AGENT = "Mozilla/5.0 (ExamCrew criteria pipeline)"


def _normalize_subject(value: str) -> str:
    s = (value or "").strip().lower()
    for a, b in (("á", "a"), ("â", "a"), ("ã", "a"), ("é", "e"), ("ê", "e"),
                 ("í", "i"), ("ó", "o"), ("ô", "o"), ("õ", "o"), ("ú", "u"), ("ç", "c")):
        s = s.replace(a, b)
    return s


def parse_year_phase(metadata: dict) -> tuple[str | None, int | None]:
    """Return (year, phase_int) from exam metadata, falling back to sourceUrl."""
    year = None
    phase = None

    raw_year = str(metadata.get("year") or "").strip()
    m = re.search(r"20\d{2}", raw_year)
    if m:
        year = m.group()

    raw_phase = str(metadata.get("phase") or "")
    pm = re.search(r"([12])", raw_phase)
    if pm:
        phase = int(pm.group(1))

    # Fall back to the source URL pattern /2022-1fase/
    if not year or not phase:
        src = str(metadata.get("sourceUrl") or "")
        um = re.search(r"/(20\d{2})-([12])fase/", src, re.IGNORECASE)
        if um:
            year = year or um.group(1)
            phase = phase or int(um.group(2))

    return year, phase


def candidate_urls(metadata: dict) -> list[str]:
    """All candidate criteria PDF URLs for an exam, in probe order."""
    year, phase = parse_year_phase(metadata)
    if not year or not phase:
        return []
    folder = f"{BASE}/{year}-{phase}fase"

    stems: list[str] = []

    # 1) Stem straight from the exam's own URL — subject-agnostic and exact.
    src = str(metadata.get("sourceUrl") or "")
    um = re.search(r"/([^/]+)\.pdf$", src, re.IGNORECASE)
    if um:
        stems.append(um.group(1))

    # 2) Known stems for the subject.
    subject = _normalize_subject(str(metadata.get("subject") or ""))
    for subj_key, subj_stems in _SUBJECT_STEMS.items():
        if subj_key in subject or subject in subj_key:
            stems.extend(subj_stems)
            break

    # 3) Stems with the exam code stripped ("Portugues_639" → "Portugues").
    for stem in list(stems):
        bare = re.sub(r"[_-]?\d{3}$", "", stem)
        if bare and bare not in stems:
            stems.append(bare)

    urls: list[str] = []
    seen: set[str] = set()
    for stem in stems:
        for suffix in _CRITERIA_SUFFIXES:
            url = f"{folder}/{stem}{suffix}.pdf"
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def resolve_criteria_url(metadata: dict, *, timeout: float = 30.0) -> tuple[str | None, list[str]]:
    """Probe candidate URLs and return (working_url, tried).

    Returns (None, tried) when none respond 200.
    """
    tried: list[str] = []
    headers = {"User-Agent": _USER_AGENT}
    for url in candidate_urls(metadata):
        tried.append(url)
        try:
            # HEAD first (cheap); some servers don't support it, so fall back to GET range.
            resp = httpx.head(url, timeout=timeout, follow_redirects=True, headers=headers)
            if resp.status_code == 405 or resp.status_code == 501:
                resp = httpx.get(
                    url, timeout=timeout, follow_redirects=True,
                    headers={**headers, "Range": "bytes=0-1024"},
                )
            if resp.status_code in (200, 206):
                return url, tried
        except httpx.HTTPError:
            continue
    return None, tried


def download_criteria(url: str, dest_path: str, *, timeout: float = 90.0) -> int:
    """Download the criteria PDF to dest_path. Returns bytes written."""
    headers = {"User-Agent": _USER_AGENT}
    resp = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
    resp.raise_for_status()
    data = resp.content
    with open(dest_path, "wb") as f:
        f.write(data)
    return len(data)
