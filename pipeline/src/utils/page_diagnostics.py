from __future__ import annotations

import json
from pathlib import Path


def build_page_diagnostics(page_results: list[dict], extraction: dict) -> list[dict]:
    text_len_by_page = {
        int(p.get("page", 0)): len((p.get("text") or "").strip())
        for p in extraction.get("pages", [])
        if p.get("page")
    }

    diagnostics: list[dict] = []
    for page_data in page_results:
        page = int(page_data.get("page", 0) or 0)
        d = dict(page_data.get("_diagnostics") or {})
        diagnostics.append(
            {
                "page": page,
                "native_text_len": d.get("native_text_len", text_len_by_page.get(page, 0)),
                "prescan_ok": bool(d.get("prescan_ok", False)),
                "prescan_fallback_used": bool(d.get("prescan_fallback_used", False)),
                "prescan_fallback_kind": d.get("prescan_fallback_kind"),
                "page_degraded": bool(d.get("page_degraded", page_data.get("pageType") == "degraded")),
                "questions_found": int(d.get("questions_found", len(page_data.get("questions", [])))),
                "figures_found": int(d.get("figures_found", len(page_data.get("figures", [])))),
                "warnings": d.get("warnings", []),
            }
        )
    return diagnostics


def write_page_diagnostics(output_root: Path, exam_id: str, page_results: list[dict], extraction: dict) -> Path:
    diagnostics = build_page_diagnostics(page_results, extraction)
    debug_dir = output_root / exam_id / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    out_file = debug_dir / "page_diagnostics.json"
    out_file.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_file

