"""Real-browser smoke test: boots GuardLens on a temporary data directory and drives Chromium through the product.

Covers: / -> /app/, the short menu + Settings tabs, the Live chat panel, Data backups, the camera Test panel, and the
whole login flow with real keystrokes (create account, sign out, sign in). Fails on any console error or crash.
Usage: python scripts/browser_smoke.py        (needs: pip install -r requirements-browser.txt; playwright install chromium)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 18766
BASE = f"http://127.0.0.1:{PORT}"
results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""), flush=True)
    return bool(ok)


def main() -> int:
    if not (ROOT / "frontend-app" / "dist" / "index.html").exists():
        print("The dashboard is not built: run `cd frontend-app && npm ci && npm run build` first.")
        return 2
    data = Path(tempfile.mkdtemp(prefix="guardlens-browser-"))
    env = {**os.environ, "GUARDLENS_DATA_DIR": str(data), "GUARDLENS_PORT": str(PORT), "GUARDLENS_HOST": "127.0.0.1",
           "GUARDLENS_ANALYSIS_ENABLED": "false"}
    for key in list(env):
        if key.startswith("GUARDLENS_") and key.endswith(("_API_KEY", "_URL", "_CERTFILE", "_KEYFILE")):
            env.pop(key)
    log = open(data / "server.log", "w")
    server = subprocess.Popen([sys.executable, "-m", "guardlens"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                if requests.get(f"{BASE}/api/auth/status", timeout=1).ok:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        # A camera whose video file is missing, so the Test panel has something to explain.
        requests.post(f"{BASE}/api/cameras", json={"name": "Hall", "source_type": "opencv",
                      "source_config": {"mode": "file", "path": str(data / "missing.mp4")}})
        console: list[str] = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: console.append(f"PAGE ERROR {e}"))
            page.on("crash", lambda: console.append("PAGE CRASHED"))

            page.goto(BASE + "/")
            page.wait_for_selector("nav")
            step("/ opens the dashboard at /app/", page.url.rstrip("/").endswith("/app"), page.url)
            nav = [b.inner_text() for b in page.locator("nav button").all()]
            step("left menu is short, ends with Settings", nav[:5] == ["Live", "Events", "Find footage", "Reports", "Settings"], str(nav))
            step("Ask GuardLens chat sits on the Live page", page.locator("aside[aria-label='Ask GuardLens']").count() == 1)

            page.get_by_role("button", name="Settings").click()
            tabs = [t.inner_text() for t in page.get_by_role("tab").all()]
            step("Settings has every section as a tab", tabs == ["Cameras", "Rules", "Zones", "Faces", "Notifications", "Recording",
                                                                  "AI helpers", "Security", "Data", "Health"], str(tabs))

            page.get_by_role("tab", name="Cameras").click()
            page.get_by_role("button", name="Test").first.click()
            page.wait_for_selector(".diagnosis")
            text = page.locator(".diagnosis").inner_text()
            step("camera Test explains a missing video file", "not found" in text and "What to do" in text, text.replace("\n", " ")[:90])

            page.get_by_role("tab", name="Data").click()
            page.get_by_role("button", name="Back up now").click()
            page.wait_for_selector("text=Backup saved")
            step("Data: Back up now saves a backup", len(list((data / "backups").glob("guardlens-manual-*.db"))) == 1)

            page.get_by_role("tab", name="Security").click()
            page.locator("#auth-user").click(); page.locator("#auth-user").press_sequentially("admin", delay=40)
            page.locator("#auth-pass").click(); page.locator("#auth-pass").press_sequentially("correct-horse-99", delay=40)
            step("typing in the account form keeps the page alive", page.locator("#auth-user").input_value() == "admin")
            page.get_by_role("button", name="Create account").click()
            page.wait_for_selector("text=Login is on")
            step("account created, login turns on, banner gone", page.locator(".login-banner").count() == 0)
            page.reload(); page.wait_for_selector("nav")
            step("reload keeps the session", page.get_by_role("button", name="Sign out (admin)").count() == 1)
            page.get_by_role("button", name="Sign out (admin)").click()
            page.wait_for_selector("text=Sign in to GuardLens")
            page.locator("#auth-user").press_sequentially("admin", delay=40)
            page.locator("#auth-pass").press_sequentially("correct-horse-99", delay=40)
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_selector("nav")
            step("sign out then sign in works", page.get_by_role("button", name="Sign out (admin)").count() == 1)
            browser.close()
        step("no browser console errors or crashes", not console, "; ".join(console)[:300])
        step("no BROWSER ERROR reports reached the server log", "BROWSER ERROR" not in (data / "server.log").read_text())
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
        shutil.rmtree(data, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} steps passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
