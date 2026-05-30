"""Normalizer: deterministic post-assembly corrections.

Runs BEFORE validator. Fixes things that can be computed from the data itself
without calling the LLM again:
- Reassociate figures by "Figura X" mentions in statements
- Normalize bbox_estimate → bbox
- Propagate calculatorAllowed from parent to children
- Default bbox for tables
- Fix hasDiagram/hasGraph from actual asset types
"""
import re


def normalize(output: dict, extraction: dict | None = None) -> dict:
    """Apply deterministic corrections. Returns corrected output."""
    questions = output.get("questions", [])
    assets = output.get("assets", [])

    # Ensure all questions have required list fields to prevent KeyError
    for q in questions:
        q.setdefault("imageRefs", [])
        q.setdefault("tableRefs", [])
        q.setdefault("assetRefs", [])
        q.setdefault("options", [])
        q.setdefault("warnings", [])
        q.setdefault("subQuestions", [])

    # ── 0. Remove fake questions with Roman numeral numbers ──────
    # These are propositions (I, II, III, IV) inside another question, not real questions
    _remove_roman_numeral_questions(questions)

    # ── 0b. Merge false multi_blank_choice subquestions ───────────
    # When pipeline creates q2 (group) + q2_1/q2_2 (multi_blank_choice),
    # but the real exam has just one question with blanks I/II/III/IV
    _merge_false_multi_blank_groups(output)
    questions = output.get("questions", [])  # refresh after merge

    # ── 0c. Clear statementLatex for multi_blank_choice (no math rendering needed)
    for q in questions:
        if q.get("type") == "multi_blank_choice":
            q["statementLatex"] = None
            q["mathHeavy"] = False

    # ── 0d. Fix multi_blank_choice misclassification ─────────────
    # A question is only multi_blank_choice if it has fill-in-the-blank instructions
    for q in questions:
        if q.get("type") == "multi_blank_choice":
            text = (q.get("statement") or "").lower()
            has_fill_instructions = (
                "complete o texto" in text or
                "a cada espaço" in text or
                "cada um dos números" in text or
                "cada espaço corresponde" in text or
                "opção adequada para cada espaço" in text or
                "selecionando a opção" in text
            )
            if not has_fill_instructions:
                q["type"] = "open_answer"
                q["blanks"] = None
                q["statementLatex"] = None

    # ── 0e. Reassign tables to correct question by position ──────
    # Tables with options (a/b/c/d) belong to multi_blank_choice questions
    _fix_table_assignment(questions, assets)

    # ── 1. Reassociate figures by statement mentions ─────────────
    _repair_figure_associations(questions, assets)
    _repair_table_associations(questions, assets)

    # ── 1a. Recover subquestions missed by the VLM from native PDF text ──
    _recover_numbered_subquestions(output, extraction)
    questions = output.get("questions", [])  # refresh after recovery

    # ── 1a.1. Keep recovered group parents clean ──────────────────
    _trim_group_parent_statements(output)

    # ── 1a.2. Build blanks when a multi_blank_choice was recovered from text ─
    _repair_multiblank_options_from_statement(output)

    # ── 1b. Resolve source group references in questions ─────────
    _resolve_source_refs(questions, output.get("sourceGroups", []))

    # ── 2. Normalize bbox_estimate → bbox ────────────────────────
    for asset in assets:
        if asset.get("bbox_estimate") and not asset.get("bbox"):
            asset["bbox"] = asset["bbox_estimate"]
            asset["bboxSource"] = "estimated"

    # ── 3. Default bbox for tables without any bbox ──────────────
    for asset in assets:
        if asset.get("type") == "table" and not asset.get("bbox") and not asset.get("bbox_estimate"):
            asset["bbox"] = {"x_pct": 5, "y_pct": 20, "w_pct": 90, "h_pct": 30}
            asset["bboxSource"] = "default"

    # ── 4. Propagate calculatorAllowed parent → children ─────────
    parent_map = {q["questionId"]: q for q in questions if q.get("isGroup")}
    for q in questions:
        pid = q.get("parentQuestion")
        if pid and pid in parent_map:
            parent = parent_map[pid]
            # If parent says no calculator, children inherit
            if parent.get("calculatorAllowed") == False:
                q["calculatorAllowed"] = False
            # If child statement says no calculator, propagate up
            stmt = str(q.get("statement", ""))
            if "sem recorrer à calculadora" in stmt.lower() or "sem calculadora" in stmt.lower():
                q["calculatorAllowed"] = False
                parent["calculatorAllowed"] = False

    # ── 5. Recalculate hasDiagram/hasGraph from assetRefs ────────
    asset_map = {a["id"]: a for a in assets}
    for q in questions:
        all_refs = set(q.get("imageRefs", []) + q.get("tableRefs", []) + q.get("assetRefs", []))
        ref_types = [asset_map[r].get("type") for r in all_refs if r in asset_map]
        if any(t == "geometry_diagram" for t in ref_types):
            q["hasDiagram"] = True
        if any(t == "graph" for t in ref_types):
            q["hasGraph"] = True
        if all_refs:
            q["visualDependency"] = True

    return output


