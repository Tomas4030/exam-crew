"""Subject profiles: discipline-specific configuration for the pipeline."""

SUBJECT_PROFILES = {
    "matematica_a": {
        "keywords": ["matemática a", "matematica a", "mat a", "635"],
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
    "fisica_quimica": {
        "keywords": ["física e química", "fisica e quimica", "fq", "715"],
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
        "keywords": ["português", "portugues", "639"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["multiple_choice", "open_answer", "essay", "short_answer"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "historia_a": {
        "keywords": ["história a", "historia a", "623"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["document_analysis", "short_answer", "essay", "multi_select"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "biologia_geologia": {
        "keywords": ["biologia e geologia", "biologia", "702"],
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
        "keywords": ["geografia a", "geografia", "719"],
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
        "keywords": ["filosofia", "714"],
        "has_formula_sheet": False,
        "latex_heavy": False,
        "has_excerpts": True,
        "has_source_grouping": True,
        "question_types": ["multiple_choice", "open_answer", "essay"],
        "normalizers": ["common", "humanities"],
        "crop_profile": "auto",
        "preview_profile": "humanities",
    },
    "unknown": {
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


def detect_subject(cover_text: str) -> tuple[str, dict]:
    """Detect subject from cover page text. Returns (subject_key, profile)."""
    text_lower = cover_text.lower()
    for key, profile in SUBJECT_PROFILES.items():
        if key == "unknown":
            continue
        for kw in profile["keywords"]:
            if kw in text_lower:
                return key, profile
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
    import re
    has_questions = bool(re.search(r'^\s*\d{1,2}\.\s', page_text, re.MULTILINE))
    # High density of math symbols suggests formula page
    math_symbols = sum(1 for c in page_text if c in '²³√∫πθ≥≤∈∞→±×÷∆αβγδεφλμσω')
    is_symbol_dense = math_symbols > 15 and not has_questions

    return (has_hint and not has_questions) or is_symbol_dense
