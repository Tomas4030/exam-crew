"""Valida output do question splitter."""
import json


def validate_questions(output: str) -> bool:
    try:
        questions = json.loads(output)
        assert isinstance(questions, list), "Output must be a list"
        for q in questions:
            assert "number" in q, f"Missing 'number' in question"
            assert "text" in q, f"Missing 'text' in question {q.get('number')}"
            assert "type" in q, f"Missing 'type' in question {q.get('number')}"
            valid_types = ["multiple_choice", "true_false", "open", "matching"]
            assert q["type"] in valid_types, f"Invalid type: {q['type']}"
            if q["type"] == "multiple_choice":
                assert "options" in q and len(q["options"]) >= 2, f"Q{q['number']}: needs >=2 options"
        print(f"✓ {len(questions)} questions validated OK")
        return True
    except (json.JSONDecodeError, AssertionError) as e:
        print(f"✗ Validation failed: {e}")
        return False


if __name__ == "__main__":
    sample = json.dumps([
        {"number": 1, "text": "Qual é a capital?", "type": "multiple_choice",
         "options": [{"letter": "A", "text": "Lisboa"}, {"letter": "B", "text": "Porto"}]},
        {"number": 2, "text": "O sol é uma estrela.", "type": "true_false"},
    ])
    validate_questions(sample)