def _repair_table_associations(questions: list[dict], assets: list[dict]):
    """Associate table assets to the question they belong to."""
    table_assets = [
        a for a in assets
        if a.get("type") == "table" or "tabela" in str(a.get("id", "")).lower()
    ]
    if not table_assets:
        return

    # Check which tables are already referenced
    all_table_refs = set()
    for q in questions:
        all_table_refs.update(q.get("tableRefs", []))

    by_number = {str(q.get("number", "")).strip(): q for q in questions}
    for asset in table_assets:
        aid = asset.get("id")
        if aid in all_table_refs:
            continue
        page = asset.get("page")
        near = str(asset.get("nearQuestion") or "").strip()

        candidates = []
        if near and near in by_number:
            candidates.append(by_number[near])
        candidates.extend(q for q in questions if q.get("sourcePage") == page and q not in candidates)

        def score(q: dict) -> int:
            text = ((q.get("statement") or "") + " " + (q.get("rawText") or "")).lower()
            s = 0
            if str(q.get("number", "")).strip() == near:
                s += 10
            if "tabela" in text or "medições" in text or "apresentam-se" in text:
                s += 8
            if q.get("type") in ("calculation", "open_answer", "multi_blank_choice"):
                s += 1
            return s

        candidates = [q for q in candidates if q]
        if not candidates:
            continue
        best = max(candidates, key=score)
        if score(best) <= 0:
            continue

        best.setdefault("tableRefs", [])
        best.setdefault("assetRefs", [])
        if aid not in best["tableRefs"]:
            best["tableRefs"].append(aid)
        if aid not in best["assetRefs"]:
            best["assetRefs"].append(aid)
        best["hasTable"] = True
        best["visualDependency"] = True


