"""Re-run the 6 previously-failing PT exams and report scoring results."""
import json
import os
import subprocess
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

EXAMS = ["rerun_2009f1", "rerun_2009f2", "rerun_2010f1", "rerun_2015f1", "rerun_2015f2", "rerun_2023f1"]
OUT_DIR = os.path.join("..", "data", "output")

for eid in EXAMS:
    pdf = os.path.join("..", "data", "uploads", f"{eid}.pdf")
    print(f"\n{'='*60}\nRUNNING {eid}\n{'='*60}", flush=True)
    proc = subprocess.run(
        [sys.executable, "-m", "src.main", pdf, eid],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    # Show last line of pipeline output
    tail = [l for l in (proc.stdout or "").splitlines() if l.strip()][-2:]
    for l in tail:
        print("  ", l)
    if proc.returncode != 0:
        print(f"  EXIT CODE {proc.returncode}")
        print("  STDERR:", (proc.stderr or "")[-500:])

    out_path = os.path.join(OUT_DIR, f"{eid}.json")
    if not os.path.exists(out_path):
        print("  NO OUTPUT FILE")
        continue
    with open(out_path, encoding="utf-8") as f:
        d = json.load(f)
    pol = d.get("metadata", {}).get("scoringPolicy", {})
    qs = d.get("questions", [])
    gtot = defaultdict(int)
    for q in qs:
        gtot[q.get("groupId", "?")] += int(q.get("points") or 0)
    print(f"  >> status={d.get('processingStatus')}")
    print(f"  >> source={pol.get('source')} raw={pol.get('rawSubtotal')} mand={pol.get('mandatorySubtotal')} optPool={pol.get('optionalPool')}")
    print(f"  >> group totals: {dict(gtot)} sum={sum(gtot.values())}")
    audit = d.get("audit") or {}
    print(f"  >> audit verdict={audit.get('verdict')} issues={[i.get('code') for i in audit.get('issues', [])]}")

print("\n\nALL DONE", flush=True)
