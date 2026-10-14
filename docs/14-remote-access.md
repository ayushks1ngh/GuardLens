# 14 — Remote access (login + tunnel)

GuardLens runs where the cameras are. To reach it from elsewhere, keep the server on this
machine and put a secure tunnel in front of it. **Turn login on first** — until an
administrator account exists, anyone who can reach port 8080 can see every camera.

## 1. Create the administrator and turn login on
Open the new dashboard at `/app/`, then **Security**. The first visit asks you to create the
administrator account (username 3–40 characters, password ≥ 10 characters). Creating it turns
login on for the whole API, live streams and snapshots. Passwords are stored as scrypt
hashes; browsers get an `HttpOnly`, `SameSite=Lax` cookie (also `Secure` over HTTPS); scripts
use **API tokens** (`Authorization: Bearer glt_…`, shown once at creation, stored hashed).
Five wrong passwords from one address lock sign-in for a minute.

Locked out? Start the server once with `GUARDLENS_AUTH_DISABLE=1` to bypass login, then fix
the account in **Security**.

The dashboard lives at `/app/` (`/` redirects there) and shows the sign-in screen itself when login is on.
Phone publishers (`/publish`) keep working because they authenticate with their own
short-lived pairing token.

## 2. Pick a tunnel
**Tailscale (private, recommended).** Install Tailscale on this machine and on your phone/laptop.
`tailscale serve --bg 8080` (or `tailscale serve --https=443 localhost:8080`) publishes the dashboard
inside your tailnet with a valid HTTPS certificate. Nothing is exposed to the public internet.

**Cloudflare Tunnel (public URL).** `cloudflared tunnel --url http://localhost:8080` gives a
public `https://….trycloudflare.com` address (use a named tunnel + Cloudflare Access for anything
permanent). Because the tunnel reaches GuardLens from localhost, login must be on.

Both give you HTTPS, which browsers require for phone-camera publishing and which makes the
session cookie `Secure`.

## 3. Hosting the UI elsewhere (optional)
The React app talks to a single `API_BASE`. Build it with `VITE_API_BASE=https://your-host`
and list the UI's origin in `config.yaml` under `cors_origins:`. Cookie login is designed for
the same origin (the tunnel URL); a split-origin setup should use API tokens instead.

## 4. What is *not* protected
- Anyone on the same LAN who can reach port 8080 sees only the login screen once login is on.
- The VLM features send frames to the AI provider you configure unless a camera is marked
  "local only" (Agents → Privacy).


## Tokens and the activity log (Settings → Security)
- **Read-only tokens** can look (GET) but not change anything, and cannot create tokens or read the activity log. Use them
  for dashboards and scripts that only read. **Full access** tokens can do everything you can. Both can expire (30 days,
  90 days, 1 year); an expired token stops working immediately and stays listed so you can delete it.
- **Recent sign-in activity** lists sign-ins, failed attempts (with the address they came from), password changes, token
  changes and login on/off. Passwords and tokens are never written to it.
- After 10 wrong passwords for the same account **from the same address** within 5 minutes, that address is refused for
  that account (even with the right password) for the rest of the window, and 5 wrong passwords from one address block that
  address for a minute. A stranger therefore cannot lock you out from your own address. Behind a tunnel or reverse proxy
  all visitors can look like one address unless the proxy's address is trusted: start with `--forwarded-allow-ips` (or set
  `FORWARDED_ALLOW_IPS`) so GuardLens sees the real client address.

## First account from another computer
Creating the very first account from any machine other than the one running GuardLens (or through a proxy) needs a one-time
**setup code**. It is printed in the terminal/log where GuardLens starts (`Setup code: XXXX-XXXX`; for the testing launcher
see `data/testing-server.log`). The dashboard asks for it automatically. Without it, anyone on your network who reached the
page first could become the administrator. It works once; 5 wrong tries per minute are allowed per address.


## What has been verified for remote access (2026-10-14)
| Behaviour | How verified |
|---|---|
| Until an admin exists, anything arriving through a proxy/tunnel gets 403 (no data, no admin takeover) | automated test (`X-Forwarded-For`, `CF-Connecting-IP`, `Tailscale-User-Login`) |
| Once an admin exists, a signed-out remote visitor gets the sign-in screen only; every data, stream, snapshot, token and audit endpoint answers 401 | automated test |
| Session cookie is `HttpOnly; SameSite=Lax`, and `Secure` when the tunnel says `X-Forwarded-Proto: https` | automated test |
| Read-only and expiring tokens, audit log, per-account throttle | automated tests + real-browser suite |
| **Not verified here:** a real Tailscale Serve / Funnel or Cloudflare Tunnel session (needs your account and a device outside your network) | 👤 do once: set `GUARDLENS_PUBLIC_URL`, create the admin locally, open the tunnel URL from your phone on mobile data, sign in, and check Settings → Security shows that sign-in with its address |