def _recover_numbered_subquestions(output: dict, extraction: dict | None):
    """Recover missing decimal-number items using native PDF text."""
    if not extraction or not extraction.get("pages"):
        return

    questions = output.get("questions", [])
    existing = {str(q.get("number", "")).strip() for q in questions}
    by_number = {str(q.get("number", "")).strip(): q for q in questions}

    page_texts = {p.get("page"): p.get("text", "") or "" for p in extraction.get("pages", [])}

    found: list[tuple[int, str, str]] = []
    for page in sorted(p for p in page_texts if isinstance(p, int)):
        text = page_texts.get(page, "")
        low = text.lower()
        if not text or page <= 3 or "cotações" in low or "tabela periódica" in low:
            continue
        pattern = re.compile(r'(?m)^\s*(\d+(?:\.\d+)+)\.\s+')
        matches = list(pattern.finditer(text))
        for i, m in enumerate(matches):
            num = m.group(1)
            if num in existing:
                continue
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[start:end].strip()
            chunk = re.split(r'\n\s*(?:Prova\s+\d+|FIM)\b', chunk)[0].strip()
            if len(chunk) >= 40:
                found.append((page, num, chunk))

    if not found:
        return

    def infer_type(chunk: str) -> str:
        low = chunk.lower()
        if "complete o texto" in low or "selecionando a opção" in low:
            return "multi_blank_choice"
        if "(a)" in low and "(d)" in low:
            return "multiple_choice"
        if "determine" in low or "calcule" in low:
            return "calculation"
        return "open_answer"

    def extract_options(chunk: str) -> list[dict]:
        opts = []
        for letter, text in re.findall(r'(?m)^\s*\(([A-D])\)\s+(.+?)(?=\n\s*\([A-D]\)|\Z)', chunk, re.S):
            clean = " ".join(text.split()).strip()
            if clean:
                opts.append({"letter": letter, "text": clean})
        return opts

    added_by_parent: dict[str, list[str]] = {}
    new_questions = []
    for page, num, chunk in found:
        parent_num = num.rsplit(".", 1)[0]
        parent_id = f"q{parent_num.replace('.', '_')}"
        q_id = f"q{num.replace('.', '_')}"
        q_type = infer_type(chunk)
        statement = re.sub(r'^\s*' + re.escape(num) + r'\.\s*', '', chunk).strip()
        opts = extract_options(chunk) if q_type == "multiple_choice" else []

        q = {
            "questionId": q_id,
            "number": num,
            "type": q_type,
            "sourcePage": page,
            "statement": statement,
            "rawText": statement,
            "blanks": None,
            "options": opts,
            "imageRefs": [],
            "tableRefs": [],
            "assetRefs": [],
            "visualDependency": False,
            "confidence": 0.78,
            "needsHumanReview": True,
            "warnings": [{"type": "text_fallback_extracted", "message": f"Q{num} recovered from native PDF text"}],
            "parentQuestion": parent_id if parent_num in by_number else None,
            "subQuestions": [],
            "mathHeavy": bool(re.search(r'[=<>]|mol|Kc|Qc|pH', statement)),
            "hasGraph": bool(re.search(r'gráfico|figura', statement, re.I)),
            "hasDiagram": False,
            "hasTable": False,
            "calculatorAllowed": None,
        }
        new_questions.append(q)
        existing.add(num)
        added_by_parent.setdefault(parent_num, []).append(q_id)

    if not new_questions:
        return

    questions.extend(new_questions)

    for parent_num, child_ids in added_by_parent.items():
        parent = by_number.get(parent_num)
        if not parent:
            continue
        parent["isGroup"] = True
        parent["type"] = "group"
        parent.setdefault("subQuestions", [])
        for cid in child_ids:
            if cid not in parent["subQuestions"]:
                parent["subQuestions"].append(cid)


def _trim_group_parent_statements(output: dict):
    """Remove child-question text accidentally swallowed by group parents."""
    questions = output.get("questions", [])
    by_id = {q.get("questionId"): q for q in questions}

    for parent in questions:
        children_ids = parent.get("subQuestions") or []
        if not children_ids:
            continue
        children = [by_id[cid] for cid in children_ids if cid in by_id]
        if not children:
            continue
        children.sort(key=lambda q: tuple(
            int(p) if p.isdigit() else 999 for p in str(q.get("number", "")).split(".")
        ))
        first = children[0]

        parent_stmt = (parent.get("statement") or "").strip()
        child_stmt = (first.get("statement") or "").strip()
        if not parent_stmt or not child_stmt:
            continue

        prefix = re.sub(r"\s+", " ", child_stmt[:120]).strip()
        parent_flat = re.sub(r"\s+", " ", parent_stmt)
        pos_flat = parent_flat.find(prefix[:60])
        if pos_flat <= 20:
            continue

        # Map flat position back to original
        count = 0
        cut = None
        for i, ch in enumerate(parent_stmt):
            if not ch.isspace():
                count += 1
            if count >= len(re.sub(r"\s+", "", parent_flat[:pos_flat])):
                cut = i
                break
        if cut is None:
            continue

        trimmed = parent_stmt[:cut].strip()
        trimmed = re.sub(r"\s*\d+(?:\.\d+)+\.\s*$", "", trimmed).strip()
        if len(trimmed) >= 30 and len(trimmed) < len(parent_stmt):
            parent.setdefault("statementRaw", parent_stmt)
            parent["statement"] = trimmed
            parent["statementPlain"] = trimmed
            if parent.get("statementLatex"):
                parent["statementLatex"] = None
            parent["tableRefs"] = []
            parent["imageRefs"] = []
            parent["assetRefs"] = []


