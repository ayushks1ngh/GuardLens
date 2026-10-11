#!/usr/bin/env python3
"""Evaluate a gesture vocabulary prediction file without touching runtime data.

Input JSONL rows: {"expected":"A", "predicted":"A", "confidence":0.91, "signer":"s1"}
Reports accuracy, unknown rate, and per-label results. Use signer-disjoint files for
real acceptance decisions; this tool does not train or claim model quality.
"""
from __future__ import annotations
import json, sys
from collections import Counter
from pathlib import Path


def main(path: str) -> int:
    rows=[json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if not rows: print("No evaluation rows", file=sys.stderr); return 2
    total=len(rows); correct=sum(r.get("expected")==r.get("predicted") for r in rows)
    unknown=sum(r.get("predicted") in {None,"unknown"} for r in rows)
    by_label=Counter(); right=Counter()
    for row in rows:
        label=str(row.get("expected")); by_label[label]+=1; right[label]+=row.get("expected")==row.get("predicted")
    result={"samples":total,"accuracy":correct/total,"unknown_rate":unknown/total,
            "per_label_accuracy":{k:right[k]/v for k,v in sorted(by_label.items())}}
    print(json.dumps(result,indent=2)); return 0

if __name__=="__main__":
    if len(sys.argv)!=2: print(__doc__); raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
