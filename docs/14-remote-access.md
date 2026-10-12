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

The classic dashboard at `/` has no login screen; with login on, use `/app/`.
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