def _repair_multiblank_options_from_statement(output: dict):
    """Build blanks for multi_blank_choice items when options are in text."""
    for q in output.get("questions", []):
        if q.get("type") != "multi_blank_choice" or q.get("blanks"):
            continue
        text = q.get("statement") or ""
        if not re.search(r"\ba\)\s*b\)\s*c\)", text, re.IGNORECASE | re.DOTALL):
            continue

        header_match = re.search(r"\ba\)\s*b\)\s*c\)\s*d\)?", text, re.IGNORECASE | re.DOTALL)
        tail = text[header_match.end():] if header_match else text
        pairs = re.findall(r"(?m)^\s*([1-5])\.\s+(.+?)(?=\n\s*[1-5]\.\s+|\Z)", tail.strip())
        if len(pairs) < 6:
            continue

        groups: list[list[dict]] = []
        current: list[dict] = []
        last_num = 0
        for num, opt_text in pairs:
            n = int(num)
            if n == 1 and current:
                groups.append(current)
                current = []
            elif current and n <= last_num:
                groups.append(current)
                current = []
            current.append({"letter": num, "text": opt_text.strip()})
            last_num = n
        if current:
            groups.append(current)

        if not groups:
            continue

        letters = ["a", "b", "c", "d"]
        while len(groups) < 4 and groups:
            groups.append(groups[-1])

        q["blanks"] = [
            {"number": letters[i], "options": groups[i]}
            for i in range(min(4, len(groups)))
            if groups[i]
        ]
        if q["blanks"]:
            q["hasTable"] = False
            q["tableRefs"] = []


def _repair_figure_associations(questions: list[dict], assets: list[dict]):
    """Reassociate figures based on 'Figura X' mentions in question statements.

    Logic:
    - For each question, find which figures it mentions (Figura 1, Figura 2, etc.)
    - For each asset that is a figure, find which questions mention it
    - Fix nearQuestion on the asset
    - Fix imageRefs on questions (remove wrong, add correct)
    """
    # Build figure mention map: question → set of figure numbers mentioned
    q_mentions: dict[str, set[str]] = {}
    for q in questions:
        text = (q.get("statement") or "") + " " + (q.get("rawText") or "")
        fig_nums = set(re.findall(r'[Ff]igura\s+(\d+)', text))
        if fig_nums:
            q_mentions[q["questionId"]] = fig_nums

    # Build asset lookup: figure_number → asset(s)
    fig_assets: dict[str, list[dict]] = {}
    for asset in assets:
        match = re.match(r'figura_(\d+)', asset["id"])
        if match:
            fig_assets.setdefault(match.group(1), []).append(asset)

    # For each figure asset, find the correct question(s) that mention it
    for fig_num, asset_list in fig_assets.items():
        # Find questions that mention this figure
        mentioning_qs = [qid for qid, mentions in q_mentions.items() if fig_num in mentions]

        for asset in asset_list:
            aid = asset["id"]

            # Fix nearQuestion on asset
            if mentioning_qs:
                # Use the question number (not ID) of the first mentioning question
                for q in questions:
                    if q["questionId"] in mentioning_qs:
                        asset["nearQuestion"] = q["number"]
                        break

            # Remove this asset from questions that DON'T mention it
            for q in questions:
                if q["questionId"] in mentioning_qs:
                    continue
                # Remove from imageRefs if wrongly assigned
                if aid in q.get("imageRefs", []):
                    q["imageRefs"].remove(aid)
                if aid in q.get("assetRefs", []):
                    q["assetRefs"].remove(aid)

            # Add to questions that DO mention it
            for q in questions:
                if q["questionId"] not in mentioning_qs:
                    continue
                if aid not in q.get("imageRefs", []):
                    q.setdefault("imageRefs", []).append(aid)
                if aid not in q.get("assetRefs", []):
                    q.setdefault("assetRefs", []).append(aid)
                q["visualDependency"] = True



