"""Vision extraction v3: pre-scan + per-question extraction to avoid truncation."""
import base64
import json
import time
import re

import httpx

from ..config import OPENROUTER_BASE_URL, OPENROUTER_API_KEY, OPENROUTER_MODEL


def _call_vision(image_path: str, prompt: str, max_tokens: int = 2048) -> str | None:
    """Send image + prompt to vision model. Returns content or None."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    response = httpx.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENROUTER_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            "max_tokens": max_tokens,
            "temperature": 0.05,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=180,
    )

    if response.status_code != 200:
        return None
    data = response.json()
    return data["choices"][0]["message"]["content"] or None


def _call_text(prompt: str, max_tokens: int = 2048) -> str | None:
    """Send text-only prompt as fallback."""
    response = httpx.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.05,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=120,
    )
    if response.status_code != 200:
        return None
    data = response.json()
    return data["choices"][0]["message"]["content"] or None


def _parse_json(content: str) -> dict | None:
    """Try to parse JSON from model output."""
    if not content:
        return None
    import re
    # Direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # From markdown
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Find JSON object
    match = re.search(r'\{[\s\S]*\}', content)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _prescan_page(image_path: str, page_num: int) -> dict | None:
    """Step 1: Quick scan to identify page type and question numbers."""
    prompt = f"""Look at this exam page (page {page_num}). Identify:
1. Page type: cover, formulary, instructions, questions, or scoring
2. List ALL question numbers visible (e.g. "1", "2", "2.1", "2.2", "3")
3. List any figures/tables with their labels (e.g. "Figura 1", "Tabela")

Important: Roman numerals I, II, III, IV inside fill-in-the-blank questions are blanks, NOT question numbers. Only include actual numbered questions (1., 2., 2.1, etc.)

Respond ONLY with JSON:
{{"page": {page_num}, "pageType": "questions", "questionNumbers": ["1", "2.1", "2.2"], "figures": ["Figura 1"], "hasScoring": false}}"""

    content = _call_vision(image_path, prompt, max_tokens=512)
    return _parse_json(content) if content else None


def _extract_question(image_path: str, page_num: int, q_number: str, total_pages: int) -> dict | None:
    """Step 2: Extract a single question from the page."""
    prompt = f"""Extract ONLY question {q_number} from this exam page (page {page_num}/{total_pages}).

Respond ONLY with JSON:
{{
  "number": "{q_number}",
  "type": "multiple_choice|multi_select|open_answer|multi_blank_choice|calculation|proof",
  "statement": "texto EXATO da pergunta",
  "rawText": "texto original com fórmulas se houver dúvida",
  "mathUncertain": false,
  "options": [{{"letter": "A", "text": "..."}}],
  "maxSelections": null,
  "blanks": null,
  "calculatorAllowed": null,
  "points": null,
  "referencesImage": null,
  "referencesTable": false,
  "groupContext": "texto partilhado antes de sub-perguntas (se aplicável)"
}}

Rules:
- Copy text EXACTLY as shown. Do NOT simplify formulas.
- If question has blanks/spaces I, II, III, IV with separate options (a/b/c) for each, it is type "multi_blank_choice".
  For multi_blank_choice, set options=[] and fill blanks like this:
  "blanks": [
    {{"number": "I", "options": [{{"letter": "a", "text": "value1"}}, {{"letter": "b", "text": "value2"}}, {{"letter": "c", "text": "value3"}}]}},
    {{"number": "II", "options": [{{"letter": "a", "text": "..."}}, ...]}}
  ]
  Do NOT collapse blanks into a single multiple choice A/B/C/D.
