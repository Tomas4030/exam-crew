"""ExamCrew Pipeline v3: PDF → subject detection → pre-scan → per-question extraction → JSON."""
import json
import os
import re
from pathlib import Path

from .tools.pdf_extractor import PDFExtractorTool
from .tools.vision_tool import analyze_exam_pages
from .utils.progress import report_progress
from .utils.validator import validate_and_fix
from .utils.normalizer import normalize
from .utils.math_normalize import math_normalize
from .utils.text_format import apply_text_formatting
from .utils.subjects import detect_subject, is_formula_page
from .utils.source_grouping import apply_source_grouping
from .utils.page_diagnostics import write_page_diagnostics
from .utils.asset_integrity import enforce_asset_integrity
from .utils.question_cleanup import cleanup_history_questions
from .utils.token_usage import get_token_usage


def _find_question_anchor_y(blocks: list[dict], q_number: str) -> float | None:
    pattern = re.compile(rf'^\s*{re.escape(str(q_number))}\.\s+\S')
    for block in blocks:
        text = (block.get("text") or "").strip()
        if pattern.match(text):
            bbox = block.get("bbox") or []
            if len(bbox) == 4:
                return float(bbox[1])
    return None


def _attach_question_regions(questions: list[dict], extraction: dict):
    pages = {p.get("page"): p for p in extraction.get("pages", [])}
    page_heights = {}
    for p in extraction.get("pages", []):
        blocks = p.get("blocks") or []
        max_y = max((float((b.get("bbox") or [0, 0, 0, 0])[3]) for b in blocks), default=0.0)
        page_heights[p.get("page")] = max_y or 842.0

    by_page: dict[int, list[dict]] = {}
    for q in questions:
        page = q.get("sourcePage")
        if isinstance(page, int):
            by_page.setdefault(page, []).append(q)

    for page_num, page_questions in by_page.items():
        page_data = pages.get(page_num, {})
        blocks = page_data.get("blocks") or []
        if not blocks:
            continue

        entries = []
        for q in page_questions:
            q_num = str(q.get("number", ""))
            if not q_num:
                continue
            y = _find_question_anchor_y(blocks, q_num)
            if y is None:
                continue
            entries.append((y, q))

        entries.sort(key=lambda x: x[0])
        page_bottom = page_heights.get(page_num, 842.0)
        for idx, (start_y, q) in enumerate(entries):
            end_y = entries[idx + 1][0] if idx + 1 < len(entries) else page_bottom
            if end_y <= start_y:
                end_y = min(page_bottom, start_y + 180.0)
            q["region"] = {
                "page": page_num,
                "bbox": [0.0, round(start_y, 2), 595.0, round(end_y, 2)],
            }


def _has_scoring_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in (
        "cotação",
        "cotações",
        "cotacao",
        "cotacoes",
        "cotaÃ§",
        "classificação final",
        "classificacao final",
        "pontuação",
        "pontuacao",
        "pontu",
    ))


