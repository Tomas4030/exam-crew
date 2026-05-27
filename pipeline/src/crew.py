"""ExamCrew Pipeline v3: PDF → subject detection → pre-scan → per-question extraction → JSON."""
import json
import re
from pathlib import Path

from .tools.pdf_extractor import PDFExtractorTool
from .tools.vision_tool import analyze_exam_pages
from .utils.progress import report_progress
from .utils.validator import validate_and_fix
from .utils.normalizer import normalize
from .utils.math_normalize import math_normalize
from .utils.subjects import detect_subject, is_formula_page
from .utils.source_grouping import apply_source_grouping


class ExamProcessingCrew:
    def __init__(self, pdf_path: str, exam_id: str, base_dir: str = None):
        self.pdf_path = pdf_path
        self.exam_id = exam_id
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent.parent
        self.output_dir = self.base_dir / "data" / "output"
        self.extracted_dir = self.base_dir / "data" / "extracted" / exam_id

    def run(self) -> dict:
        self.extracted_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Extract PDF
        report_progress("extract", "Rendering PDF pages as images")
        extractor = PDFExtractorTool()
        extraction_raw = extractor._run(self.pdf_path, str(self.extracted_dir))
        extraction = json.loads(extraction_raw)
        report_progress("extract_done", f"Rendered {extraction['total_pages']} pages, found {len(extraction['assets'])} embedded images")

        # Step 1.5: Detect subject and filter formula pages
        cover_text = extraction["pages"][0]["text"] if extraction["pages"] else ""
        subject_key, subject_profile = detect_subject(cover_text)
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

        # Step 2.5: Dedicated scoring extraction from last page
        # Try vision first, then text fallback. Also collect any scoring from pre-scan.
        from .tools.vision_tool import _extract_scoring, _call_text
        scoring_collected = []

        # Collect scoring already found during pre-scan
        for pr in page_results:
            if pr.get("scoring"):
                scoring_collected.extend(pr["scoring"])

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
        output = self._assemble_output(extraction, page_results, subject_profile)
        output["metadata"]["subject"] = subject_key.replace("_", " ").title() if subject_key != "unknown" else None
        output["metadata"]["formula_pages"] = formula_pages

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
        output = normalize(output)

        # Step 3.7: Crop assets from rendered pages
        from .utils.cropper import crop_assets
        report_progress("crop", "Cropping assets from page images")
        crop_output_dir = self.output_dir / self.exam_id
        output["_pdf_path"] = self.pdf_path
        output = crop_assets(output, extraction, crop_output_dir)
        output.pop("_pdf_path", None)

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

        # Step 5: Save
        out_file = self.output_dir / f"{self.exam_id}.json"
        out_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        report_progress("done", f"Saved to {out_file}")
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
                    q_num = str(score.get("question") or score.get("number") or "").strip()
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
            output = normalize(output)
            output = validate_and_fix(output, extraction)

        return output

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
        pages = extraction.get("pages", [])
        if not pages:
            return []

        scoring_text = ""
        for p in pages[-2:]:
            text = p.get("text", "")
            if "cotaç" in text.lower():
                scoring_text = text
                break
        if not scoring_text:
            return []

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
                    # Optional items are 13 points each (standard for Portuguese national exams)
                    results.append({"question": item_m.group(1), "points": 13, "group": optional_group})

        return results

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
                parent_num = number.split(".")[0] if is_sub else None

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
                q_id = f"q{number.replace('.', '_')}"
                if q_id in seen_ids:
                    q_id = f"q{number.replace('.', '_')}_p{page_num}"
                seen_ids.add(q_id)

                # If sub-question, ensure parent group exists
                parent_id = None
                if parent_num:
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
                q_num = str(score.get("question") or score.get("number") or "").strip()
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
                    if q["number"] == q_num and entry_group.lower() in q_group.lower() and q.get("points") is None:
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

        # If most questions still have no points, try text-based scoring from last page
        real_qs_no_points = [q for q in all_questions if q["number"].isdigit() and not q.get("parentQuestion") and not q.get("isGroup") and q.get("points") is None]
        if len(real_qs_no_points) > len(all_questions) // 3:
            # Scoring merge mostly failed — try text-based fallback
            last_page = extraction["pages"][-1]
            last_text = last_page.get("text", "")
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
                    q_num = q_num_str.lstrip("0") or "0"
                    for q in all_questions:
                        if q["number"] == q_num and q.get("points") is None:
                            q["points"] = pts
                            break

        # Detect optional questions from scoring page: "N × P pontos" pattern
        # and list of optional question numbers
        last_page = extraction["pages"][-1]
        last_text = last_page.get("text", "")
        import re as _re2
        opt_match = _re2.search(r'(\d+)\s*[×x]\s*(\d+)\s*pontos', last_text)
        opt_points = int(opt_match.group(2)) if opt_match else None
        # Try to find which questions are optional (listed near the "× pontos" section)
        opt_question_nums = set()
        if opt_points:
            # Look for a list of numbers near "itens" or "opcionais"
            opt_section = _re2.search(r'(?:opcion|contribuem para a classificação final da prova os \d+ itens)[\s\S]{0,200}', last_text, _re2.IGNORECASE)
            if opt_section:
                opt_question_nums = {int(n) for n in _re2.findall(r'\b(\d{1,2})\b', opt_section.group())}

        # Warn for questions still without points
        for q in all_questions:
            if q.get("points") is None and not q.get("isGroup"):
                q_num = int(q["number"]) if q["number"].isdigit() else 0
                # If this question is in the optional group, assign optional points
                if opt_points and q_num in opt_question_nums:
                    q["points"] = opt_points
                    q.setdefault("disciplineData", {})["optional"] = True
                    continue
                # If we have optional points and no specific list, assign to all unscored
                if opt_points and not opt_question_nums and 8 <= opt_points <= 30:
                    q["points"] = opt_points
                    q.setdefault("disciplineData", {})["optional"] = True
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

        # Add embedded images from PDF extraction as assets (with REAL bbox)
        for asset in extraction.get("assets", []):
            all_assets.append({
                "id": asset["id"],
                "type": "embedded_image",
                "page": asset["page"],
                "bbox": asset["bbox"],
                "url": asset["path"],
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
            if aid not in all_image_refs and aid not in all_table_refs and asset["type"] != "embedded_image":
                # Try to auto-associate by nearQuestion
                near = asset.get("nearQuestion")
                if near:
                    for q in all_questions:
                        if q["number"] == near:
                            if asset["type"] == "table":
                                q["tableRefs"].append(aid)
                            else:
                                q["imageRefs"].append(aid)
                                q["visualDependency"] = True
                            break
                    else:
                        all_warnings.append({
                            "type": "unassociated_asset",
                            "message": f"Asset '{aid}' (page {asset['page']}) not linked to any question"
                        })
                else:
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