- For normal multiple choice (A)/(B)/(C)/(D), use type "multiple_choice" with options.
- If the question asks to select/identify two options from I-V or a-e, use type "multi_select", set options, and set maxSelections=2.
- calculatorAllowed: false only if text says "sem recorrer à calculadora", else null.
- groupContext: shared text before sub-questions (e.g. function definition).
- referencesTable: true if the question uses a table shown on the page.
- Respond ONLY with the JSON object. No markdown, no explanation."""

    content = _call_vision(image_path, prompt, max_tokens=1500)
    return _parse_json(content) if content else None


def _extract_figure(image_path: str, page_num: int, fig_label: str) -> dict | None:
    """Extract figure info including bbox estimate."""
    prompt = f"""Look at "{fig_label}" on this page. Estimate its position as percentage of page dimensions.

Respond ONLY with JSON:
{{
  "id": "{fig_label.lower().replace(' ', '_')}",
  "label": "{fig_label}",
  "type": "geometry_diagram|graph|table|chart|map",
  "description": "brief description of what the figure shows",
  "nearQuestion": "7",
  "bbox_estimate": {{"x_pct": 30, "y_pct": 40, "w_pct": 40, "h_pct": 30}}
}}"""

    content = _call_vision(image_path, prompt, max_tokens=512)
    return _parse_json(content) if content else None


def analyze_exam_pages(pages_data: list[dict], delay: float = 2.0) -> list[dict]:
    """Analyze all pages using pre-scan + per-question extraction."""
    def _question_numbers_from_text(text: str) -> list[str]:
        if not text:
            return []

        numbers: list[str] = []
        for match in re.finditer(r"(?m)^\s*(\d{1,2}(?:\.\d+)?)\.\s+\S", text):
            n = match.group(1).strip()
            if n not in numbers:
                numbers.append(n)
        return numbers

    def _native_prescan_fallback(page_num: int, page_text: str) -> dict | None:
        q_numbers = _question_numbers_from_text(page_text or "")
        if not q_numbers:
            return {
                "page": page_num,
                "pageType": "degraded",
                "questionNumbers": [],
                "figures": [],
                "hasScoring": False,
                "_prescanFailed": True,
                "_fallback": "native_text_no_question_numbers",
            }
        return {
            "page": page_num,
            "pageType": "questions",
            "questionNumbers": q_numbers,
            "figures": [],
            "hasScoring": False,
            "_prescanFailed": True,
            "_fallback": "native_text_question_numbers",
        }

    results = []
    total = len(pages_data)

    for idx, page_info in enumerate(pages_data):
        page_num = page_info["page"]
        image_path = page_info["page_image_path"]
        page_text = page_info.get("text", "") or ""
        diagnostics = {
            "prescan_ok": False,
            "prescan_fallback_used": False,
            "prescan_fallback_kind": None,
            "native_text_len": len(page_text.strip()),
            "page_degraded": False,
            "questions_found": 0,
            "figures_found": 0,
            "warnings": [],
        }

        try:
            print(json.dumps({"stage": "vision", "message": f"Pre-scanning page {page_num} ({idx+1}/{total})"}), flush=True)

            # Step 1: Pre-scan (vision)
            scan = _prescan_page(image_path, page_num)
            time.sleep(delay)
            diagnostics["prescan_ok"] = bool(scan)

            # Step 1b: text-model prescan fallback
            if not scan:
                fallback_prompt = (
                    f"List question numbers in this text. Respond JSON: "
                    f"{{\"page\": {page_num}, \"pageType\": \"questions\", \"questionNumbers\": [], \"figures\": []}}\n\n"
                    f"Text:\n{page_text[:3000]}"
                )
                content = _call_text(fallback_prompt, 256)
                scan = _parse_json(content) if content else None
                time.sleep(delay)
                if scan:
                    diagnostics["prescan_fallback_used"] = True
                    diagnostics["prescan_fallback_kind"] = "llm_text_prescan"

            # Step 1c: native text deterministic fallback (non-blocking)
            if not scan:
                scan = _native_prescan_fallback(page_num, page_text)
                diagnostics["prescan_fallback_used"] = True
                diagnostics["prescan_fallback_kind"] = scan.get("_fallback")
                diagnostics["warnings"].append("prescan_failed_used_native_text_fallback")

            page_type = scan.get("pageType", "questions")

            # Handle scoring / non-question pages
            if page_type != "questions":
                result = {
                    "page": page_num,
                    "pageType": page_type,
                    "questions": [],
                    "figures": [],
                }
                if page_type == "scoring" or scan.get("hasScoring"):
                    scoring = _extract_scoring(image_path, page_num)
                    result["scoring"] = scoring or []
                if page_type == "degraded":
                    diagnostics["page_degraded"] = True
                    result["error"] = "Pre-scan failed and no question numbers found in native text."
                result["_diagnostics"] = diagnostics
                results.append(result)
                time.sleep(delay)
                continue

            # Step 2: Extract each question
            page_questions = []
            q_numbers = scan.get("questionNumbers", []) or []
            print(json.dumps({"stage": "vision", "message": f"Page {page_num}: extracting {len(q_numbers)} questions"}), flush=True)

            for q_num in q_numbers:
                try:
                    q_data = _extract_question(image_path, page_num, q_num, total)
                    if q_data:
                        page_questions.append(q_data)
                except Exception as q_err:
                    diagnostics["warnings"].append(f"question_extract_error:{q_num}:{q_err}")
                time.sleep(delay)

            # Step 3: Extract figures
            page_figures = []
            for fig_label in scan.get("figures", []) or []:
                try:
                    fig_data = _extract_figure(image_path, page_num, fig_label)
                    if fig_data:
                        page_figures.append(fig_data)
                except Exception as fig_err:
                    diagnostics["warnings"].append(f"figure_extract_error:{fig_label}:{fig_err}")
                time.sleep(delay)

            diagnostics["questions_found"] = len(page_questions)
            diagnostics["figures_found"] = len(page_figures)

            results.append({
                "page": page_num,
                "pageType": "questions",
                "questions": page_questions,
                "figures": page_figures,
                "_diagnostics": diagnostics,
            })
        except Exception as e:
            diagnostics["page_degraded"] = True
            diagnostics["warnings"].append(f"page_exception:{e}")
            results.append({
                "page": page_num,
                "pageType": "degraded",
                "error": str(e),
                "questions": [],
                "figures": [],
                "warnings": [{"type": "page_exception", "message": str(e)}],
                "_diagnostics": diagnostics,
            })
            continue

    return results



def _extract_table_data(image_path: str, page_num: int, table_description: str = "") -> dict | None:
    """Extract actual table data (rows/columns) from a page image."""
    prompt = f"""Look at the table on this page (page {page_num}).

