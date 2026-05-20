"""Testa comunicação com OpenRouter."""
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

import httpx


def test_openrouter():
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    assert api_key, "OPENROUTER_API_KEY not set"

    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "google/gemini-2.0-flash-exp:free",
            "messages": [{"role": "user", "content": "Diz apenas 'OK'"}],
        },
        timeout=30,
    )
    data = response.json()
    print(f"Status: {response.status_code}")
    print(f"Response: {data['choices'][0]['message']['content']}")
    assert response.status_code == 200
    print("✓ OpenRouter connection OK")


if __name__ == "__main__":
    test_openrouter()
