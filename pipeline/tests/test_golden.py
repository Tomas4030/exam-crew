"""Pytest wrapper for the golden-set regression check.

Run with:
    uv run python -m pytest tests/test_golden.py -q
"""
from .golden_tool import check


def test_criteria_golden_set():
    failures = check(verbose=False)
    assert not failures, "\n".join(failures)
