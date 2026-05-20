import json
import sys


def report_progress(stage: str, message: str, details: dict = None):
    payload = {"stage": stage, "message": message}
    if details:
        payload["details"] = details
    print(json.dumps(payload), flush=True)
