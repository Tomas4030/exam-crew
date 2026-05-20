"""Test Blackbox AI API connection."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import httpx

load_dotenv(Path(__file__).parent.parent / ".env")

api_key = os.environ.get("BLACKBOX_API_KEY", "")
if not api_key:
    print("ERROR: BLACKBOX_API_KEY not set in .env")
    sys.exit(1)

print(f"Key: {api_key[:6]}...{api_key[-4:]}")
print("Testing Blackbox AI with blackboxai/minimax/minimax-m2.5...")

response = httpx.post(
    "https://api.blackbox.ai/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": "blackboxai/minimax/minimax-m2.5",
        "messages": [{"role": "user", "content": "Diz 'olá' em português. Responde apenas com uma palavra."}],
        "max_tokens": 50,
    },
    timeout=30,
)

if response.status_code == 200:
    data = response.json()
    print(f"✅ OK: {data['choices'][0]['message']['content']}")
else:
    print(f"❌ Error {response.status_code}: {response.text}")