class ExamProcessingCrew:
    def __init__(self, pdf_path: str, exam_id: str, base_dir: str = None):
        self.pdf_path = pdf_path
        self.exam_id = exam_id
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent.parent
        self.output_dir = self.base_dir / "data" / "output"
        self.extracted_dir = self.base_dir / "data" / "extracted" / exam_id

    def _attach_run_metrics(self, output: dict) -> dict:
        output.setdefault("metadata", {})["tokenUsage"] = get_token_usage()
        return output

    def run(self) -> dict:
        self.extracted_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Preflight: detect document type and watermark
        from .utils.pdf_preflight import run_pdf_preflight
        report_progress("preflight", "Checking PDF type and watermark/noise")
        preflight = run_pdf_preflight(self.pdf_path)
        if preflight.should_abort:
            msg = preflight.abort_reason or "PDF rejected by preflight"
            report_progress("error", msg)
            raise RuntimeError(msg)

        # Step 1: Extract PDF
        report_progress("extract", "Rendering PDF pages as images")
        extractor = PDFExtractorTool()
        extraction_raw = extractor._run(self.pdf_path, str(self.extracted_dir))
        extraction = json.loads(extraction_raw)
        report_progress("extract_done", f"Rendered {extraction['total_pages']} pages, found {len(extraction['assets'])} embedded images")

        # Step 1.5: Detect subject and filter formula pages
        cover_text = extraction["pages"][0]["text"] if extraction["pages"] else ""
        source_url = os.environ.get("EXAM_SOURCE_URL") or ""
        original_filename = os.environ.get("EXAM_ORIGINAL_FILENAME") or Path(self.pdf_path).name
        subject_hint = "\n".join([cover_text, source_url, original_filename])
        subject_key, subject_profile = detect_subject(subject_hint)
        report_progress("subject", f"Detected subject: {subject_key}")

        # Filter out formula/cover pages
        pages_to_process = []
        formula_pages = []
        for page in extraction["pages"]:
            if is_formula_page(page["text"], subject_profile):
                formula_pages.append(page["page"])
            else:
                pages_to_process.append(page)

        if formula_pages:
            report_progress("filter", f"Skipping formula pages: {formula_pages}")

        # Filter out SFI/accessibility duplicate pages
        # Some PDFs contain both the normal version and a "sem figuras" (SFI)
        # version for accessibility. Detect and skip the duplicate.
        sfi_pages = []
        _SFI_MARKERS = ["sem figuras", "entrelinha 1,5", "entrelinha 1.5", "versão sfi",
                        "prova de acessibilidade", "sem imagens"]
        if len(pages_to_process) > 8:
            for page in pages_to_process:
                text_lower = (page.get("text") or "").lower()
                if any(m in text_lower for m in _SFI_MARKERS):
                    sfi_pages.append(page["page"])

            # If SFI pages found, also skip all pages after the first SFI marker
            # (the entire SFI section is a duplicate of the normal exam)
            if sfi_pages:
                first_sfi = min(sfi_pages)
                sfi_pages = [p["page"] for p in pages_to_process if p["page"] >= first_sfi]
                pages_to_process = [p for p in pages_to_process if p["page"] < first_sfi]
                report_progress("filter", f"Skipping accessibility/SFI duplicate pages: {sfi_pages}")

        # Step 1.6: Build DocumentIR and question candidates (passive, debug only)
        try:
            from .core.layout_ir import build_document_ir
            from .core.question_segmenter import segment_questions
            from .core.debug_export import export_debug

            doc_ir = build_document_ir(self.pdf_path, self.exam_id)
            skip_pages = set(formula_pages) | {1}  # skip cover + formulary
            segmentation = segment_questions(doc_ir, skip_pages=skip_pages)
            export_debug(self.output_dir, document_ir=doc_ir, segmentation=segmentation)
            report_progress("layout_ir", f"DocumentIR: {doc_ir.total_pages} pages, {len(segmentation.candidates)} question candidates")
        except Exception as e:
            report_progress("layout_ir", f"DocumentIR generation failed (non-fatal): {e}")

        # Step 1.7: Create table assets from PyMuPDF detection (before vision)
        _ROMAN_HEADERS = {"I", "II", "III", "IV", "V"}
        for page_info in pages_to_process:
            for table in page_info.get("tables", []):
                bbox = table.get("bbox")
                rows = table.get("rows", [])
                if not rows or len(rows) < 2 or not bbox:
                    continue
                page_num = page_info["page"]
                header = [h.strip() if h else "" for h in rows[0]]
                # Classify: options table (I/II/III/IV) vs data table
                is_options = all(h in _ROMAN_HEADERS for h in header if h)
                table_id = f"tabela_p{page_num}" if not is_options else f"tabela_opcoes_p{page_num}"
                # Avoid duplicates
                if any(a["id"] == table_id for a in extraction["assets"]):
                    continue
                extraction["assets"].append({
                    "id": table_id,
                    "path": None,
                    "page": page_num,
                    "bbox": {"x": round(bbox[0]), "y": round(bbox[1]),
                             "width": round(bbox[2] - bbox[0]), "height": round(bbox[3] - bbox[1])},
                    "type": "table",
                    "columns": header,
                    "rows": [{header[i]: (row[i] or "").strip() for i in range(len(header)) if i < len(row)} for row in rows[1:]],
                    "_is_options_table": is_options,
                })

        # Step 2: Analyze pages (pre-scan + per-question)
        report_progress("vision", f"Analyzing {len(pages_to_process)} pages with Qwen3-VL")
        page_results = analyze_exam_pages(pages_to_process)
        try:
            diag_file = write_page_diagnostics(self.output_dir, self.exam_id, page_results, extraction)
            report_progress("diagnostics", f"Page diagnostics saved: {diag_file}")
        except Exception as diag_err:
            report_progress("diagnostics", f"Failed to write page diagnostics (non-fatal): {diag_err}")

        # Step 2.5: Dedicated scoring extraction from last page
        # Try vision first, then text fallback. Also collect any scoring from pre-scan.
        from .tools.vision_tool import _extract_scoring, _call_text
        scoring_collected = []

        # Collect scoring already found during pre-scan
        for pr in page_results:
            if pr.get("scoring"):
                scoring_collected.extend(pr["scoring"])

        # Prefer processed pages over the raw PDF tail. Older exams can end with
        # technical/accessibility pages that are not part of the statement.
        if not scoring_collected:
            scoring_pages = list(reversed(pages_to_process[-3:] or extraction["pages"][-3:]))
            for scoring_page in scoring_pages:
                scoring = _extract_scoring(scoring_page["page_image_path"], scoring_page["page"])
                if scoring:
                    scoring_collected = scoring
                    break

            if not scoring_collected:
                for scoring_page in scoring_pages:
                    scoring_text = scoring_page.get("text", "")
                    if not _has_scoring_text(scoring_text):
                        continue
                    text_prompt = f"""Extract scoring from this text. Each line has a question number and points.
Respond ONLY with JSON array: [{{"question": "1", "points": 12}}]

Text:
{scoring_text[:3000]}"""
                    content = _call_text(text_prompt, 512)
                    if content:
                        import re as _re
                        try:
                            scoring_collected = json.loads(content)
                        except json.JSONDecodeError:
                            match = _re.search(r'\[[\s\S]*\]', content)
                            if match:
                                try:
                                    scoring_collected = json.loads(match.group())
                                except json.JSONDecodeError:
                                    pass
                    if scoring_collected:
                        break

        # If pre-scan didn't find scoring, do dedicated extraction on last page
        if not scoring_collected:
            last_page = extraction["pages"][-1]
            scoring = _extract_scoring(last_page["page_image_path"], last_page["page"])
            if scoring:
                scoring_collected = scoring
            else:
                # Fallback: try text-based extraction from last page
                last_text = last_page.get("text", "")
                if last_text and ("cotaç" in last_text.lower() or "pontu" in last_text.lower()):
                    text_prompt = f"""Extract scoring from this text. Each line has a question number and points.
Respond ONLY with JSON array: [{{"question": "1", "points": 12}}]

Text:
{last_text[:3000]}"""
                    content = _call_text(text_prompt, 512)
                    if content:
                        import re as _re
                        try:
                            scoring_collected = json.loads(content)
                        except json.JSONDecodeError:
                            match = _re.search(r'\[[\s\S]*\]', content)
                            if match:
                                try:
                                    scoring_collected = json.loads(match.group())
                                except json.JSONDecodeError:
                                    pass

        if scoring_collected:
            # Ensure scoring is in page_results for the assembler
            # Remove any existing scoring entries to avoid duplicates
            page_results = [pr for pr in page_results if not pr.get("scoring")]
            page_results.append({"page": extraction["total_pages"], "pageType": "scoring", "questions": [], "figures": [], "scoring": scoring_collected})
            report_progress("scoring", f"Extracted {len(scoring_collected)} scoring entries")

        # Step 3: Assemble
        report_progress("assemble", "Building structured output")
        self._last_page_results = page_results  # Store for retry scoring re-application
        extraction["_processed_pages"] = pages_to_process
        output = self._assemble_output(extraction, page_results, subject_profile)
        output["metadata"]["subject"] = subject_key.replace("_", " ").title() if subject_key != "unknown" else None
        output["metadata"]["sourceUrl"] = source_url or None
        output["metadata"]["originalFilename"] = original_filename or None
        url_match = re.search(r"/(20\d{2})-([12])fase/", source_url, re.IGNORECASE)
        if url_match:
            output["metadata"]["year"] = url_match.group(1)
            output["metadata"]["phase"] = f"{url_match.group(2)}ª Fase"
        output["metadata"]["formula_pages"] = formula_pages
        output["metadata"]["preflight"] = preflight.to_dict()

        # Fallback textual se a visão/assemble não extraiu perguntas
        if not output.get("questions"):
            from .utils.text_question_fallback import extract_questions_from_text_pages, repair_corrupt_questions_from_text

            fallback_questions = extract_questions_from_text_pages(extraction, subject_profile)

            if fallback_questions:
                output["questions"] = fallback_questions
                output.setdefault("warnings", []).append({
                    "type": "text_fallback_used",
                    "message": f"Vision/assemble returned 0 questions; recovered {len(fallback_questions)} questions from extracted text.",
                })
                output["needsHumanReview"] = True
                report_progress("retry", f"Recovered {len(fallback_questions)} questions using text fallback")
            else:
                output.setdefault("warnings", []).append({
                    "type": "empty_output",
                    "message": "Vision/assemble returned 0 questions and text fallback recovered 0 questions.",
                })
                output["status"] = "partial_failed"
                output["needsHumanReview"] = True

            repaired_text = repair_corrupt_questions_from_text(output, extraction)
            if repaired_text:
                report_progress("normalize", f"Repaired {repaired_text} corrupted question text(s) from native PDF text")

            reapplied_points = self._reapply_page_result_scoring(output, page_results)
            if subject_profile and subject_profile.get("has_source_grouping"):
                reapplied_points += self._apply_scoring_entries_to_output(
                    output,
                    self._parse_history_scoring(extraction),
                    overwrite=True,
                )
            if reapplied_points:
                report_progress("scoring", f"Applied scoring to {reapplied_points} text-fallback question(s)")
        else:
            from .utils.text_question_fallback import extract_questions_from_text_pages, repair_corrupt_questions_from_text

            fallback_questions = extract_questions_from_text_pages(extraction, subject_profile)
            existing = {
                (q.get("sourcePage"), str(q.get("number", "")).strip())
                for q in output.get("questions", [])
            }
            recovered = []
            for q in fallback_questions:
                key = (q.get("sourcePage"), str(q.get("number", "")).strip())
                if key in existing:
                    continue
                recovered.append(q)
                existing.add(key)

            if recovered:
                output.setdefault("questions", []).extend(recovered)
                output["questions"].sort(key=lambda q: (
                    q.get("sourcePage") or 999,
                    int(str(q.get("number") or "999").split(".", 1)[0]) if str(q.get("number") or "").split(".", 1)[0].isdigit() else 999,
                    str(q.get("number") or ""),
                ))
                output.setdefault("warnings", []).append({
                    "type": "partial_text_fallback_used",
                    "message": f"Recovered {len(recovered)} question(s) missing from vision output using extracted PDF text.",
                })
                output["needsHumanReview"] = True
                report_progress("retry", f"Recovered {len(recovered)} missing question(s) using text fallback")

            repaired_text = repair_corrupt_questions_from_text(output, extraction)
            if repaired_text:
                report_progress("normalize", f"Repaired {repaired_text} corrupted question text(s) from native PDF text")

            reapplied_points = self._reapply_page_result_scoring(output, page_results)
            if subject_profile and subject_profile.get("has_source_grouping"):
                reapplied_points += self._apply_scoring_entries_to_output(
                    output,
                    self._parse_history_scoring(extraction),
                    overwrite=True,
                )
            if reapplied_points:
                report_progress("scoring", f"Applied scoring to {reapplied_points} text-fallback question(s)")

        # Step 3.2: Extract table data for tables without rows
        from .tools.vision_tool import _extract_table_data
        for asset in output.get("assets", []):
            if asset.get("type") == "table" and not asset.get("rows"):
                page_num = asset.get("page")
                page_info = next((p for p in extraction["pages"] if p["page"] == page_num), None)
                if page_info:
                    report_progress("table", f"Extracting table data from page {page_num}")
                    table_data = _extract_table_data(page_info["page_image_path"], page_num)
                    if table_data:
                        asset["columns"] = table_data.get("columns", [])
                        asset["rows"] = table_data.get("rows", [])
                        report_progress("table", f"Extracted {len(asset['rows'])} rows from {asset['id']}")

        # Step 3.3: Detect tables via PyMuPDF for multi_blank_choice questions
        import fitz as _fitz
        pdf_doc = _fitz.open(self.pdf_path)
        for q in output.get("questions", []):
            if q.get("type") != "multi_blank_choice" or q.get("blanks"):
                continue
            # This question was marked multi_blank_choice but blanks weren't extracted
            page_num = q.get("sourcePage", 0)
            if page_num < 1 or page_num > pdf_doc.page_count:
                continue
            page = pdf_doc[page_num - 1]
            tables = page.find_tables().tables
            if len(tables) >= 2:
                # Last table is likely the options table (I/II/III/IV columns)
                opts_table = tables[-1]
                rows = opts_table.extract()
                if rows and len(rows[0]) >= 2:
                    # First row = headers (I, II, III, IV), rest = options
                    headers = [h.strip() if h else "" for h in rows[0]]
                    blanks = []
                    for col_idx, header in enumerate(headers):
                        if not header:
                            continue
                        options = []
                        for row_idx, row in enumerate(rows[1:], 1):
                            cell = row[col_idx].strip() if col_idx < len(row) and row[col_idx] else ""
                            if cell:
                                letter = chr(ord('a') + row_idx - 1)
                                options.append({"letter": letter, "text": cell})
                        if options:
                            blanks.append({"number": header, "options": options})
                    if blanks:
                        q["blanks"] = blanks
                        report_progress("table", f"Extracted {len(blanks)} blanks for Q{q['number']} from PyMuPDF table")
        pdf_doc.close()

        # Step 3.5: Source grouping (for History, Portuguese, etc.)
        report_progress("source_grouping", "Detecting source/document pages")
        output = apply_source_grouping(output, subject_profile, extraction)

        # Step 3.5b: Normalize (deterministic corrections)
        report_progress("normalize", "Applying deterministic corrections")
        output = normalize(output, extraction)

        # Step 3.7: Crop assets from rendered pages
        from .utils.cropper import crop_assets
        report_progress("crop", "Cropping assets from page images")
        crop_output_dir = self.output_dir / self.exam_id
        output["_pdf_path"] = self.pdf_path
        output = crop_assets(output, extraction, crop_output_dir)
        output.pop("_pdf_path", None)

        # Step 3.7b: Re-normalize after crops (catches cloned table assets)
        output = normalize(output, extraction)

        # Step 3.7c: Profile-based normalizer (discipline-specific rules)
        from .normalizers import normalize_by_profile
        output = normalize_by_profile(output, extraction, subject_profile)

        # Step 3.8: Math normalization (LaTeX, textQuality)
        report_progress("math_normalize", "Normalizing mathematical text")
        output = math_normalize(output, extraction)

        # Step 3.9: Clean statementLatex — remove tabular when table is already an asset
        for q in output.get("questions", []):
            if q.get("tableRefs") and q.get("statementLatex"):
                q["statementLatex"] = re.sub(
                    r'\\begin\{center\}[\s\S]*?\\end\{center\}', '', q["statementLatex"]
                )
                q["statementLatex"] = re.sub(
                    r'\\begin\{tabular\}[\s\S]*?\\end\{tabular\}', '', q["statementLatex"]
                )
                q["statementLatex"] = q["statementLatex"].strip()

        # Step 4: Validate
        report_progress("validate", "Running post-processing validation")
        output = validate_and_fix(output, extraction)

        # Step 4.5: Targeted retry for missing questions
        missing_q_warnings = [w for w in output.get("warnings", []) if w["type"] == "missing_question"]
        if missing_q_warnings and pages_to_process:
            report_progress("retry", f"Retrying extraction for {len(missing_q_warnings)} missing question(s)")
            output = self._targeted_retry(output, extraction, pages_to_process, missing_q_warnings)

        # Step 4.7: Remove deterministic duplicates/source excerpts before final audit.
        output = cleanup_history_questions(output)
        output = validate_and_fix(output, extraction)

        # Step 4.9: Deterministic readable line breaks for frontend display
        # Runs last so validate/retry changes are captured. Overwrites statement
        # with formatted version; original preserved in statementRaw.
        output = apply_text_formatting(output)

        # Step 4.92: remove broken asset/media references before final save
        output = enforce_asset_integrity(output, self.output_dir)

        # Step 4.94: Subject-specific audit gate before any "done" status.
        from .utils.history_audit import apply_history_audit_gate
        max_audit_retries = 2
        history_audit_issues = []
        history_audit_summary = {"verdict": "SKIPPED"}
        for audit_attempt in range(max_audit_retries + 1):
            report_progress("audit", f"Running Historia quality audit (attempt {audit_attempt + 1})")
            output, history_audit_issues, history_audit_summary = apply_history_audit_gate(
                output,
                self.output_dir / self.exam_id,
            )
            if history_audit_summary.get("verdict") != "FAIL":
                break
            if audit_attempt >= max_audit_retries:
                break

            retryable = self._retryable_history_audit_issues(history_audit_issues)
            if not retryable:
                break

            report_progress(
                "audit_retry",
                f"Retrying deterministic repairs for {len(retryable)} Historia audit issue(s)",
            )
            output = self._repair_history_audit_issues(
                output,
                extraction,
                subject_profile,
                retryable,
            )
            output.setdefault("metadata", {})["historyAuditRetries"] = audit_attempt + 1

        if history_audit_summary.get("verdict") == "FAIL":
            out_file = self.output_dir / f"{self.exam_id}.json"
            output = self._attach_run_metrics(output)
            out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            top = history_audit_issues[0].code if history_audit_issues else "UNKNOWN"
            message = (
                "Historia audit failed before completion: "
                f"{history_audit_summary.get('blocker', 0)} blocker(s), "
                f"{history_audit_summary.get('high', 0)} high issue(s). Top issue: {top}."
            )
            report_progress("error", message)
            raise RuntimeError(message)

        portuguese_audit_issues = []
        portuguese_audit_summary = {"verdict": "SKIPPED"}
        if subject_profile and "portugues" in subject_profile.get("normalizers", []):
            from .utils.portuguese_audit import apply_portuguese_audit_gate

            report_progress("audit", "Running Portuguese quality audit")
            output, portuguese_audit_issues, portuguese_audit_summary = apply_portuguese_audit_gate(
                output,
                self.output_dir / self.exam_id,
            )

        if portuguese_audit_summary.get("verdict") == "FAIL":
            out_file = self.output_dir / f"{self.exam_id}.json"
            output = self._attach_run_metrics(output)
            out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            top = portuguese_audit_issues[0].code if portuguese_audit_issues else "UNKNOWN"
            message = (
                "Portuguese audit failed before completion: "
                f"{portuguese_audit_summary.get('blocker', 0)} blocker(s), "
                f"{portuguese_audit_summary.get('high', 0)} high issue(s). Top issue: {top}."
            )
            report_progress("error", message)
            raise RuntimeError(message)

        # Step 4.95: Final quality gate
        question_count = len(output.get("questions") or [])

        if question_count == 0:
            output.setdefault("warnings", []).append({
                "type": "empty_questions",
                "severity": "critical",
                "message": "Pipeline completed but extracted 0 questions.",
            })
            output["status"] = "partial_failed"
            output["needsHumanReview"] = True

            out_file = self.output_dir / f"{self.exam_id}.json"
            output = self._attach_run_metrics(output)
            out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

            report_progress(
                "error",
                "O pipeline terminou, mas não extraiu perguntas. JSON guardado como partial_failed."
            )

            raise RuntimeError("Pipeline completed with 0 questions")

        # Step 5: Save
        out_file = self.output_dir / f"{self.exam_id}.json"
        output = self._attach_run_metrics(output)
        out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        report_progress("done", f"Saved to {out_file}")
        return output

    def _retryable_history_audit_issues(self, issues: list) -> list:
        retryable_codes = {
            "GROUP_NUMBER_GAP",
            "CORRUPT_TEXT",
            "MULTIPLE_CHOICE_WITHOUT_OPTIONS",
            "MATCHING_WITHOUT_COLUMNS",
            "ORDERING_WITHOUT_ITEMS",
            "MULTIBLANK_WITHOUT_OPTIONS",
            "MULTIBLANK_MISCLASSIFIED",
            "CHOICE_LIKE_OPEN_ANSWER",
            "OPEN_ANSWER_SHOULD_BE_SELECTION",
            "BROKEN_SOURCE_REF",
            "BROKEN_CHILD_REF",
            "CROSS_GROUP_SOURCE_REF",
            "SOURCE_REFS_WITHOUT_MEDIA",
            "MENTIONS_SOURCE_WITHOUT_REF",
            "MISSING_EXPECTED_DOCUMENTS",
            "MISSING_MEDIA_FILE",
            "MISSING_SOURCE_CROP_FILE",
            "MISSING_CHILD_CROP_FILE",
            "DUPLICATE_SOURCE_CROPS",
            "SUSPECT_CROP_TOO_SMALL",
        }
        return [issue for issue in issues if getattr(issue, "code", "") in retryable_codes]

    def _repair_history_audit_issues(
        self,
        output: dict,
        extraction: dict,
        subject_profile: dict,
        issues: list,
    ) -> dict:
        codes = {getattr(issue, "code", "") for issue in issues}
        output.setdefault("metadata", {}).pop("historyAudit", None)

        if "CORRUPT_TEXT" in codes:
            from .utils.text_question_fallback import repair_corrupt_questions_from_text
            repaired = repair_corrupt_questions_from_text(output, extraction)
            if repaired:
                report_progress("audit_retry", f"Repaired {repaired} corrupt text item(s)")

        if "GROUP_NUMBER_GAP" in codes:
            from .utils.text_question_fallback import extract_questions_from_text_pages
            fallback_questions = extract_questions_from_text_pages(extraction, subject_profile)
            existing = {
                (q.get("groupId") or "", str(q.get("number") or "").strip(), q.get("sourcePage"))
                for q in output.get("questions", [])
            }
            recovered = []
            for q in fallback_questions:
                key = (q.get("groupId") or "", str(q.get("number") or "").strip(), q.get("sourcePage"))
                if key in existing:
                    continue
                recovered.append(q)
                existing.add(key)
            if recovered:
                output.setdefault("questions", []).extend(recovered)
                output["questions"].sort(key=lambda q: (
                    q.get("sourcePage") or 999,
                    q.get("groupId") or "",
                    int(str(q.get("number") or "999").split(".", 1)[0]) if str(q.get("number") or "").split(".", 1)[0].isdigit() else 999,
                    str(q.get("number") or ""),
                ))
                output.setdefault("warnings", []).append({
                    "type": "history_audit_retry_recovered_questions",
                    "message": f"Recovered {len(recovered)} question(s) from text fallback during audit retry.",
                })
                report_progress("audit_retry", f"Recovered {len(recovered)} missing question(s)")

        needs_structure_pass = bool(codes & {
            "MULTIPLE_CHOICE_WITHOUT_OPTIONS",
            "MATCHING_WITHOUT_COLUMNS",
            "ORDERING_WITHOUT_ITEMS",
            "MULTIBLANK_WITHOUT_OPTIONS",
            "MULTIBLANK_MISCLASSIFIED",
            "CHOICE_LIKE_OPEN_ANSWER",
            "OPEN_ANSWER_SHOULD_BE_SELECTION",
            "BROKEN_SOURCE_REF",
            "BROKEN_CHILD_REF",
            "CROSS_GROUP_SOURCE_REF",
            "SOURCE_REFS_WITHOUT_MEDIA",
            "MENTIONS_SOURCE_WITHOUT_REF",
            "MISSING_EXPECTED_DOCUMENTS",
            "MISSING_MEDIA_FILE",
            "MISSING_SOURCE_CROP_FILE",
            "MISSING_CHILD_CROP_FILE",
            "DUPLICATE_SOURCE_CROPS",
            "SUSPECT_CROP_TOO_SMALL",
            "GROUP_NUMBER_GAP",
        })
        if needs_structure_pass:
            output = apply_source_grouping(output, subject_profile, extraction)
            output = normalize(output, extraction)

            from .normalizers import normalize_by_profile
            output = normalize_by_profile(output, extraction, subject_profile)

            from .utils.cropper import crop_assets
            crop_output_dir = self.output_dir / self.exam_id
            output["_pdf_path"] = self.pdf_path
            output = crop_assets(output, extraction, crop_output_dir)
            output.pop("_pdf_path", None)

            output = normalize(output, extraction)
            output = normalize_by_profile(output, extraction, subject_profile)
            output = cleanup_history_questions(output)
            output = validate_and_fix(output, extraction)
            output = apply_text_formatting(output)
            output = enforce_asset_integrity(output, self.output_dir)

        return output

    def _targeted_retry(self, output: dict, extraction: dict, pages_to_process: list[dict], missing_warnings: list[dict]) -> dict:
        """Re-extract only pages where missing questions are expected."""
        from .tools.vision_tool import _extract_question, _prescan_page
        import time

        # Determine which question numbers are missing
        missing_nums = set()
        for w in missing_warnings:
            # Extract number from message like "Question 1 not found"
            m = re.search(r'Question (\d+)', w["message"])
            if m:
                missing_nums.add(int(m.group(1)))

        if not missing_nums:
            return output

        # Determine which pages to retry: pages adjacent to where the missing questions should be
        existing_qs = output.get("questions", [])
        page_for_q: dict[int, int] = {}
        for q in existing_qs:
            if q["number"].isdigit():
                page_for_q[int(q["number"])] = q["sourcePage"]

        retry_pages = set()
        for mq in missing_nums:
            # Find the page of the next existing question
            next_q = min((n for n in page_for_q if n > mq), default=None)
            prev_q = max((n for n in page_for_q if n < mq), default=None)
            if next_q:
                retry_pages.add(page_for_q[next_q])
            if prev_q:
                retry_pages.add(page_for_q[prev_q])

        # Get page data for retry pages
        retry_page_data = [p for p in pages_to_process if p["page"] in retry_pages]
        if not retry_page_data:
            return output

        report_progress("retry", f"Re-scanning pages {sorted(retry_pages)} for questions {sorted(missing_nums)}")

        new_questions_found = []
        for page_info in retry_page_data:
            page_num = page_info["page"]
            image_path = page_info["page_image_path"]
            page_text = page_info.get("text", "")

            # Try to extract each missing question directly
            for mq in sorted(missing_nums):
                # VALIDATE: only attempt if the question number actually appears on this page
                if page_text and not re.search(rf'(?:^|\n)\s*{mq}\.\s', page_text):
                    continue  # Question number not on this page — don't hallucinate

                q_data = _extract_question(image_path, page_num, str(mq), extraction["total_pages"])
                time.sleep(2)

                # Validate the result: reject if statement is suspiciously short or generic
                if q_data and q_data.get("statement"):
                    stmt = q_data["statement"]
                    # Reject hallucinated responses
                    if len(stmt) < 15 or "not on this page" in stmt.lower():
                        q_data = None

                if q_data and q_data.get("statement"):
                    q_data["_retry_page"] = page_num
                    new_questions_found.append(q_data)
                    report_progress("retry", f"Found Q{mq} on page {page_num} (retry)")

        # Fallback 3: if vision failed for any question, try text-based extraction
        still_missing = missing_nums - {int(q.get("number", 0)) for q in new_questions_found if q.get("number", "").isdigit()}
        if still_missing:
            for page_info in retry_page_data:
                page_num = page_info["page"]
                page_text = page_info.get("text", "")
                if not page_text:
                    continue
                for mq in sorted(still_missing):
                    q_data = self._extract_question_from_text(page_text, mq)
                    if q_data:
                        q_data["_retry_page"] = page_num
                        new_questions_found.append(q_data)
                        still_missing.discard(mq)
                        report_progress("retry", f"Found Q{mq} on page {page_num} (text fallback)")

        # If we found new questions, re-assemble with them injected
        if new_questions_found:
            # Inject into page_results and re-assemble
            for q_data in new_questions_found:
                page_num = q_data.pop("_retry_page")
                # Find or create page entry
                found_page = False
                for pr in output.get("_page_results", []):
                    if pr.get("page") == page_num:
                        pr.setdefault("questions", []).append(q_data)
                        found_page = True
                        break
                if not found_page:
                    # Add directly to questions list
                    number = str(q_data.get("number", ""))
                    q_id = f"q{number.replace('.', '_')}"
                    stmt = str(q_data.get("statement", "") or "")
                    math_indicators = ['²', '³', '√', '∫', 'π', 'θ', '≥', '≤', '∈', '∞', 'lim', 'sen', 'cos', 'tg', 'log', 'ln', '→', 'f(x)', 'g(x)']
                    is_math = q_data.get("mathHeavy", False) or any(ind in stmt for ind in math_indicators)
                    calc = q_data.get("calculatorAllowed", True)
                    if "sem recorrer à calculadora" in stmt.lower():
                        calc = False

                    new_q = {
                        "questionId": q_id,
                        "number": number,
                        "type": q_data.get("type", "open_answer"),
                        "sourcePage": page_num,
                        "statement": stmt,
                        "rawText": q_data.get("rawText"),
                        "blanks": q_data.get("blanks"),
                        "options": q_data.get("options", []),
                        "maxSelections": q_data.get("maxSelections"),
                        "imageRefs": [],
                        "tableRefs": [],
                        "assetRefs": [],
                        "visualDependency": False,
                        "confidence": 0.85,
                        "needsHumanReview": False,
                        "warnings": [{"type": "retry_extracted", "message": f"Q{number} extracted on retry pass"}],
                        "parentQuestion": None,
                        "subQuestions": [],
                        "mathHeavy": is_math,
                        "hasGraph": False,
                        "hasDiagram": False,
                        "hasTable": False,
                        "calculatorAllowed": calc,
                        "points": q_data.get("points"),
                    }
                    output["questions"].append(new_q)

            # Re-sort and re-validate
            def sort_key(q):
                parts = q["number"].split(".")
                try:
                    return (q["sourcePage"], int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
                except ValueError:
                    return (q["sourcePage"], 999, 0)
            output["questions"].sort(key=sort_key)

            # Re-apply scoring to new questions that missed the first pass
            scoring_entries = []
            for pr in self._last_page_results:
                for score in pr.get("scoring", []):
                    q_num = str(score.get("question") or score.get("number") or "").strip().rstrip(".")
                    pts = score.get("points") or score.get("cotacao") or score.get("score")
                    if q_num and pts is not None:
                        try:
                            pts = int(float(str(pts)))
                        except (ValueError, TypeError):
                            continue
                        if pts > 0:
                            scoring_entries.append({"question": q_num, "points": pts})

            for entry in scoring_entries:
                q_num = entry["question"]
                pts = entry["points"]
                for q in output["questions"]:
                    if q["number"] == q_num and q.get("points") is None:
                        q["points"] = pts
                        break

            # Clear all warnings — validate will regenerate them fresh
            output["warnings"] = []
            for q in output["questions"]:
                q["warnings"] = [w for w in q.get("warnings", []) if w.get("type") == "retry_extracted"]

            # Re-run normalize + validate from scratch
            output = normalize(output, extraction)
            output = validate_and_fix(output, extraction)

        return output

    def _reapply_page_result_scoring(self, output: dict, page_results: list[dict]) -> int:
        """Apply scoring collected before later text-fallback questions were added."""
        scoring_entries = []
        for pr in page_results or []:
            for score in pr.get("scoring", []) or []:
                q_num = str(score.get("question") or score.get("number") or "").strip().rstrip(".")
                pts = score.get("points") or score.get("cotacao") or score.get("score")
                group = str(score.get("group") or score.get("groupId") or "").strip()
                if not q_num or pts is None:
                    continue
                try:
                    pts = int(float(str(pts)))
                except (ValueError, TypeError):
                    continue
                if pts > 0:
                    scoring_entries.append({"question": q_num, "points": pts, "group": group})

        return self._apply_scoring_entries_to_output(output, scoring_entries, overwrite=False)

    def _apply_scoring_entries_to_output(self, output: dict, scoring_entries: list[dict], overwrite: bool = False) -> int:
        """Apply group-aware scoring entries to output questions."""
        applied = 0
        questions = output.get("questions", []) or []
        for entry in scoring_entries:
            q_num = entry["question"]
            pts = entry["points"]
            group = entry.get("group", "")
            candidates = [
                q for q in questions
                if str(q.get("number", "")).strip() == q_num and (overwrite or q.get("points") is None)
            ]
            if group:
                grouped = [
                    q for q in candidates
                    if group.lower() in str(q.get("groupId") or q.get("group") or "").lower()
                ]
                candidates = grouped or candidates
            if candidates:
                for q in candidates[:1]:
                    if q.get("points") != pts:
                        q["points"] = pts
                        applied += 1

        return applied

    def _extract_question_from_text(self, page_text: str, q_number: int) -> dict | None:
        """Extract a question from raw page text using regex. Last-resort fallback."""
        # Find the question block: starts with "N." and ends before next question or end
        pattern = rf'(?:^|\n)\s*{q_number}\.\s*(.*?)(?=\n\s*{q_number + 1}\.\s|\Z)'
        match = re.search(pattern, page_text, re.DOTALL)
        if not match:
            return None

        block = match.group(1).strip()
        if len(block) < 10:
            return None

        # Try to detect multiple choice options
        options = []
        opt_pattern = r'\(([A-D])\)\s*(.+?)(?=\([A-D]\)|$)'
        opt_matches = re.findall(opt_pattern, block, re.DOTALL)
        if opt_matches:
            for letter, text in opt_matches:
                options.append({"letter": letter, "text": text.strip()})
            # Statement is everything before first option
            stmt_end = block.find(f"({opt_matches[0][0]})")
            statement = block[:stmt_end].strip() if stmt_end > 0 else block
            q_type = "multiple_choice"
        else:
            statement = block
            q_type = "open_answer"

        return {
            "number": str(q_number),
            "type": q_type,
            "statement": statement,
            "options": options,
            "mathHeavy": any(c in statement for c in '²³√∫πθ≥≤∈∞'),
            "calculatorAllowed": None,
            "points": None,
        }

    def _parse_history_scoring(self, extraction: dict) -> list[dict]:
        """Parse scoring table from last page for History exams.

        Handles vertical table format where each cell is on its own line:
        I\nII\nII\n...\n1.\n1.\n2.\n...\n13\n14\n20\n...
        """
        pages = extraction.get("_processed_pages") or extraction.get("pages", [])
        if not pages:
            return []

        scoring_text = ""
        for p in reversed(pages[-4:]):
            text = p.get("text", "")
            if _has_scoring_text(text):
                scoring_text = text
                break
            if "cotaç" in text.lower():
                scoring_text = text
                break
        if not scoring_text:
            return []

        structured_results = self._parse_history_scoring_lines(scoring_text)
        if structured_results:
            return structured_results

        results = []
        roman_map = {"I": "grupo_i", "II": "grupo_ii", "III": "grupo_iii", "IV": "grupo_iv"}
        lines = [l.strip() for l in scoring_text.split("\n") if l.strip()]

        # Strategy: collect consecutive roman numerals, then items, then points
        # The table appears as vertical columns: groups block, items block, points block
        groups_seq = []
        items_seq = []
        points_seq = []

        i = 0
        # Find start: look for "Grupo" or "Subtotal" header before the roman numerals
        while i < len(lines):
            if lines[i].lower() in ("grupo", "subtotal", "grupo subtotal"):
                i += 1
                break
            i += 1

        # Skip any non-roman lines (e.g. "Subtotal")
        while i < len(lines) and lines[i] not in roman_map:
            i += 1

        # Collect roman numerals
        while i < len(lines):
            line = lines[i]
            if line in roman_map:
                groups_seq.append(line)
                i += 1
            else:
                break

        # Collect item numbers (N. format)
        while i < len(lines):
            line = lines[i]
            m = re.match(r'^(\d+)\.$', line)
            if m:
                items_seq.append(m.group(1))
                i += 1
            else:
                break

        # Skip "Cotação (em pontos)" header
        while i < len(lines) and not re.match(r'^\d+$', lines[i]):
            i += 1

        # Collect points
        while i < len(lines):
            line = lines[i]
            if re.match(r'^\d+$', line):
                val = int(line)
                if 5 <= val <= 200:
                    points_seq.append(val)
                else:
                    break
                i += 1
            else:
                break

        # Align the three sequences
        n = min(len(groups_seq), len(items_seq), len(points_seq))
        if n >= 3:
            for k in range(n):
                gid = roman_map.get(groups_seq[k])
                if gid:
                    results.append({"question": items_seq[k], "points": points_seq[k], "group": gid})

        opt_match = re.search(r'(\d+)\s*[Ã×x]\s*(\d+)\s*pontos', scoring_text, re.IGNORECASE)
        optional_points = int(opt_match.group(2)) if opt_match else 13

        # Also parse optional items section (e.g. "Grupo I\n2.\nGrupo III\n2.\n5.\n...")
        if "Destes" in scoring_text or "contribuem" in scoring_text:
            optional_group = None
            for j in range(i, len(lines)):
                line = lines[j]
                gm = re.match(r'^Grupo\s+(I{1,3}V?|IV)$', line, re.IGNORECASE)
                if gm:
                    optional_group = roman_map.get(gm.group(1))
                    continue
                item_m = re.match(r'^(\d+)\.$', line)
                if item_m and optional_group:
                    results.append({"question": item_m.group(1), "points": optional_points, "group": optional_group})

        return results

    def _parse_history_scoring_lines(self, scoring_text: str) -> list[dict]:
        """Parse modern and optional-item Historia scoring tables from native PDF text."""
        roman_map = {"I": "grupo_i", "II": "grupo_ii", "III": "grupo_iii", "IV": "grupo_iv"}
        lines = [re.sub(r"\s+", " ", line).strip() for line in (scoring_text or "").splitlines()]
        lines = [line for line in lines if line]

        def roman_token(value: str) -> str:
            value = re.sub(r"^Grupo\s+", "", value, flags=re.IGNORECASE)
            value = re.sub(r"[^ivIV]", "", value).upper()
            return value if value in roman_map else ""

        def item_token(value: str) -> str:
            match = re.match(r"^(\d{1,2})\.$", value)
            return match.group(1) if match else ""

        def point_token(value: str) -> int | None:
            if not re.match(r"^\d{1,3}$", value):
                return None
            val = int(value)
            return val if 1 <= val <= 100 else None

        results: list[dict] = []

        # Standard vertical layout:
        # Grupo / Item / Cotação -> I -> 1. 2. 3. -> 10 10 10 subtotal -> II ...
        i = 0
        while i < len(lines):
            group = roman_token(lines[i])
            if not group:
                i += 1
                continue
            gid = roman_map[group]
            j = i + 1
            items: list[str] = []
            while j < len(lines):
                item = item_token(lines[j])
                if not item:
                    break
                items.append(item)
                j += 1
            if not items:
                i += 1
                continue
            points: list[int] = []
            while j < len(lines):
                point = point_token(lines[j])
                if point is None:
                    break
                points.append(point)
                j += 1
            if len(points) >= len(items):
                for item, point in zip(items, points[:len(items)]):
                    results.append({"question": item, "points": point, "group": gid})
                i = j
                continue
            i += 1

        if len(results) >= 8:
            return results

        # Older optional layout:
        # mandatory columns followed by "Destes N itens ... 7 x 18 pontos".
        old_results: list[dict] = []
        start = next((idx for idx, line in enumerate(lines) if line.lower() == "grupo"), -1)
        if start >= 0:
            idx = start + 1
            while idx < len(lines) and not roman_token(lines[idx]):
                idx += 1
            groups: list[str] = []
            while idx < len(lines):
                token = roman_token(lines[idx])
                if not token:
                    break
                groups.append(token)
                idx += 1
            items: list[str] = []
            while idx < len(lines):
                item = item_token(lines[idx])
                if not item:
                    break
                items.append(item)
                idx += 1
            while idx < len(lines) and point_token(lines[idx]) is None:
                idx += 1
            points: list[int] = []
            while idx < len(lines):
                point = point_token(lines[idx])
                if point is None:
                    break
                points.append(point)
                idx += 1

            for group, item, point in zip(groups, items, points[:len(items)]):
                old_results.append({"question": item, "points": point, "group": roman_map[group]})

        optional_match = re.search(r"(\d+)\s*[x×]\s*(\d+)\s*pontos", scoring_text, re.IGNORECASE)
        optional_points = int(optional_match.group(2)) if optional_match else None
        if optional_points:
            current_group = ""
            in_optional_section = False
            for line in lines:
                if "contribuem para a classificação" in line.lower() or "contribuem para a classificacao" in line.lower():
                    in_optional_section = True
                    continue
                if not in_optional_section:
                    continue
                group = roman_token(line)
                if group:
                    current_group = roman_map[group]
                    continue
                item = item_token(line)
                if item and current_group:
                    old_results.append({"question": item, "points": optional_points, "group": current_group})

        return old_results

    def _extract_metadata(self, page_results: list[dict], extraction: dict) -> dict:
        """Extract metadata deterministically from raw PDF text (pages 1-2)."""
        metadata = {
            "title": None,
            "subject": None,
            "year": None,
            "phase": None,
            "total_pages": extraction["total_pages"],
        }

        # Use raw text from first 2 pages of the ORIGINAL extraction (not filtered)
        for p in extraction["pages"][:2]:
            text = p.get("text", "")
            if not text:
                continue
            # Extract year
            if not metadata["year"]:
                year_match = re.search(r'20[12]\d', text)
                if year_match:
                    metadata["year"] = year_match.group()
            # Extract subject
            if not metadata["subject"]:
                subjects = ["Matemática A", "Matemática", "Física e Química", "Português", "Biologia e Geologia", "Filosofia", "Geometria Descritiva"]
                for s in subjects:
                    if s.lower() in text.lower():
                        metadata["subject"] = s
                        break
            # Extract phase
            if not metadata["phase"]:
                if "1.ª Fase" in text or "1ª Fase" in text or "1.ª fase" in text:
                    metadata["phase"] = "1ª Fase"
                elif "2.ª Fase" in text or "2ª Fase" in text:
                    metadata["phase"] = "2ª Fase"
            # Title
            if metadata["subject"] and metadata["year"] and not metadata["title"]:
                metadata["title"] = f"Exame Nacional de {metadata['subject']} - {metadata['year']}"

        return metadata

    def _assemble_output(self, extraction: dict, page_results: list[dict], subject_profile: dict = None) -> dict:
        """Combine extraction data + vision results into final ExamOutput."""
        all_questions = []
        all_assets = []
        all_warnings = []
        seen_ids = set()
        group_questions = {}  # track parent groups

        # Build raw text lookup per page (for sourceTextRaw)
        _page_raw_text = {p["page"]: p.get("text", "") for p in extraction.get("pages", [])}

        # Extract metadata
        metadata = self._extract_metadata(page_results, extraction)

        for page_data in page_results:
            page_num = page_data.get("page", 0)

            if page_data.get("error"):
                all_warnings.append({
                    "type": "page_error",
                    "message": f"Page {page_num}: {page_data['error']}"
                })
                continue

            # Collect figures/assets from LLM
            for fig in page_data.get("figures", []):
                fig_id = fig.get("id", f"fig_p{page_num}_{len(all_assets)}")
                # Normalize ID and make unique with page
                fig_id = fig_id.lower().replace(" ", "_").replace(".", "")
                fig_id = f"{fig_id}_p{page_num}"  # Always include page for uniqueness
                asset = {
                    "id": fig_id,
                    "type": fig.get("type", "unknown"),
                    "page": page_num,
                    "label": fig.get("label") or fig.get("id", "").replace("_", " ").title(),
                    "description": fig.get("description", ""),
                    "bbox_estimate": fig.get("bbox_estimate"),
                    "nearQuestion": fig.get("nearQuestion"),
                }
                all_assets.append(asset)

            # Collect questions
            for q in page_data.get("questions", []):
                number = str(q.get("number", ""))
                if not number:
                    continue

                # For source-grouping subjects (History etc.), don't create sub-questions
                # I/II/III/IV and a/b/c/d inside statements are NOT sub-questions
                has_source_grouping = subject_profile.get("has_source_grouping", False) if subject_profile else False
                is_sub = "." in number and not has_source_grouping
                parent_num = ".".join(number.split(".")[:-1]) if is_sub else None

                # For History: flatten "2.1" → just "2" (it's the same question)
                if has_source_grouping and "." in number:
                    # Skip sub-items entirely — they're part of the parent question
                    base_num = number.split(".")[0]
                    # Check if we already have this base number on this page
                    if any(eq.get("number") == base_num and eq.get("sourcePage") == page_num
                           for eq in all_questions):
                        continue
                    number = base_num

                # Generate unique ID
                if has_source_grouping:
                    group_label = page_data.get("group", "") or page_data.get("grupo", "") or ""
                    group_slug = re.sub(r'[^a-zA-Z0-9]', '', group_label).lower()
                    q_id = f"{group_slug}_q{number.replace('.', '_')}" if group_slug else f"q{number.replace('.', '_')}"
                else:
                    q_id = f"q{number.replace('.', '_')}"

                # If a synthetic group exists with this ID, merge real data into it
                if q_id in group_questions and group_questions[q_id].get("_synthetic"):
                    existing = group_questions[q_id]
                    if q.get("statement"):
                        existing["statement"] = q["statement"]
                    if q.get("rawText"):
                        existing["rawText"] = q["rawText"]
                    existing["sourcePage"] = page_num
                    existing.pop("_synthetic", None)
                    seen_ids.add(q_id)
                    continue

                if q_id in seen_ids:
                    q_id = f"q{number.replace('.', '_')}_p{page_num}"
                seen_ids.add(q_id)

                # If sub-question, ensure parent group exists
                parent_id = None
                if parent_num:
                    if has_source_grouping and group_slug:
                        parent_id = f"{group_slug}_q{parent_num.replace('.', '_')}"
                    else:
                        parent_id = f"q{parent_num}"
                    if parent_id not in group_questions:
                        group_questions[parent_id] = {
                            "questionId": parent_id,
                            "number": parent_num,
                            "type": "group",
                            "sourcePage": page_num,
                            "statement": "",
                            "options": [],
                            "imageRefs": [],
                            "tableRefs": [],
                            "assetRefs": [],
                            "visualDependency": False,
                            "confidence": 0.9,
                            "needsHumanReview": False,
                            "warnings": [],
                            "parentQuestion": None,
                            "mathHeavy": False,
                            "hasGraph": False,
                            "hasDiagram": False,
                            "hasTable": False,
                            "isGroup": True,
                            "subQuestions": [],
                            "_synthetic": True,
                        }

                # Determine imageRefs and tableRefs
                image_refs = []
                table_refs = []
                visual_dep = False
                statement = str(q.get("statement", "") or "")

                ref = q.get("referencesImage")
                if ref and isinstance(ref, str):
                    visual_dep = True
                    fig_id = ref.lower().replace(" ", "_").replace(".", "")
                    # Find matching asset (with page suffix)
                    matched = False
                    for a in all_assets:
                        if a["id"].startswith(fig_id) and a["page"] == page_num:
                            image_refs.append(a["id"])
                            matched = True
                            break
                    if not matched:
                        # Try any page
                        for a in all_assets:
                            if a["id"].startswith(fig_id):
                                image_refs.append(a["id"])
                                matched = True
                                break
                    if not matched:
                        image_refs.append(f"{fig_id}_p{page_num}")  # Reference even if not found yet

                # Detect table references
                if re.search(r'tabela|quadro', statement, re.IGNORECASE):
                    visual_dep = True
                    # Find matching table asset
                    for a in all_assets:
                        if a["type"] == "table" and a["page"] == page_num:
                            table_refs.append(a["id"])
                    if not table_refs:
                        # Create implicit table asset
                        t_id = f"tabela_p{page_num}"
                        table_refs.append(t_id)
                        all_assets.append({
                            "id": t_id,
                            "type": "table",
                            "page": page_num,
                            "description": "Tabela referenciada no enunciado",
                            "bbox_estimate": None,
                            "nearQuestion": number,
                        })

                # Also check if parent group has image refs (inherit)
                if parent_id and parent_id in group_questions:
                    parent_refs = group_questions[parent_id].get("imageRefs", [])
                    for pr in parent_refs:
                        if pr not in image_refs:
                            image_refs.append(pr)
                            visual_dep = True

                # Infer mathHeavy from content
                math_indicators = ['²', '³', '√', '∫', 'π', 'θ', '≥', '≤', '∈', '∞', 'lim', 'sen', 'cos', 'tg', 'log', 'ln', '→', 'f(x)', 'g(x)', 'Σ', '∆', 'α', 'β']
                is_math = q.get("mathHeavy", False) or q.get("mathUncertain", False) or any(ind in statement for ind in math_indicators)

                # Confidence heuristic — dynamic based on actual factors
                confidence = 0.92  # Base: text-only question, well extracted
                warnings = []

                # mathUncertain from LLM
                if q.get("mathUncertain"):
                    confidence -= 0.2
                    warnings.append({"type": "math_uncertain", "message": f"Q{number} has uncertain math transcription"})

                # Reduce confidence for visual dependencies without matched assets
                if visual_dep and not image_refs and not table_refs:
                    confidence -= 0.25
                    warnings.append({"type": "missing_asset", "message": f"Q{number} references visual but no asset found"})
                elif visual_dep:
                    confidence -= 0.05  # Visual questions are slightly less reliable

                # Reduce for math-heavy (formula OCR errors likely)
                if q.get("mathHeavy") or q.get("mathUncertain"):
                    confidence -= 0.08

                # Reduce for very short statements (likely truncated)
                if len(statement) < 30 and not q.get("blanks"):
                    confidence -= 0.15
                    warnings.append({"type": "short_statement", "message": f"Q{number} statement suspiciously short"})

                # Reduce for multiple choice without enough options
                if q.get("type") == "multiple_choice" and len(q.get("options", [])) < 3:
                    confidence -= 0.2
                    warnings.append({"type": "missing_options", "message": f"Q{number} multiple choice with <3 options"})

                confidence = round(max(0.1, min(1.0, confidence)), 2)

                # hasDiagram/hasGraph: check both nearQuestion AND imageRefs
                all_q_asset_ids = set(image_refs + table_refs)
                has_graph = q.get("type") == "graph" or any(
                    a.get("type") == "graph" for a in all_assets
                    if a.get("nearQuestion") == number or a["id"] in all_q_asset_ids
                )
                has_diagram = any(
                    a.get("type") == "geometry_diagram" for a in all_assets
                    if a.get("nearQuestion") == number or a["id"] in all_q_asset_ids
                )
                has_table = len(table_refs) > 0 or q.get("referencesTable", False)

                # calculatorAllowed: default True unless explicitly stated
                calc_allowed = q.get("calculatorAllowed", True)
                if "sem recorrer à calculadora" in statement.lower() or "sem calculadora" in statement.lower():
                    calc_allowed = False

                question = {
                    "questionId": q_id,
                    "number": number,
                    "type": q.get("type", "open_answer"),
                    "sourcePage": page_num,
                    "statement": statement,
                    "sourceTextRaw": _page_raw_text.get(page_num, ""),
                    "rawText": q.get("rawText") or None,
                    "blanks": q.get("blanks") or None,
                    "options": q.get("options", []),
                    "maxSelections": q.get("maxSelections"),
                    "imageRefs": image_refs,
                    "tableRefs": table_refs,
                    "assetRefs": [],
                    "visualDependency": visual_dep,
                    "confidence": round(confidence, 2),
                    "needsHumanReview": confidence < 0.75 or q.get("mathUncertain", False),
                    "warnings": warnings,
                    "parentQuestion": parent_id,
                    "subQuestions": [],
                    "mathHeavy": is_math,
                    "hasGraph": has_graph,
                    "hasDiagram": has_diagram,
                    "hasTable": has_table,
                    "calculatorAllowed": calc_allowed,
                    "points": q.get("points"),
                }

                # Detect mandatory questions (marked with ✱/* in the PDF)
                raw_ctx = question.get("sourceTextRaw", "") or ""
                mand_pat = re.compile(r'[✱\*❋]\s*' + re.escape(number) + r'[.\s]')
                question["isMandatory"] = bool(
                    mand_pat.search(raw_ctx) or mand_pat.search(statement)
                )

                all_questions.append(question)

                # Track in parent group
                if parent_id and parent_id in group_questions:
                    group_questions[parent_id]["subQuestions"].append(q_id)
                    if visual_dep:
                        group_questions[parent_id]["visualDependency"] = True
                    for ir in image_refs:
                        if ir not in group_questions[parent_id]["imageRefs"]:
                            group_questions[parent_id]["imageRefs"].append(ir)
                    # Inherit groupContext into parent statement
                    gc = q.get("groupContext")
                    if gc and not group_questions[parent_id]["statement"]:
                        group_questions[parent_id]["statement"] = gc
                        group_questions[parent_id]["mathHeavy"] = q.get("mathHeavy", False) or q.get("mathUncertain", False)

        # ── Fix 2: Merge group_questions into all_questions ────────
        # If a question was already extracted as a normal question but also has
        # children (group_questions entry), convert it to a group in-place.
        for gid, gq in group_questions.items():
            if gid in seen_ids:
                # Already in all_questions — convert to group in-place
                for q in all_questions:
                    if q["questionId"] == gid:
                        q["type"] = "group"
                        q["isGroup"] = True
                        q["subQuestions"] = gq["subQuestions"]
                        q["blanks"] = None
                        if gq["statement"] and not q["statement"]:
                            q["statement"] = gq["statement"]
                        break
            else:
                # Group not yet in list — add it
                gq["type"] = "group"
                gq["blanks"] = None
                all_questions.insert(0, gq)
                seen_ids.add(gid)

        # ── Fix 2b: Rebuild subQuestions from children's parentQuestion ────
        # Ensures parent always knows its children regardless of extraction order
        parent_children: dict[str, list[str]] = {}
        for q in all_questions:
            pid = q.get("parentQuestion")
            if pid:
                parent_children.setdefault(pid, []).append(q["questionId"])
        for q in all_questions:
            qid = q["questionId"]
            if qid in parent_children:
                q["subQuestions"] = parent_children[qid]
                q["isGroup"] = True
                if q["type"] != "group":
                    q["type"] = "group"
                    q["blanks"] = None

        # ── Inherit properties from children to parent groups ────
        for q in all_questions:
            if not q.get("isGroup"):
                continue
            children = [c for c in all_questions if c.get("parentQuestion") == q["questionId"]]
            # mathHeavy: true if ANY child is mathHeavy
            if any(c.get("mathHeavy") for c in children):
                q["mathHeavy"] = True
            # calculatorAllowed: false if ALL children are false OR statement says so
            child_calc = [c.get("calculatorAllowed") for c in children if c.get("calculatorAllowed") is not None]
            if child_calc and all(c == False for c in child_calc):
                q["calculatorAllowed"] = False
            elif "sem recorrer à calculadora" in str(q.get("statement", "")).lower():
                q["calculatorAllowed"] = False

        # ── Fix 4: Propagate calculatorAllowed from parent to children ────
        for q in all_questions:
            pid = q.get("parentQuestion")
            if not pid:
                continue
            if q.get("calculatorAllowed") is None or q.get("calculatorAllowed") is True:
                # Find parent
                for parent in all_questions:
                    if parent["questionId"] == pid:
                        if parent.get("calculatorAllowed") == False:
                            q["calculatorAllowed"] = False
                        break

        # ── Fix 5: Default bbox for tables without bbox ────
        for asset in all_assets:
            if asset.get("type") == "table" and not asset.get("bbox_estimate") and not asset.get("bbox"):
                # Full-width table default: spans most of the page width
                asset["bbox_estimate"] = {"x_pct": 5, "y_pct": 20, "w_pct": 90, "h_pct": 30}

        # ── Fix 6: Sequence check — emit warnings for missing questions ────
        # Skip for source-grouping subjects (History, etc.) where numbering resets per group
        has_source_grouping = subject_profile.get("has_source_grouping", False) if subject_profile else False
        main_numbers = sorted(set(
            int(q["number"]) for q in all_questions
            if q["number"].isdigit() and not q.get("parentQuestion")
        ))
        if main_numbers and not has_source_grouping:
            # Always start from 1
            for expected_num in range(1, main_numbers[-1] + 1):
                if expected_num not in main_numbers:
                    prev_q = max((n for n in main_numbers if n < expected_num), default=None)
                    next_q = min((n for n in main_numbers if n > expected_num), default=None)
                    msg = f"⚠️ Question {expected_num} not found"
                    if expected_num == 1:
                        msg = f"⚠️ Question 1 missing — first question not extracted"
                    elif prev_q and next_q:
                        msg = f"⚠️ Question {expected_num} not found — gap between Q{prev_q} and Q{next_q}"
                    all_warnings.append({
                        "type": "missing_question",
                        "severity": "critical",
                        "message": msg
                    })

        # Apply scoring (cotações) from any page that had them
        scoring_entries = []
        for page_data in page_results:
            for score in page_data.get("scoring", []):
                # Accept both 'question' and 'number' keys from model
                q_num = str(score.get("question") or score.get("number") or "").strip().rstrip(".")
                pts = score.get("points") or score.get("cotacao") or score.get("score")
                # Also accept group key for History scoring
                group = score.get("group") or score.get("grupo") or ""
                if q_num and pts is not None:
                    try:
                        pts = int(float(str(pts)))
                    except (ValueError, TypeError):
                        continue
                    if pts > 0:
                        scoring_entries.append({"question": q_num, "points": pts, "group": str(group)})

        # ── History scoring: parse from last page text by group+item ──
        has_source_grouping = subject_profile.get("has_source_grouping", False) if subject_profile else False
        if has_source_grouping:
            history_scores = self._parse_history_scoring(extraction)
            if history_scores:
                scoring_entries = history_scores  # Override with deterministic parse

        # Apply scoring to questions — try multiple matching strategies
        for entry in scoring_entries:
            q_num = entry["question"]
            pts = entry["points"]
            entry_group = entry.get("group", "")
            matched = False

            # Strategy 0: match by groupId + number (for History)
            if entry_group:
                for q in all_questions:
                    q_group = q.get("groupId") or q.get("group", "")
                    if q["number"] == q_num and entry_group.lower() in q_group.lower():
                        q["points"] = pts
                        matched = True
                        break
                if matched:
                    continue

            # Strategy 1: exact match
            for q in all_questions:
                if q["number"] == q_num and q.get("points") is None:
                    q["points"] = pts
                    matched = True
                    break
            if matched:
                continue
            # Strategy 2: normalized (strip leading zeros, spaces)
            normalized = q_num.lstrip("0").strip() or "0"
            for q in all_questions:
                if q["number"] == normalized and q.get("points") is None:
                    q["points"] = pts
                    matched = True
                    break
            if matched:
                continue
            # Strategy 3: try matching with/without dot (e.g. "2.1" vs "2_1")
            alt = q_num.replace("_", ".")
            for q in all_questions:
                if q["number"] == alt and q.get("points") is None:
                    q["points"] = pts
                    break

        scoring_candidate_text = ""
        scoring_candidate_pages = extraction.get("_processed_pages") or extraction.get("pages", [])
        for scoring_page in reversed(scoring_candidate_pages[-4:]):
            candidate_text = scoring_page.get("text", "")
            if _has_scoring_text(candidate_text):
                scoring_candidate_text = candidate_text
                break
        if not scoring_candidate_text and scoring_candidate_pages:
            scoring_candidate_text = scoring_candidate_pages[-1].get("text", "")

        # If most questions still have no points, try text-based scoring from last page
        real_qs_no_points = [q for q in all_questions if q["number"].isdigit() and not q.get("parentQuestion") and not q.get("isGroup") and q.get("points") is None]
        if len(real_qs_no_points) > len(all_questions) // 3:
            # Scoring merge mostly failed — try text-based fallback
            last_text = scoring_candidate_text
            if last_text:
                # Try to parse scoring from raw text using regex
                import re as _re
                # Pattern: question number followed by dots/spaces and points
                text_scores = _re.findall(r'(\d+(?:\.\d+)?)\s*[.\s…·]+\s*(\d+)', last_text)
                for q_num_str, pts_str in text_scores:
                    try:
                        pts = int(pts_str)
                    except ValueError:
                        continue
                    if pts <= 0 or pts > 50:
                        continue
                    q_num = q_num_str.lstrip("0").rstrip(".") or "0"
                    for q in all_questions:
                        if q["number"] == q_num and q.get("points") is None:
                            q["points"] = pts
                            break

        # Detect optional questions from scoring page: "N × P pontos" pattern
        # and list of optional question numbers
        last_text = scoring_candidate_text
        import re as _re2
        opt_match = _re2.search(r'(\d+)\s*[×x]\s*(\d+)\s*pontos', last_text)
        opt_points = int(opt_match.group(2)) if opt_match else None
        opt_choose = int(opt_match.group(1)) if opt_match else None
        # Try to find which questions are optional (listed near the "× pontos" section)
        opt_question_nums = set()
        if opt_points:
            opt_section = _re2.search(r'(?:opcion|contribuem para a classificação final da prova os \d+ itens)[\s\S]{0,300}', last_text, _re2.IGNORECASE)
            if opt_section:
                opt_question_nums = {int(n) for n in _re2.findall(r'\b(\d{1,2})\b', opt_section.group())}

        # Build scoringGroup metadata
        scoring_group = None
        if opt_points and opt_choose:
            scoring_group = {
                "type": "best_of",
                "choose": opt_choose,
                "from": len(opt_question_nums) or opt_choose,
                "pointsEach": opt_points,
            }

        # Mark optional questions (even if they already have points from main scoring)
        if opt_question_nums:
            for q in all_questions:
                q_num = int(q["number"]) if q["number"].isdigit() else 0
                if q_num in opt_question_nums:
                    q.setdefault("disciplineData", {})["optional"] = True
                    if scoring_group:
                        q.setdefault("disciplineData", {})["scoringGroup"] = scoring_group
                    if q.get("points") is None:
                        q["points"] = opt_points

        # Warn for questions still without points
        for q in all_questions:
            if q.get("points") is None and not q.get("isGroup"):
                q_num = int(q["number"]) if q["number"].isdigit() else 0
                # If we have optional points and no specific list, assign to all unscored
                if opt_points and not opt_question_nums and 8 <= opt_points <= 30:
                    q["points"] = opt_points
                    q.setdefault("disciplineData", {})["optional"] = True
                    if scoring_group:
                        q.setdefault("disciplineData", {})["scoringGroup"] = scoring_group
                    continue
                q.setdefault("warnings", []).append({
                    "type": "missing_points",
                    "message": f"No scoring entry applied for Q{q['number']}"
                })

        # Fix scoring for groups: if group parent has points but children don't,
        # the points belong to the group (shared). Don't duplicate to children.
        # If children have individual points, parent gets the sum.
        for q in all_questions:
            if not q.get("isGroup"):
                continue
            children = [c for c in all_questions if c.get("parentQuestion") == q["questionId"]]
            child_points = [c.get("points") for c in children if c.get("points") is not None]
            if q.get("points") is None and child_points:
                # Parent has no points but children do — sum them
                q["points"] = sum(child_points)
            elif q.get("points") is not None and not child_points:
                # Parent has points but children don't — points are shared (leave as-is)
                pass

        # Sort questions by page then number
        def sort_key(q):
            num = q["number"]
            parts = num.split(".")
            try:
                return (q["sourcePage"], int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except ValueError:
                return (q["sourcePage"], 999, 0)
        all_questions.sort(key=sort_key)

        # Add per-question page region for safer crop boundaries
        _attach_question_regions(all_questions, extraction)

        # Add embedded images from PDF extraction as assets (with REAL bbox)
        for asset in extraction.get("assets", []):
            abs_path = asset.get("path")
            # Build portable relative path and public URL — never expose the absolute local path.
            if abs_path:
                from pathlib import Path as _Path
                try:
                    rel = _Path(abs_path).relative_to(self.output_dir / self.exam_id)
                    rel_str = rel.as_posix()
                except ValueError:
                    rel_str = f"assets/{_Path(abs_path).name}"
                public_url = f"/api/exams/{self.exam_id}/assets/{_Path(abs_path).name}"
            else:
                rel_str = None
                public_url = None
            all_assets.append({
                "id": asset["id"],
                "type": "embedded_image",
                "page": asset["page"],
                "bbox": asset["bbox"],
                "relativePath": rel_str,
                "url": public_url,
                "img_width": asset.get("img_width"),
                "img_height": asset.get("img_height"),
            })

        # Warnings for unassociated assets
        all_image_refs = set()
        all_table_refs = set()
        for q in all_questions:
            all_image_refs.update(q.get("imageRefs", []))
            all_table_refs.update(q.get("tableRefs", []))

        for asset in all_assets:
            aid = asset["id"]
            if aid in all_image_refs or aid in all_table_refs or asset["type"] == "embedded_image":
                continue

            associated = False

            # Try nearQuestion first
            near = asset.get("nearQuestion")
            if near:
                for q in all_questions:
                    if q["number"] == near:
                        if asset["type"] == "table":
                            q["tableRefs"].append(aid)
                        else:
                            q["imageRefs"].append(aid)
                            q["visualDependency"] = True
                        associated = True
                        break

            # Fallback: geometric association by page — find the question on the
            # same page whose region is closest above/around the asset label.
            if not associated:
                asset_page = asset.get("page")
                page_questions = [q for q in all_questions if q.get("sourcePage") == asset_page]
                if page_questions:
                    # Sort by position (earlier questions first)
                    page_questions.sort(key=lambda q: (q.get("region", {}).get("y0", 0) if q.get("region") else 0))
                    # Pick the last question that starts before or near the asset
                    # (figures are usually placed after the question text)
                    best_q = page_questions[0]  # default: first question on page
                    for q in page_questions:
                        best_q = q  # last question on page before end
                    if best_q:
                        if asset["type"] == "table":
                            best_q["tableRefs"].append(aid)
                        else:
                            best_q["imageRefs"].append(aid)
                            best_q["visualDependency"] = True
                        associated = True

            if not associated:
                all_warnings.append({
                    "type": "unassociated_asset",
                    "message": f"Asset '{aid}' (page {asset['page']}) not linked to any question"
                })

        # Stats
        main_questions = len([q for q in all_questions if not q.get("parentQuestion") and not q.get("isGroup")])
        groups = len(group_questions)
        answerable = len([q for q in all_questions if not q.get("isGroup")])

        metadata["stats"] = {
            "mainQuestions": main_questions + groups,
            "answerableItems": answerable,
            "jsonNodes": len(all_questions),
        }

        # Processing status
        missing_pages = []
        for w in all_warnings:
            if w["type"] == "page_error":
                # Extract page number from message like "Page 4: ..."
                import re as _re
                m = _re.search(r'Page (\d+)', w["message"])
                if m:
                    missing_pages.append(int(m.group(1)))

        if missing_pages:
            processing_status = "partial_failed"
        elif all_warnings:
            processing_status = "completed_with_warnings"
        else:
            processing_status = "completed"

        return {
            "exam_id": self.exam_id,
            "processingStatus": processing_status,
            "missingPages": missing_pages,
            "needsHumanReview": processing_status == "partial_failed" or any(q.get("needsHumanReview") for q in all_questions),
            "metadata": metadata,
            "assets": all_assets,
            "questions": all_questions,
            "warnings": all_warnings,
        }
