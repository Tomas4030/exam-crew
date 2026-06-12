"""LLM prompts for the criteria pipeline.

Used as a fallback for legacy scanned PDFs whose native text layer is
corrupted (typically 2008-2014), and as the primary extractor for subjects
whose criteria don't follow the Grupo I/II/III layout (Matemática, FQ,
línguas estrangeiras…).
"""

CRITERIA_VISION_PROMPT = """Analisa esta página de um documento oficial de CRITÉRIOS DE CLASSIFICAÇÃO de um exame nacional (Portugal).

A tua tarefa é extrair os critérios oficiais por item. NÃO inventes respostas. NÃO completes critérios em falta. NÃO reescrevas o critério com palavras tuas no campo rawText.

Para cada item de classificação identificado nesta página, devolve:
- grupo: grupo oficial se o exame tiver grupos ("GRUPO I", "GRUPO II", "GRUPO III"). Se o exame NÃO tiver grupos (ex.: Matemática, Física e Química, Inglês — itens numerados de forma contínua 1, 2, 3…), devolve null.
- numero: número puro do item ("1", "1.1", "2", "7.2").
- points: cotação máxima do item, em pontos (inteiro). Null se não aparecer nesta página.
- type: "multiple_choice", "open_answer", "calculation", "essay" ou "unknown".
- rawText: transcrição literal do critério correspondente a este item, tal como aparece (incluindo etapas de resolução e cotações parciais, se existirem).
- correctAnswer: só para escolha múltipla; a letra correta (A/B/C/D). Se houver Versão 1 e Versão 2, devolve {"v1": "D", "v2": "B"}. Null caso contrário.
- contentTopics: lista de tópicos de conteúdo exigidos (curtos). [] se não aplicável.
- sourcePage: o número desta página.
- confidence: 0 a 1.

Ignora tabelas gerais de cotações/distribuição no início ou fim do documento — extrai apenas os critérios específicos por item.

Responde APENAS com JSON válido, sem texto fora do JSON:
{"criteriaItems": [{"grupo": null, "numero": "1", "points": 13, "type": "open_answer", "rawText": "...", "correctAnswer": null, "contentTopics": [], "sourcePage": PAGE, "confidence": 0.9}]}"""


def criteria_vision_prompt(page_num: int) -> str:
    return CRITERIA_VISION_PROMPT.replace("PAGE", str(page_num))
