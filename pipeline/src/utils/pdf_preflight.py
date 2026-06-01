"""PDF preflight: detect document type and watermark before extraction."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

import fitz

WATERMARK_PATTERNS = [
    r"\bVERS[ÃA]O\s+DE\s+TRABALHO\b",
    r"\bDRAFT\b",
    r"\bSPECIMEN\b",
    r"\bSAMPLE\b",
    r"\bCONFIDENTIAL\b",
    r"\bPROVA\s+DE\s+TRABALHO\b",
]

_CRITERIA_MARKERS = [
    "critérios de classificação",
    "critérios gerais de classificação",
    "critérios específicos de classificação",
    "tópicos de resposta",
    "descritores de desempenho",
]

_EXAM_MARKERS = [
    "duração da prova",
    "tolerância",
    "a prova inclui",
    "para cada resposta",
    "cotações dos itens encontram-se no final",
]


@dataclass
class PDFPreflight:
    document_type: str          # "exam" | "criteria" | "unknown"
    watermark_detected: bool
    watermark_terms: list[str]
    noisy_pages: list[int]
    should_abort: bool
    abort_reason: str | None
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_pdf_preflight(pdf_path: str) -> PDFPreflight:
    doc = fitz.open(pdf_path)
    pages_text: list[tuple[int, str]] = []
    noisy_pages: set[int] = set()

    for i, page in enumerate(doc):
        page_num = i + 1
        text = page.get_text("text") or ""
        pages_text.append((page_num, text))
        for pat in WATERMARK_PATTERNS:
            if re.search(pat, text, flags=re.IGNORECASE):
                noisy_pages.add(page_num)

    doc.close()

    head = "\n".join(t for _, t in pages_text[:3]).lower()
    criteria_score = sum(1 for m in _CRITERIA_MARKERS if m in head)
    exam_score = sum(1 for m in _EXAM_MARKERS if m in head)

    if criteria_score >= 2 and criteria_score > exam_score:
        document_type, confidence = "criteria", 0.95
    elif exam_score >= 2:
        document_type, confidence = "exam", 0.90
    else:
        document_type, confidence = "unknown", 0.50

    terms = [
        pat.replace(r"\b", "").replace(r"\s+", " ").replace("[ÃA]", "Ã/A").replace("\\", "")
        for pat in WATERMARK_PATTERNS
        if any(re.search(pat, text, flags=re.IGNORECASE) for _, text in pages_text)
    ]

    should_abort = document_type == "criteria"
    abort_reason = (
        "O ficheiro parece ser Critérios de Classificação, não o enunciado do exame. "
        "Envia o PDF da prova/enunciado para gerar o quiz."
        if should_abort else None
    )

    return PDFPreflight(
        document_type=document_type,
        watermark_detected=bool(noisy_pages),
        watermark_terms=terms,
        noisy_pages=sorted(noisy_pages),
        should_abort=should_abort,
        abort_reason=abort_reason,
        confidence=confidence,
    )


def clean_watermark_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text
    for pat in WATERMARK_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    lines = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower() in {"versão de trabalho", "versao de trabalho", "draft", "sample", "specimen"}:
            continue
        lines.append(line)
    return "\n".join(lines).strip()
