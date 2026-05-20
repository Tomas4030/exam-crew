"""List available models from Blackbox AI."""
import os
from pathlib import Path
from dotenv import load_dotenv
import httpx

load_dotenv(Path(__file__).parent.parent / ".env")
api_key = os.environ.get("BLACKBOX_API_KEY", "")

response = httpx.get(
    "https://api.blackbox.ai/v1/models",
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=30,
)
print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    models = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(models, list):
        for m in models:
            name = m.get("id", m) if isinstance(m, dict) else m
            print(f"  - {name}")
    else:
        print(data)
else:
    print(response.text[:500])
