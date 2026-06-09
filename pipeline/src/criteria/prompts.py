"""LLM prompts for the criteria pipeline.

Used only as a fallback for legacy scanned PDFs whose native text layer is
corrupted (typically 2008-2014). Modern PDFs are parsed deterministically from
native text, so these prompts should rarely fire.
"""

CRITERIA_VISION_PROMPT = """Analisa esta página de um documento oficial de CRITÉRIOS DE CLASSIFICAÇÃO de um exame nacional de Português (Portugal).

A tua tarefa é extrair os critérios oficiais por item. NÃO inventes respostas. NÃO completes critérios em falta. NÃO reescrevas o critério com palavras tuas no campo rawText.

Para cada item de classificação identificado nesta página, devolve:
- grupo: grupo oficial ("GRUPO I", "GRUPO II", "GRUPO III").
- numero: número puro do item ("1", "1.1", "2").
- points: cotação máxima do item, em pontos (inteiro). Null se não aparecer nesta página.
- type: "multiple_choice", "open_answer", "essay" ou "unknown".
- rawText: transcrição literal do critério correspondente a este item, tal como aparece.
- correctAnswer: só para escolha múltipla; a letra correta (A/B/C/D). Se houver Versão 1 e Versão 2, devolve {"v1": "D", "v2": "B"}. Null caso contrário.
- contentTopics: lista de tópicos de conteúdo exigidos (curtos). [] se não aplicável.
- sourcePage: o número desta página.
- confidence: 0 a 1.

Responde APENAS com JSON válido, sem texto fora do JSON:
{"criteriaItems": [{"grupo": "GRUPO I", "numero": "1", "points": 13, "type": "open_answer", "rawText": "...", "correctAnswer": null, "contentTopics": [], "sourcePage": PAGE, "confidence": 0.9}]}"""


def criteria_vision_prompt(page_num: int) -> str:
    return CRITERIA_VISION_PROMPT.replace("PAGE", str(page_num))
