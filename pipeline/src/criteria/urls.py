"""Resolve the official Critérios de Classificação PDF URL for a given exam.

The exam statement carries metadata.year ("2022"), metadata.phase ("1ª Fase")
and metadata.sourceUrl. The criteria PDF lives at a sibling path on
examesnacionais.com.pt, but the filename has changed over the years:

    default (2008-2017, 2020-2025): Portugues_639_Criterios.pdf
    2018:                            Portugues639_Criterios.pdf
    2019:                            Portugues_Criterios.pdf

We derive the {year}-{phase}fase folder and probe the known filename variants,
returning the first that responds 200.
"""
from __future__ import annotations

import re

import httpx

BASE = "https://www.examesnacionais.com.pt/exames-nacionais/12ano"

# Filename variants tried in order. Year-specific overrides come first.
_FILENAME_VARIANTS_BY_YEAR: dict[str, list[str]] = {
    "2018": ["Portugues639_Criterios.pdf", "Portugues_639_Criterios.pdf"],
    "2019": ["Portugues_Criterios.pdf", "Portugues_639_Criterios.pdf"],
}
_DEFAULT_VARIANTS = [
    "Portugues_639_Criterios.pdf",
    "Portugues639_Criterios.pdf",
    "Portugues_Criterios.pdf",
]

_USER_AGENT = "Mozilla/5.0 (ExamCrew criteria pipeline)"


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


def candidate_urls(year: str, phase: int) -> list[str]:
    """All candidate criteria PDF URLs for a year/phase, in probe order."""
    folder = f"{year}-{phase}fase"
    variants = _FILENAME_VARIANTS_BY_YEAR.get(year, _DEFAULT_VARIANTS)
    # de-dup while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for name in variants + _DEFAULT_VARIANTS:
        if name in seen:
            continue
        seen.add(name)
        ordered.append(f"{BASE}/{folder}/{name}")
    return ordered


def resolve_criteria_url(metadata: dict, *, timeout: float = 30.0) -> tuple[str | None, list[str]]:
    """Probe candidate URLs and return (working_url, tried).

    Returns (None, tried) when none respond 200.
    """
    year, phase = parse_year_phase(metadata)
    if not year or not phase:
        return None, []

    tried: list[str] = []
    headers = {"User-Agent": _USER_AGENT}
    for url in candidate_urls(year, phase):
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
