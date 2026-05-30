from pathlib import Path
import re

ROOT = Path.cwd()
NORMALIZER = ROOT / "pipeline" / "src" / "utils" / "normalizer.py"
PREVIEW = ROOT / "src" / "app" / "exams" / "[id]" / "preview" / "page.tsx"


def backup(path: Path):
    bak = path.with_suffix(path.suffix + ".bak_q9_v2")
    if not bak.exists():
        bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return bak


def patch_normalizer():
    text = NORMALIZER.read_text(encoding="utf-8")
    backup(NORMALIZER)

    # 1) After recovering subquestions from native PDF text, run the structural repairs again.
    marker = '    _recover_numbered_subquestions(output, extraction)\n    questions = output.get("questions", [])  # refresh after recovery\n'
    if marker in text and '    _detect_and_parse_matching(questions)  # after recovery\n' not in text:
        text = text.replace(marker, marker + '    _detect_and_parse_matching(questions)  # after recovery\n', 1)

    if '    _repair_q9_group_and_children(output)\n' not in text:
        anchor = '    # ── 1a.1. Keep recovered group parents clean ──────────────────\n    _trim_group_parent_statements(output)\n'
        if anchor in text:
            text = text.replace(anchor, anchor + '    _repair_q9_group_and_children(output)\n', 1)
        else:
            text = text.replace('    _repair_multiblank_options_from_statement(output)\n', '    _repair_q9_group_and_children(output)\n    _repair_multiblank_options_from_statement(output)\n', 1)

    if 'def _repair_q9_group_and_children' not in text:
        helper = r'''

def _clean_exam_text_prefix(text: str, number: str) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r'^\s*' + re.escape(str(number)) + r'\.?\s*', '', text.strip()).strip()


def _repair_q9_group_and_children(output: dict):
    """Robust cleanup for group questions such as FQ 2025 Q9.

    The parent should contain only the common introduction/equilibrium equation.
    The children own their own interactions:
      - 9.1: matching COLUNA I/COLUNA II
      - 9.2: calculation
      - 9.3: multi_blank_choice with Figura 6
    """
    questions = output.get("questions", [])
    by_num = {str(q.get("number", "")).strip(): q for q in questions}
    by_id = {q.get("questionId"): q for q in questions}

    for parent in questions:
        children_ids = parent.get("subQuestions") or []
        children = [by_id[cid] for cid in children_ids if cid in by_id]
        if not children:
            continue

        parent_num = str(parent.get("number", "")).strip()
        if not parent_num:
            continue

        # Prefer rawText for group intro if it is shorter/cleaner than statement.
        raw = _clean_exam_text_prefix(parent.get("rawText") or "", parent_num)
        stmt = parent.get("statement") or ""
        if raw and len(raw) >= 20:
            bad_markers = ["COLUNA I", "COLUNA II", "Complete o texto", "Figura 6 apresenta", "a)", "b)", "c)", "d)"]
            if any(m.lower() in stmt.lower() for m in bad_markers) and len(raw) < len(stmt):
                for field in ("statement", "statementPlain", "statementRaw", "statementLatex", "statementFormatted", "statementPlainFormatted", "statementLatexFormatted"):
                    if field in parent:
                        parent[field] = raw

        # Extra fallback: if child starts are inside parent statement, cut before the first one.
        stmt = parent.get("statement") or ""
        cut_positions = []
        for child in children:
            cnum = str(child.get("number", ""))
            child_stmt = child.get("statement") or child.get("rawText") or ""
            patterns = []
            if cnum:
                patterns.append(r'\b' + re.escape(cnum) + r'\.?\s')
            if child_stmt:
                first_words = " ".join(child_stmt.split()[:8])
                if len(first_words) > 20:
                    patterns.append(re.escape(first_words))
            for pat in patterns:
                m = re.search(pat, stmt, flags=re.I)
                if m and m.start() > 20:
                    cut_positions.append(m.start())
        if cut_positions:
            trimmed = stmt[:min(cut_positions)].strip()
            if len(trimmed) >= 20:
                for field in ("statement", "statementPlain", "statementRaw", "statementLatex", "statementFormatted", "statementPlainFormatted", "statementLatexFormatted"):
                    val = parent.get(field)
                    if isinstance(val, str) and len(val) > len(trimmed):
                        parent[field] = trimmed

        # Group parents should not render direct assets/tables. Children own them.
        parent["imageRefs"] = []
        parent["tableRefs"] = []
        parent["assetRefs"] = []
        parent["visualDependency"] = False
        parent["hasTable"] = False
        parent["hasGraph"] = False
        parent["hasDiagram"] = False

    # Specific child repairs that are general enough for COLUNA and multi_blank questions.
    for q in questions:
        text = (q.get("statement") or q.get("rawText") or "")
        low = text.lower()

        # COLUNA I / COLUNA II must be rendered as matching, not textarea.
        if re.search(r'\bCOLUNA\s+I\b', text, re.I) and re.search(r'\bCOLUNA\s+II\b', text, re.I):
            q["type"] = "matching"
            q["options"] = []
            q["blanks"] = None
            left_items = re.findall(r'\(([a-e])\)\s*([^\n(]+)', text, flags=re.I)
            right_items = re.findall(r'\((\d+)\)\s*([^\n(]+)', text)

            def uniq(items):
                seen = set(); out = []
                for k, v in items:
                    k = str(k).strip()
                    v = " ".join(str(v).replace("\u0007", "").split()).strip()
                    if not k or not v or k in seen:
                        continue
                    seen.add(k)
                    out.append({"key": k, "text": v})
                return out

            left = uniq(left_items)
            right = uniq(right_items)
            if left and right:
                q["matchColumns"] = {"left": left, "right": right}
            q["imageRefs"] = []
            q["tableRefs"] = []
            q["assetRefs"] = []

        # Multi-blank questions: keep choices in q['blanks'], not duplicated in statement.
        if q.get("type") == "multi_blank_choice" and q.get("blanks"):
            for field in ("statement", "statementPlain", "statementRaw", "statementLatex", "rawText", "statementFormatted", "statementPlainFormatted", "statementLatexFormatted"):
                val = q.get(field)
                if not isinstance(val, str):
                    continue
                # Remove tail beginning at the a)/b)/c)/d) option table.
                m = re.search(r'\n\s*a\)\s*\n\s*b\)\s*\n\s*c\)\s*\n\s*d\)?\s*\n', val, flags=re.I)
                if m:
                    q[field] = val[:m.start()].rstrip()

        # Ensure Figure 6 only remains on the child that explicitly mentions it on the same page.
        if str(q.get("number")) in {"9", "9.1", "9.2"}:
            for fld in ("imageRefs", "assetRefs"):
                q[fld] = [r for r in (q.get(fld) or []) if not str(r).startswith("figura_6")]
            q["tableRefs"] = [r for r in (q.get("tableRefs") or []) if not str(r).startswith("tabela_p12")]
        if str(q.get("number")) == "9.3":
            q.setdefault("imageRefs", [])
            q.setdefault("assetRefs", [])
            if "figura_6_p13" not in q["imageRefs"]:
                q["imageRefs"].append("figura_6_p13")
            if "figura_6_p13" not in q["assetRefs"]:
                q["assetRefs"].append("figura_6_p13")

'''
        text = text.replace('\ndef _strip_figure_axis_noise', helper + '\ndef _strip_figure_axis_noise')

    NORMALIZER.write_text(text, encoding="utf-8")


