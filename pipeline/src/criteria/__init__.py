"""Official classification-criteria pipeline (Phase 2).

Separate from the exam-statement extraction pipeline. Takes an already-processed
exam (data/output/{exam_id}.json) plus the official *Critérios de Classificação*
PDF and produces data/output/{exam_id}.criteria.json:

    criteria.pdf -> extract -> parse -> match to questions -> audit -> criteria.json

Keep this module's contract narrow: fidelity to the official document. Do NOT
generate answers or pedagogy here (that is the corrections module).
"""

__all__ = ["build_criteria"]


def build_criteria(*args, **kwargs):  # lazy re-export to avoid import cycles
    from .run import build_criteria as _impl
    return _impl(*args, **kwargs)
