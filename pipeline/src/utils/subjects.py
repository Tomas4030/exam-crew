"""Subject profiles: discipline-specific configuration for the pipeline.

Detection strategy (most → least reliable):
    1. Official 3-digit exam code on the cover ("Prova 639/1.ª Fase") — every
       national exam carries one, and it is unambiguous.
    2. Filename hints (e.g. historia-a.pdf from examesnacionais.com.pt URLs).
    3. Keyword search over cover text / source URL / filename.
"""
import re

SUBJECT_PROFILES = {
    "matematica_a": {
        "examCodes": ["635"],
        "keywords": ["matemática a", "matematica a", "mat a"],
        "has_formula_sheet": True,
        "formula_sheet_hint": "formulário",
        "latex_heavy": True,
        "has_excerpts": False,
        "has_source_grouping": False,
        "question_types": ["multiple_choice", "open_answer", "calculation", "proof", "multi_blank_choice"],
        "normalizers": ["common", "matematica"],
        "crop_profile": "math",
        "preview_profile": "math",
    },
    "matematica_b": {
        "examCodes": ["735"],
        "keywords": ["matemática b", "matematica b"],
        "has_formula_sheet": True,
        "formula_sheet_hint": "formulário",
        "latex_heavy": True,
        "has_excerpts": False,
        "has_source_grouping": False,
        "question_types": ["multiple_choice", "open_answer", "calculation", "multi_blank_choice"],
        "normalizers": ["common", "matematica"],
        "crop_profile": "math",
        "preview_profile": "math",
    },
    "macs": {
        "examCodes": ["835"],
        "keywords": ["matemática aplicada às ciências sociais", "matematica aplicada", "macs"],
        "has_formula_sheet": True,
        "formula_sheet_hint": "formulário",
        "latex_heavy": True,
        "has_excerpts": False,
        "has_source_grouping": False,
        "question_types": ["multiple_choice", "open_answer", "calculation"],
        "normalizers": ["common", "matematica"],
        "crop_profile": "math",
        "preview_profile": "math",
    },
    "fisica_quimica": {
        "examCodes": ["715"],
        "keywords": ["física e química", "fisica e quimica", "fq"],
        "has_formula_sheet": True,
        "formula_sheet_hint": "formulário",
        "latex_heavy": True,
        "has_excerpts": False,
        "has_source_grouping": False,
        "question_types": ["multiple_choice", "open_answer", "calculation", "matching", "multi_blank_choice"],
        "normalizers": ["common", "fisica_quimica"],
        "crop_profile": "physics",
        "preview_profile": "fisica_quimica",
    },
    "portugues": {
        "examCodes": ["639"],
        "keywords": ["português", "portugues"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["multiple_choice", "open_answer", "essay", "short_answer"],
        "normalizers": ["common", "humanities", "portugues"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "literatura_portuguesa": {
        "examCodes": ["732"],
        "keywords": ["literatura portuguesa"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["open_answer", "essay", "short_answer"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "historia_a": {
        "examCodes": ["623"],
        "keywords": ["história a", "historia a"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["document_analysis", "short_answer", "essay", "multi_select"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "historia_b": {
        "examCodes": ["723"],
        "keywords": ["história b", "historia b"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["document_analysis", "short_answer", "essay", "multi_select"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "historia_cultura_artes": {
        "examCodes": ["724"],
        "keywords": ["história da cultura e das artes", "historia da cultura"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["document_analysis", "short_answer", "essay", "multiple_choice"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "biologia_geologia": {
        "examCodes": ["702"],
        "keywords": ["biologia e geologia", "biologia"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": False,
        "has_source_grouping": False,
        "question_types": ["multiple_choice", "open_answer", "classification", "ordering"],
        "normalizers": ["common", "fisica_quimica"],
        "crop_profile": "physics",
        "preview_profile": "fisica_quimica",
    },
    "geografia_a": {
        "examCodes": ["719"],
        "keywords": ["geografia a", "geografia"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["multiple_choice", "open_answer", "document_analysis"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "filosofia": {
        "examCodes": ["714"],
        "keywords": ["filosofia"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["multiple_choice", "open_answer", "essay"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "economia_a": {
        "examCodes": ["712"],
        "keywords": ["economia a", "economia"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": False,
        "question_types": ["multiple_choice", "open_answer", "calculation"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "geometria_descritiva": {
        "examCodes": ["708"],
        "keywords": ["geometria descritiva"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": False,
        "has_source_grouping": False,
        "question_types": ["open_answer", "construction"],
        "normalizers": ["common"],
        "crop_profile": "math",
        "preview_profile": "math",
    },
    "desenho_a": {
        "examCodes": ["706"],
        "keywords": ["desenho a"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": False,
        "has_source_grouping": False,
        "question_types": ["open_answer", "practical"],
        "normalizers": ["common"],
        "crop_profile": "auto",
        "preview_profile": "auto",
    },
    "ingles": {
        "examCodes": ["550"],
        "keywords": ["inglês", "ingles", "english"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["multiple_choice", "open_answer", "short_answer", "essay", "matching"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "frances": {
        "examCodes": ["517"],
        "keywords": ["francês", "frances", "français"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["multiple_choice", "open_answer", "short_answer", "essay"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "espanhol": {
        "examCodes": ["547"],
        "keywords": ["espanhol", "español"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["multiple_choice", "open_answer", "short_answer", "essay"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "alemao": {
        "examCodes": ["501"],
        "keywords": ["alemão", "alemao", "deutsch"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["multiple_choice", "open_answer", "short_answer", "essay"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "latim_a": {
        "examCodes": ["734"],
        "keywords": ["latim a", "latim"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["open_answer", "short_answer", "translation"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "unknown": {
        "examCodes": [],
        "keywords": [],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": False,
        "has_source_grouping": False,
        "question_types": ["multiple_choice", "open_answer"],
        "normalizers": ["common"],
        "crop_profile": "auto",
        "preview_profile": "auto",
    },
}

# code → subject key, built once from the profiles.
CODE_TO_SUBJECT: dict[str, str] = {
    code: key
    for key, profile in SUBJECT_PROFILES.items()
    for code in profile.get("examCodes", [])
}

# "Prova 639", "Prova 639/1.ª Fase", "Prova Escrita de Português 639/2.ª F." —
# the cover always carries "Prova <código>" with the official 3-digit code.
_EXAM_CODE_RE = re.compile(r"\bprova\s+(?:escrita\s+de\s+[^\d]{0,60}?)?(\d{3})\b", re.IGNORECASE)


def detect_exam_code(text: str) -> str | None:
    """Extract the official 3-digit exam code from cover text, if present."""
    for m in _EXAM_CODE_RE.finditer(text or ""):
        code = m.group(1)
        if code in CODE_TO_SUBJECT:
            return code
    return None


def detect_subject(cover_text: str) -> tuple[str, dict]:
    """Detect subject from cover page text. Returns (subject_key, profile)."""
    text_lower = (cover_text or "").lower()

    # 1) Official exam code — deterministic, always on the cover.
    code = detect_exam_code(text_lower)
    if code:
        key = CODE_TO_SUBJECT[code]
        return key, SUBJECT_PROFILES[key]

    # 2) Filename hints (URLs from examesnacionais.com.pt).
    history_filename_hints = (
        "historia-a.pdf",
        "história-a.pdf",
        "/historia-a",
        "\\historia-a",
        "/historia.pdf",
        "\\historia.pdf",
    )
    if any(hint in text_lower for hint in history_filename_hints):
        return "historia_a", SUBJECT_PROFILES["historia_a"]

    # 3) Keywords — longest match wins so "matemática a" beats "matemática".
    best: tuple[int, str] | None = None
    for key, profile in SUBJECT_PROFILES.items():
        if key == "unknown":
            continue
        for kw in profile["keywords"]:
            if kw in text_lower and (best is None or len(kw) > best[0]):
                best = (len(kw), key)
    if best:
        return best[1], SUBJECT_PROFILES[best[1]]

    # 4) Bare 3-digit code anywhere (legacy behaviour, e.g. "639" in a URL).
    for code_value, key in CODE_TO_SUBJECT.items():
        if code_value in text_lower:
            return key, SUBJECT_PROFILES[key]

    return "unknown", SUBJECT_PROFILES["unknown"]


def is_formula_page(page_text: str, profile: dict) -> bool:
    """Detect if a page is a formula sheet based on profile."""
    if not profile.get("has_formula_sheet"):
        return False
    hint = profile.get("formula_sheet_hint", "formulário")
    text_lower = page_text.lower()

    # Formula pages typically have "formulário" or related keywords
    formula_hints = [hint, "formulario", "fórmulas", "formulas", "tabela trigonométrica",
                     "tabela de derivadas", "limites notáveis", "regras de derivação"]
    has_hint = any(h in text_lower for h in formula_hints)

    # Also detect by content pattern: lots of math symbols, few question numbers
    has_questions = bool(re.search(r'^\s*\d{1,2}\.\s', page_text, re.MULTILINE))
    # High density of math symbols suggests formula page
    math_symbols = sum(1 for c in page_text if c in '²³√∫πθ≥≤∈∞→±×÷∆αβγδεφλμσω')
    is_symbol_dense = math_symbols > 15 and not has_questions

    return (has_hint and not has_questions) or is_symbol_dense