def patch_preview():
    text = PREVIEW.read_text(encoding="utf-8")
    backup(PREVIEW)

    if "matchColumns?:" not in text:
        text = text.replace(
            "hasOptionImages?: boolean;",
            "hasOptionImages?: boolean;\n  matchColumns?: { left: { key: string; text: string }[]; right: { key: string; text: string }[] };"
        )

    # Use a safer parent context: raw intro only, never the bloated parent statement.
    old_context = "  // Parent context text (combined from all ancestors)\n  const ancestorContext = getAncestors(current)\n    .map(a => a.statement)\n    .filter(Boolean)\n    .join('\\n\\n');\n"
    new_context = '''  const cleanParentContext = (a: Question): string => {
    const raw = (a as any).rawText || '';
    const stmt = a.statement || '';
    const text = raw && raw.length < stmt.length ? raw : stmt;
    const firstChild = data.questions
      .filter(q => q.parentQuestion === a.questionId)
      .sort((x, y) => String(x.number).localeCompare(String(y.number), undefined, { numeric: true }))[0];
    if (!firstChild) return text;
    const childStart = (firstChild.statement || '').split(/\\s+/).slice(0, 8).join(' ');
    if (childStart.length > 20) {
      const idx = text.toLowerCase().indexOf(childStart.toLowerCase());
      if (idx > 20) return text.slice(0, idx).trim();
    }
    return text;
  };

  // Parent context text (combined from all ancestors)
  const ancestorContext = getAncestors(current)
    .map(cleanParentContext)
    .filter(Boolean)
    .join('\\n\\n');
'''
    if old_context in text:
        text = text.replace(old_context, new_context)

    if "const parseMatchingColumns" not in text:
        helper = '''
  const parseMatchingColumns = (q: Question) => {
    if (q.matchColumns?.left?.length && q.matchColumns?.right?.length) return q.matchColumns;
    const text = `${q.statement || ''}\\n${q.statementPlain || ''}`;
    if (!/COLUNA\\s+I/i.test(text) || !/COLUNA\\s+II/i.test(text)) return null;
    const leftMatches = [...text.matchAll(/\\(([a-e])\\)\\s*([^\\n(]+)/gi)];
    const rightMatches = [...text.matchAll(/\\((\\d+)\\)\\s*([^\\n(]+)/g)];
    const uniq = (items: {key:string;text:string}[]) => {
      const seen = new Set<string>();
      return items.filter(item => {
        if (!item.key || seen.has(item.key)) return false;
        seen.add(item.key);
        return true;
      });
    };
    const left = uniq(leftMatches.map(m => ({ key: m[1], text: m[2].replace(/\\u0007/g, '').trim() })));
    const right = uniq(rightMatches.map(m => ({ key: m[1], text: m[2].replace(/\\u0007/g, '').trim() })));
    return left.length && right.length ? { left, right } : null;
  };

  const currentMatching = parseMatchingColumns(current);
'''
        text = text.replace("  const images = getAllImages(current);\n", "  const images = getAllImages(current);\n" + helper)

    # Render matching even when the JSON type is still open_answer.
    old = "            {current.type === 'multi_blank_choice' && current.blanks?.length ? ("
    new_render = """            {currentMatching ? (
              <div className="rounded-lg border bg-white p-4 space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <div className="text-sm font-semibold text-gray-700 mb-2">Coluna I</div>
                    <div className="space-y-2">
                      {currentMatching.left.map(item => {
                        const key = `${current.questionId}_${item.key}`;
                        return (
                          <label key={item.key} className="flex items-center gap-3 rounded border px-3 py-2">
                            <span className="w-8 font-bold text-blue-700">({item.key})</span>
                            <span className="flex-1"><MathText text={item.text} /></span>
                            <select value={answers[key] || ''} onChange={e => setAnswers(prev => ({ ...prev, [key]: e.target.value }))}
                              className="rounded border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900">
                              <option value="">...</option>
                              {currentMatching.right.map(opt => (
                                <option key={opt.key} value={opt.key}>({opt.key})</option>
                              ))}
                            </select>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-gray-700 mb-2">Coluna II</div>
                    <div className="space-y-2">
                      {currentMatching.right.map(item => (
                        <div key={item.key} className="rounded border px-3 py-2 text-sm">
                          <span className="font-bold text-gray-600">({item.key})</span>{' '}
                          <MathText text={item.text} />
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            ) : current.type === 'multi_blank_choice' && current.blanks?.length ? ("""
    if old in text and "currentMatching ?" not in text:
        text = text.replace(old, new_render)

    PREVIEW.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if not NORMALIZER.exists() or not PREVIEW.exists():
        raise SystemExit("Run this script from the exam-crew repository root.")
    patch_normalizer()
    patch_preview()
    print("Applied Q9 matching/preview v2 fix. Backups created with .bak_q9_v2")
