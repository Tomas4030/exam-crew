from __future__ import annotations

import re


RANGE_RE = re.compile(
    r"\b(?:documentos?|docs?\.?)\s+(?:de\s+)?(\d+)\s*(?:a|ao|-|–|—)\s*(\d+)\b",
    re.IGNORECASE,
)
DOC_LIST_RE = re.compile(
    r"\b(?:documentos?|docs?\.?)\s+((?:\d+\s*(?:,|;|e)\s*)+\d+)\b",
    re.IGNORECASE,
)
SINGLE_DOC_RE = re.compile(r"\b(?:documento|doc\.?)\s+(\d+)\b", re.IGNORECASE)
ALL_DOCS_RE = re.compile(
    r"cada um dos documentos"
    r"|dos documentos apresentados"
    r"|dos dois documentos"
    r"|dos tres documentos"
    r"|dos três documentos"
    r"|dados disponiveis nos documentos"
    r"|dados disponíveis nos documentos"
    r"|a partir dos documentos(?!\s+de\s+\d)",
    re.IGNORECASE,
)


def resolve_doc_numbers(text: str, group_doc_nums: list[int]) -> list[int]:
    """Resolve referenced document numbers in a História source question."""
    nums: set[int] = set()
    value = text or ""

    for start, end in RANGE_RE.findall(value):
        lo, hi = sorted((int(start), int(end)))
        nums.update(range(lo, hi + 1))

    for match in DOC_LIST_RE.finditer(value):
        nums.update(int(n) for n in re.findall(r"\d+", match.group(1)))

    for number in SINGLE_DOC_RE.findall(value):
        nums.add(int(number))

    if not nums and ALL_DOCS_RE.search(value):
        nums.update(group_doc_nums)

    allowed = set(group_doc_nums)
    if allowed:
        nums = {n for n in nums if n in allowed}

    return sorted(nums)


def doc_nums_from_source_refs(refs: list[dict]) -> list[int]:
    nums: set[int] = set()
    for ref in refs or []:
        source_id = str(ref.get("sourceId") or "")
        match = re.search(r"_documento_(\d+)$", source_id)
        if match:
            nums.add(int(match.group(1)))
    return sorted(nums)
