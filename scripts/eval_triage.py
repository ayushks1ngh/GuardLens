"""Evaluate alert triage on the alerts you have judged.

Usage: python scripts/eval_triage.py                 # uses your "Real alert" / "False alarm" buttons (Events page)
       python scripts/eval_triage.py labels.json     # or a file mapping event id -> "real" | "false_alarm"
Alerts must already carry an AI note (turn on "Alert triage" under Settings > AI helpers and let it run, or re-run it).
Suppression of alerts stays OFF unless this says safe_to_enable_suppression: true.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402

from guardlens import feedback  # noqa: E402
from guardlens.agents.evaluation import evaluate_triage  # noqa: E402
from guardlens.config import load_config  # noqa: E402
from guardlens.events import Event, get_engine, init_engine  # noqa: E402


def main(path: str | None) -> int:
    init_engine(load_config().resolved_db_url())
    with Session(get_engine()) as session:
        if path:
            rows = []
            for event_id, label in json.loads(Path(path).read_text()).items():
                event = session.get(Event, int(event_id))
                note = feedback._triage_note(event) if event else None
                if note:
                    rows.append({"label": label, "threat": note.get("threat"), "false_alarm": note.get("false_alarm")})
            report = evaluate_triage(rows)
            progress = {"judged": len(rows)}
        else:
            progress, report = feedback.summary(session), feedback.triage_report(session)
    print(json.dumps({"progress": progress, "evaluation": report}, indent=2))
    needed = feedback.NEEDED
    if report["real"] < needed:
        print(f"\nNot enough yet: {report['real']} real alerts judged with AI notes; at least {needed} are needed before "
              "the result means anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
