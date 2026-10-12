"""End-to-end smoke test against a REAL server (real YOLO, sample video, real CLIP search).

Boots GuardLens on a temporary data directory, adds the bundled sample video as a camera,
and walks the product: detection -> events -> evidence -> agents -> search -> login. Prints
PASS/FAIL per step and exits non-zero on any failure. Takes a few minutes the first time
(downloads the search model once). Usage: python scripts/e2e_smoke.py [--skip-search] [--ai]
--ai also exercises triage/chat/rule drafting/briefing with the provider key(s) from .env
(frames of the bundled sample video are sent to that provider).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PORT = 18765
BASE = f"http://127.0.0.1:{PORT}"
results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""), flush=True)
    return ok


def wait_for(fn, timeout, every=1.0):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = fn()
            if last:
                return last
        except requests.RequestException:
            pass
        time.sleep(every)
    return last


def load_ai_keys() -> dict:
    """Only the AI provider keys from the gitignored .env (never printed, never TLS/other settings)."""
    keys = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() in ("GUARDLENS_NVIDIA_API_KEY", "GUARDLENS_GEMINI_API_KEY", "GUARDLENS_OPENROUTER_API_KEY") and value.strip():
                keys[name.strip()] = value.strip().strip('"').strip("'")
    return keys


def run_ai_steps(http, cid, events) -> None:
    import re
    status = http.get(f"{BASE}/api/agents/ai").json()
    step("AI provider is configured", status["available"], str([p["name"] for p in status["providers"] if p["configured"]]))
    if not status["available"]:
        return
    http.put(f"{BASE}/api/agents/event_triage", json={"config": {"enabled": True, "max_runs_per_hour": 100}})

    def noted():
        for ev in http.get(f"{BASE}/api/events", params={"camera_id": cid, "limit": 50}).json()["items"]:
            note = ((ev.get("event_metadata") or {}).get("agent") or {}).get("event_triage")
            if note:
                return ev, note

    found = wait_for(noted, 150, every=3)
    step("triage annotates a real alert via the live model", bool(found))
    if found:
        note = found[1]
        step("triage verdict parsed (or failed open readably)", note.get("verdict") in ("parsed", "unparsed"),
             f"{note.get('verdict')} threat={note.get('threat')} title={str(note.get('title'))[:50]!r} model={note.get('model')}")
        step("triage never changed the alert's own severity", found[0]["severity"] == "warning")
    runs = http.get(f"{BASE}/api/agents/runs", params={"agent": "event_triage", "limit": 20}).json()
    step("agent runs are audited", bool(runs), str(sorted({r["status"] for r in runs})))
    chat = http.post(f"{BASE}/api/assistant/chat", json={"question": "What happened in the last hour? Cite alert ids.", "camera_id": cid}, timeout=90)
    step("assistant answers about the camera", chat.ok, chat.text[:100] if not chat.ok else chat.json()["answer"][:80])
    if chat.ok:
        body = chat.json()
        step("assistant returns the analysed frame", bool(body["frame_url"]) and http.get(BASE + body["frame_url"]).ok)
        known = {u["id"] for u in body["events_used"]}
        step("assistant citations only reference supplied alerts", set(body["citations"]) <= known, str(body["citations"]))
        follow = http.post(f"{BASE}/api/assistant/chat", json={"question": "and how many people were there?",
                                                                "session_id": body["session_id"], "camera_id": cid}, timeout=90)
        step("assistant follow-up works with memory", follow.ok)
    draft = http.post(f"{BASE}/api/rules/propose", json={"text": "Warn me if more than 3 people are in view on the Mall sample camera"}, timeout=90)
    step("rule drafting returns a validated draft", draft.ok, draft.text[:120] if not draft.ok else "")
    if draft.ok:
        proposal = draft.json()["proposal"]
        step("draft is a known rule type with checked settings", bool(proposal["type"]), f"type={proposal['type']} problems={proposal['problems']}")
        rules_now = http.get(f"{BASE}/api/rules").json()
        step("drafting did not save anything", all(r["name"] != proposal["name"] for r in rules_now), proposal["name"])
    http.post(f"{BASE}/api/agents/daily_briefing/run", json={}, timeout=120)
    rep = http.get(f"{BASE}/api/reports/daily").json()
    step("AI briefing written or falls back safely", "daily briefing" in rep["text"], str(rep["content"].get("fallback") or "AI narrative"))
    if rep["content"].get("narrative"):
        cited = {int(i) for i in re.findall(r"\[E(\d+)\]", rep["content"]["narrative"])}
        listed = {e["id"] for e in http.get(f"{BASE}/api/events", params={"limit": 500}).json()["items"]}
        step("briefing cites only real alerts", cited <= listed, str(sorted(cited))[:60])


def main(skip_search: bool, with_ai: bool = False) -> int:
    data = Path(tempfile.mkdtemp(prefix="guardlens-e2e-"))
    env = {**os.environ, "GUARDLENS_DATA_DIR": str(data), "GUARDLENS_PORT": str(PORT), "GUARDLENS_HOST": "127.0.0.1",
           "GUARDLENS_ANALYSIS_ENABLED": "true"}
    for key in ("GUARDLENS_NVIDIA_API_KEY", "GUARDLENS_GEMINI_API_KEY", "GUARDLENS_OPENROUTER_API_KEY",
                "GUARDLENS_SSL_CERTFILE", "GUARDLENS_SSL_KEYFILE", "GUARDLENS_AUTH_DISABLE"):
        env.pop(key, None)
    if with_ai:
        env.update(load_ai_keys())
        print("AI mode: using provider key(s) from .env:", sorted(load_ai_keys()) or "NONE FOUND", flush=True)
    log = open(data / "server.log", "w")
    server = subprocess.Popen([sys.executable, "-m", "guardlens"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    http = requests.Session()
    try:
        up = wait_for(lambda: http.get(f"{BASE}/healthz", timeout=2).ok, 60)
        if not step("server starts", bool(up)):
            return 1
        health = http.get(f"{BASE}/health").json()
        step("health reports detectors", "object" in health["detectors"], str(health["detectors"]))
        meta = http.get(f"{BASE}/api/meta").json()
        step("meta lists plugins and agents", {"event_triage", "daily_briefing", "rule_setup"} <= set(meta["plugins"]["agents"]))
        step("new dashboard is served at /app/", '<div id="root">' in http.get(f"{BASE}/app/").text)
        types = http.get(f"{BASE}/api/rules/types").json()
        step("rule types carry form fields", all(t["fields"] is not None and t["label"] for t in types), f"{len(types)} types")

        sample = ROOT / "data" / "samples" / "mall_cctv.mp4"
        camera = http.post(f"{BASE}/api/cameras", json={"name": "Mall sample", "source": str(sample)}).json()
        cid = camera["id"]
        step("camera added", bool(cid))
        connected = wait_for(lambda: any(c["camera_id"] == cid and c["connected"] for c in http.get(f"{BASE}/health").json()["cameras"]), 30)
        step("camera connects and streams", bool(connected))
        snap = wait_for(lambda: (r := http.get(f"{BASE}/api/cameras/{cid}/snapshot")).ok and r.content[:2] == b"\xff\xd8" and r, 20)
        step("snapshot endpoint returns a JPEG", bool(snap))
        mjpeg = http.get(f"{BASE}/stream/{cid}/mjpeg?max_frames=1", timeout=15, stream=True)
        step("MJPEG stream serves frames", mjpeg.ok and "multipart" in mjpeg.headers.get("content-type", ""))
        mjpeg.close()

        rule = http.post(f"{BASE}/api/rules", json={"type": "object_class", "name": "e2e people", "camera_id": cid,
                                                    "severity": "warning", "cooldown_seconds": 2,
                                                    "params": {"classes": ["person"], "min_confidence": 0.3}})
        step("rule created through the validated API", rule.status_code == 201, rule.text[:120])
        bad = http.post(f"{BASE}/api/rules", json={"type": "crowd", "name": "bad", "params": {"threshold": "many"}})
        step("invalid rule settings rejected with a readable error", bad.status_code == 422 and "threshold" in bad.text)

        events = wait_for(lambda: http.get(f"{BASE}/api/events", params={"camera_id": cid}).json()["items"] or None, 90)
        step("real detection raises events", bool(events), f"{len(events or [])} events")
        if events:
            ev = events[0]
            img = http.get(f"{BASE}/history/{ev['snapshot_path']}")
            step("event snapshot evidence is stored and served", img.ok and img.content[:2] == b"\xff\xd8")
            step("event metadata carries boxes", bool(ev["event_metadata"].get("boxes")), str(ev["event_metadata"].get("classes")))
            ack = http.post(f"{BASE}/api/events/{ev['id']}/acknowledge", json={})
            step("event can be acknowledged", ack.ok and ack.json()["status"] == "acknowledged")
            report = http.get(f"{BASE}/api/events/{ev['id']}/incident-report").json()
            step("incident report draft builds", "# Incident report" in report["markdown"])

        dry = http.post(f"{BASE}/api/rules/preview", json={"type": "object_class", "camera_id": cid, "params": {"classes": ["person"]}, "hours": 1}).json()
        step("rule preview replays stored activity", dry["supported"] and dry["samples_checked"] >= 0, f"samples={dry.get('samples_checked')}")

        step("agents listed with settings fields", len(http.get(f"{BASE}/api/agents").json()) >= 4)
        unusual = http.put(f"{BASE}/api/agents/unusual_activity", json={"config": {"enabled": True}})
        step("an agent can be turned on from the API", unusual.ok and unusual.json()["status"]["state"] == "active")
        if not with_ai:
            step("AI-dependent helper degrades cleanly without a key",
                 http.post(f"{BASE}/api/rules/propose", json={"text": "alert me when anyone is near the door"}).status_code == 503)
            step("assistant says AI is not configured (no crash)", http.post(f"{BASE}/api/assistant/chat", json={"question": "hello"}).status_code == 503)
        issues = http.get(f"{BASE}/api/health/issues").json()
        step("health issues are explained", all({"message", "fix"} <= set(i) for i in issues), f"{len(issues)} items")
        if with_ai:
            run_ai_steps(http, cid, events or [])
        briefing = http.post(f"{BASE}/api/agents/daily_briefing/run", json={})
        step("daily briefing falls back to the plain report without AI", briefing.ok and briefing.json()["status"] == "ok")
        report = http.get(f"{BASE}/api/reports/daily").json()
        step("daily report is generated", "daily briefing" in report["text"])

        if not skip_search and events:
            print("…enabling search (downloads the CLIP model on first run)", flush=True)
            http.put(f"{BASE}/api/search/settings", json={"enabled": True})
            done = wait_for(lambda: (s := http.get(f"{BASE}/api/search/status").json())["indexed_events"] >= 1 and s, 900, every=5)
            step("search model loads and indexes events", bool(done), str(done and {k: done[k] for k in ("indexed_events", "events_with_pictures", "error")}))
            if done:
                found = http.get(f"{BASE}/api/search", params={"q": "a person walking"}).json()["results"]
                step("natural-language search returns events", bool(found), f"{len(found)} results")
                if found:
                    sim = http.get(f"{BASE}/api/search/similar/{found[0]['event_id']}").json()["results"]
                    step("find-similar works", isinstance(sim, list))

        # ---- login ------------------------------------------------------------------
        step("login is off by default", http.get(f"{BASE}/api/auth/status").json()["enabled"] is False)
        setup = http.post(f"{BASE}/api/auth/setup", json={"username": "admin", "password": "e2e-password-123"})
        step("administrator created, login turns on", setup.status_code == 201)
        anon = requests.Session()
        step("signed-out API calls are refused", anon.get(f"{BASE}/api/cameras").status_code == 401)
        step("signed-out streams and snapshots are refused",
             anon.get(f"{BASE}/stream/{cid}/mjpeg?max_frames=1").status_code == 401 and anon.get(f"{BASE}/history/x.jpg").status_code == 401)
        step("dashboard shell still loads to show the login screen", anon.get(f"{BASE}/app/").ok)
        step("signed-in session works", http.get(f"{BASE}/api/cameras").ok)
        token = http.post(f"{BASE}/api/auth/tokens", json={"name": "e2e"}).json()["token"]
        step("API token works as a bearer", anon.get(f"{BASE}/api/cameras", headers={"Authorization": f"Bearer {token}"}).ok)
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
            step("server shuts down cleanly", server.returncode in (0, -15, 143), f"exit {server.returncode}")
        except subprocess.TimeoutExpired:
            server.kill()
            step("server shuts down cleanly", False, "had to kill")
        log.close()
        failed = [r for r in results if not r[1]]
        text = (data / "server.log").read_text(errors="replace")
        errors = [l for l in text.splitlines() if " ERROR " in l or "Traceback" in l]
        step("no errors in the server log", not errors, errors[0][:160] if errors else "")
        if failed or errors:
            print(f"\nlog kept at {data / 'server.log'}")
        else:
            shutil.rmtree(data, ignore_errors=True)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} steps passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main("--skip-search" in sys.argv, "--ai" in sys.argv))