_ROMAN_NUMERALS = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}


def _remove_roman_numeral_questions(questions: list[dict]):
    """Remove questions whose number is a Roman numeral (I, II, III...).

    These are propositions inside multi_blank_choice questions (e.g. Q13),
    not real standalone questions. Remove them from the list in-place.
    """
    to_remove = []
    for i, q in enumerate(questions):
        num = q.get("number", "").strip()
        if num.upper() in _ROMAN_NUMERALS and not q.get("parentQuestion"):
            to_remove.append(i)

    # Remove in reverse order to preserve indices
    for i in reversed(to_remove):
        questions.pop(i)


def _resolve_source_refs(questions: list[dict], source_groups: list[dict]):
    """Resolve remaining textual references (documento X, imagem B) to sourceRefs.

    This complements source_grouping.py — catches any references that the
    source_grouping step might have missed (e.g. questions added during retry).
    """
    if not source_groups:
        return

    # Build lookup
    group_by_doc_num: dict[str, dict] = {}
    for sg in source_groups:
        num_match = re.search(r'(\d+)', sg.get("label", ""))
        if num_match:
            group_by_doc_num[num_match.group(1)] = sg

    for q in questions:
        # Skip if already has sourceRefs
        if q.get("sourceRefs"):
            continue

        text = (q.get("statement") or "") + " " + (q.get("rawText") or "")
        if not text.strip():
            continue

        # Check for document references
        doc_nums = re.findall(r'[Dd]ocumento\s+(\d+)', text)
        doc_nums += re.findall(r'[Dd]oc\.?\s*(\d+)', text)

        source_refs = []
        for doc_num in set(doc_nums):
            sg = group_by_doc_num.get(doc_num)
            if not sg:
                continue

            # Check for specific child references
            child_letters = re.findall(r'[Ii]magem\s+([A-Z])', text, re.IGNORECASE)
            child_letters += re.findall(r'[Ff]igura\s+([A-Z])', text, re.IGNORECASE)
            child_letters = list(set(c.upper() for c in child_letters))

            if child_letters:
                for letter in child_letters:
                    child_id = _find_child_in_group(sg, letter)
                    if child_id:
                        source_refs.append({"sourceId": sg["id"], "childId": child_id, "mode": "specific_child"})
                        if child_id not in q.get("assetRefs", []):
                            q.setdefault("assetRefs", []).append(child_id)
            else:
                source_refs.append({"sourceId": sg["id"], "childId": None, "mode": "full_group"})

            if sg["id"] not in q.get("assetRefs", []):
                q.setdefault("assetRefs", []).append(sg["id"])

        if source_refs:
            q["sourceRefs"] = source_refs


def _find_child_in_group(source_group: dict, letter: str) -> str | None:
    """Find a child ID by letter in a source group."""
    letter_lower = letter.lower()
    for child_id in source_group.get("children", []):
        if f"_{letter_lower}_" in child_id or child_id.endswith(f"_{letter_lower}"):
            return child_id
    return None