Extract ALL data from the table as structured JSON.

Respond ONLY with JSON:
{{
  "columns": ["column1_header", "column2_header"],
  "rows": [
    {{"column1_header": "value1", "column2_header": "value2"}},
    {{"column1_header": "value3", "column2_header": "value4"}}
  ]
}}

Rules:
- Include ALL rows of data, not just a sample
- Use the exact column headers as shown in the table
- Preserve numeric values exactly as printed (decimals, units)
- If a cell is empty, use null"""

    content = _call_vision(image_path, prompt, max_tokens=2048)
    if not content:
        return None
    result = _parse_json(content)
    if result and result.get("rows"):
        return result
    return None


def _extract_scoring(image_path: str, page_num: int) -> list[dict] | None:
    """Extract scoring table from page."""
    prompt = """Extract the scoring/grading table (cotações) from this exam page.

CRITICAL RULES:
- Read EACH ROW of the table exactly as printed
- The "question" field must be the EXACT number shown in the table (e.g. "1", "2.1", "3", "12.1")
- The "points" field must be the integer value shown next to that question number
- Do NOT guess or reorder — transcribe exactly what the table shows
- If a question number has sub-items (e.g. "12.1", "12.2"), list each separately
- If the table shows a GROUP total (e.g. "12" with points), include it too

Respond ONLY with a JSON array, one entry per row:
[{"question": "1", "points": 12}, {"question": "2.1", "points": 14}]"""

    content = _call_vision(image_path, prompt, max_tokens=1024)
    if not content:
        return None
    import re
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r'\[[\s\S]*\]', content)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None
