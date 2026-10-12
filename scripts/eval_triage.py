"""Evaluate event triage on labelled history.

Usage: python scripts/eval_triage.py labels.json
labels.json maps event id -> "real" | "false_alarm". Events must already carry an
``event_metadata.agent.event_triage`` annotation (run the agent first).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402

from guardlens.agents.evaluation import evaluate_triage  # noqa: E402
from guardlens.config import load_config  # noqa: E402
from guardlens.events import Event, get_engine, init_engine  # noqa: E402


def main(path: str) -> None:
    labels = json.loads(Path(path).read_text())
    init_engine(load_config().resolved_db_url())
    rows = []
    with Session(get_engine()) as session:
        for event_id, label in labels.items():
            event = session.get(Event, int(event_id))
            note = ((event.event_metadata or {}).get("agent") or {}).get("event_triage") if event else None
            if note:
                rows.append({"label": label, "threat": note.get("threat"), "false_alarm": note.get("false_alarm")})
    print(json.dumps(evaluate_triage(rows), indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