def _merge_false_multi_blank_groups(output: dict):
    """Merge false group+subquestion splits for multi_blank_choice questions.

    When the pipeline creates q2(group) + q2_1(multi_blank_choice) + q2_2(multi_blank_choice),
    but the real exam has just one question 2 with blanks I/II/III/IV, merge them back.
    """
    questions = output.get("questions", [])
    by_id = {q["questionId"]: q for q in questions}
    to_remove = set()

    for q in questions:
        if not q.get("isGroup"):
            continue
        children_ids = q.get("subQuestions") or []
        children = [by_id[cid] for cid in children_ids if cid in by_id]
        if not children:
            continue

        # Check if children are multi_blank_choice with blanks
        mb_children = [c for c in children if c.get("type") == "multi_blank_choice" and c.get("blanks")]
        if not mb_children:
            continue

        # Only merge if parent number has no decimal (real subquestions are 2.1, 2.2)
        if "." in str(q.get("number", "")):
            continue

        # Merge: promote first child's blanks into parent, remove children
        first = mb_children[0]
        q["type"] = "multi_blank_choice"
        q["isGroup"] = False
        q["subQuestions"] = []
        q["blanks"] = first.get("blanks")
        q["options"] = []
        q["tableRefs"] = first.get("tableRefs") or q.get("tableRefs", [])
        q["assetRefs"] = first.get("assetRefs") or q.get("assetRefs", [])
        q["hasTable"] = first.get("hasTable") or q.get("hasTable", False)

        # Merge statement if parent is just intro
        parent_stmt = (q.get("statement") or "").strip()
        child_stmt = (first.get("statement") or "").strip()
        if child_stmt and child_stmt not in parent_stmt:
            q["statement"] = f"{parent_stmt}\n\n{child_stmt}".strip()
        q["statementLatex"] = None
        q["statementPlain"] = q["statement"]

        for child in children:
            to_remove.add(child["questionId"])

    output["questions"] = [q for q in questions if q["questionId"] not in to_remove]


def _fix_table_assignment(questions: list[dict], assets: list[dict]):
    """Fix option-table assignment. Catches clones and 1./2./3. format."""

    def _is_real_multi_blank(q: dict) -> bool:
        text = (q.get("statement") or q.get("rawText") or "").lower()
        return (
            "complete o texto" in text or
            "cada espaço" in text or
            "opção adequada" in text or
            "selecionando a opção" in text or
            "corresponde à opção" in text
        )

    def _is_options_table(asset: dict) -> bool:
        # Check rows content
        rows = asset.get("rows") or []
        if rows:
            text = " ".join(
                str(c) for row in rows
                for c in (row.values() if isinstance(row, dict) else row)
            ).lower()
            has_letters = ("a)" in text and "b)" in text) or ("a)" in text and "c)" in text)
            has_numbers = ("1." in text and "2." in text) or ("1)" in text and "2)" in text)
            if has_letters or has_numbers:
                return True
        # Check columns for a)/b)/c)/d) headers
        cols = [str(c).lower().strip() for c in (asset.get("columns") or [])]
        if any("a)" in c or "b)" in c or "c)" in c for c in cols):
            return True
        return False

    # Collect option table IDs + prefixes for clone detection
    option_table_ids: set[str] = set()
    table_prefixes: set[str] = set()

    for asset in assets:
        aid = asset.get("id", "")
        if not ("tabela" in aid.lower() or asset.get("type") == "table"):
            continue
        if _is_options_table(asset):
            option_table_ids.add(aid)
            m = re.match(r'^(tabela_p\d+)', aid.lower())
            if m:
                table_prefixes.add(m.group(1))

    # Catch ALL clones by prefix (tabela_p12_12, tabela_p12_abc, etc.)
    for asset in assets:
        aid = asset.get("id", "")
        aid_lower = aid.lower()
        for prefix in table_prefixes:
            if aid_lower == prefix or aid_lower.startswith(prefix + "_"):
                option_table_ids.add(aid)

    if not option_table_ids:
        return

    # Remove from all non-fill-blank questions
    for q in questions:
        if _is_real_multi_blank(q):
            continue
        for field in ("assetRefs", "tableRefs", "imageRefs"):
            refs = q.get(field) or []
            if any(r in option_table_ids for r in refs):
                q[field] = [r for r in refs if r not in option_table_ids]

    # Assign to the correct fill-blank question on the same page
    for asset in assets:
        aid = asset.get("id", "")
        if aid not in option_table_ids:
            continue
        page = asset.get("page")
        candidates = [q for q in questions if q.get("sourcePage") == page and _is_real_multi_blank(q)]
        if candidates:
            owner = candidates[0]
            owner.setdefault("tableRefs", [])
            owner.setdefault("assetRefs", [])
            if aid not in owner["tableRefs"]:
                owner["tableRefs"].append(aid)
            if aid not in owner["assetRefs"]:
                owner["assetRefs"].append(aid)
