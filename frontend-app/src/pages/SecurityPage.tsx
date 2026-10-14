import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { AUTH_CHANGED_EVENT, EXPIRY_CHOICES, auditText, bearerExample, tokenExpiryText, tokenScopeText, tokenUsedText, type ApiToken, type AuditRow, type AuthStatus } from "../lib/auth";
import { AuthForm } from "../components/AuthScreens";
import type { Meta } from "../types";

export function SecurityPage({ meta: _meta }: { meta: Meta | null }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [tokenName, setTokenName] = useState("");
  const [tokenScope, setTokenScope] = useState<"read" | "full">("read");
  const [tokenDays, setTokenDays] = useState("90");
  const [audit, setAudit] = useState<AuditRow[]>([]);
  const [fresh, setFresh] = useState<{ name: string; token: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [confirmOff, setConfirmOff] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTokens = useCallback(() => {
    api<AuditRow[]>("/api/auth/audit?limit=15").then((rows) => setAudit(Array.isArray(rows) ? rows : [])).catch(() => undefined);
    return api<ApiToken[]>("/api/auth/tokens").then(setTokens).catch(() => undefined);
  }, []);
  const loadStatus = useCallback(() => {
    api<AuthStatus>("/api/auth/status").then((st) => {
      setStatus(st);
      // Only signed-in users can list tokens; asking while signed out would look like an expired session.
      if (st.authenticated) loadTokens();
    }).catch(() => undefined);
  }, [loadTokens]);
  useEffect(() => { loadStatus(); }, [loadStatus]);
  const afterSignIn = () => { loadStatus(); window.dispatchEvent(new Event(AUTH_CHANGED_EVENT)); };

  const fail = (e: unknown, fallback: string) => setError(e instanceof ApiError ? e.message : fallback);

  const changePassword = async (e: FormEvent) => {
    e.preventDefault();
    setPwMsg(null);
    if (next.length < 10) { setPwMsg({ ok: false, text: "The new password must be at least 10 characters." }); return; }
    try {
      await api("/api/auth/password", { method: "PUT", json: { current, new: next } });
      setCurrent(""); setNext("");
      setPwMsg({ ok: true, text: "Password changed." });
    } catch (err) {
      setPwMsg({ ok: false, text: err instanceof ApiError ? (err.status === 401 || err.status === 403 ? "The current password is not right." : err.message) : "Could not change the password." });
    }
  };

  const setLogin = async (enabled: boolean) => {
    setError(null);
    try {
      const res = await api<{ enabled: boolean }>("/api/auth/settings", { method: "PUT", json: { enabled } });
      setStatus((s) => (s ? { ...s, enabled: res.enabled } : s));
      window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
      setConfirmOff(false);
    } catch (err) { fail(err, "Could not change the login setting."); }
  };

  const createToken = async (e: FormEvent) => {
    e.preventDefault();
    const name = tokenName.trim();
    if (!name) return;
    setError(null); setCopied(false);
    try {
      const res = await api<{ id: number; name: string; token: string }>("/api/auth/tokens", { method: "POST", json: { name, scope: tokenScope, expires_days: tokenDays ? Number(tokenDays) : null } });
      setFresh({ name: res.name, token: res.token });
      setTokenName("");
      loadTokens();
    } catch (err) { fail(err, "Could not create the token."); }
  };

  const removeToken = async (id: number) => {
    setError(null);
    try { await api(`/api/auth/tokens/${id}`, { method: "DELETE" }); setConfirmDelete(null); loadTokens(); }
    catch (err) { fail(err, "Could not delete the token."); }
  };

  const copy = async () => {
    try { await navigator.clipboard.writeText(fresh!.token); setCopied(true); } catch { setCopied(false); }
  };

  return (
    <section className="security-page">
      <div className="page-head"><h2>Security</h2></div>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Login is {status ? (status.enabled ? "on" : "off") : "…"}</h3>
        <p className="hint">
          {status?.enabled
            ? `Anyone opening GuardLens must sign in first${status.username ? ` (signed in as ${status.username})` : ""}.`
            : "Anyone who can reach this computer on your network can see the cameras."}
        </p>
        {status && !status.enabled && !status.needs_setup && <button type="button" className="primary" onClick={() => setLogin(true)}>Turn login on</button>}
        {status?.enabled && !confirmOff && <button type="button" onClick={() => setConfirmOff(true)}>Turn login off</button>}
        {status?.enabled && confirmOff && (
          <div className="warn-box" role="alertdialog" aria-label="Confirm turning login off">
            <p style={{ marginTop: 0 }}>Without login, anyone who can reach GuardLens can watch your cameras and change settings. Only do this on a network you fully trust.</p>
            <div className="row-inline">
              <button type="button" onClick={() => setLogin(false)}>Yes, turn login off</button>
              <button type="button" onClick={() => setConfirmOff(false)}>Keep login on</button>
            </div>
          </div>
        )}
      </div>

      {status?.needs_setup && (
        <>
          <p className="hint">Create the administrator account to protect your cameras. Login turns on as soon as you do, and then every device must sign in.</p>
          <AuthForm mode="setup" onDone={afterSignIn} />
        </>
      )}
      {status && !status.needs_setup && !status.authenticated && (
        <>
          <p className="hint">Sign in to change your password or manage API tokens.</p>
          <AuthForm mode="login" onDone={afterSignIn} />
        </>
      )}
      {status?.authenticated && (
        <>
      <form className="card stack" onSubmit={changePassword}>
        <h3 style={{ marginTop: 0 }}>Change password</h3>
        <label htmlFor="sec-current">Current password</label>
        <input id="sec-current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        <label htmlFor="sec-new">New password (at least 10 characters)</label>
        <input id="sec-new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
        <div><button type="submit" className="primary">Change password</button></div>
        {pwMsg && <p className={pwMsg.ok ? "hint" : "error"} role={pwMsg.ok ? "status" : "alert"}>{pwMsg.text}</p>}
      </form>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>API tokens</h3>
        <p className="hint">
          A token lets a script or another app talk to GuardLens without your password. Send it with each request as
          {" "}<code>Authorization: Bearer &lt;token&gt;</code>. Give each app its own token so you can remove one without affecting the others.
        </p>
        {fresh && (
          <div className="warn-box" role="status" style={{ marginBottom: 12 }}>
            <p style={{ marginTop: 0 }}><strong>Token “{fresh.name}” created.</strong> Copy it now. You won’t see this again.</p>
            <div className="copy-box">
              <input readOnly aria-label="New token" value={fresh.token} onFocus={(e) => e.currentTarget.select()} />
              <button type="button" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
            </div>
            <p className="hint">Use it as: <code>{bearerExample("<token>")}</code></p>
            <button type="button" onClick={() => setFresh(null)}>I’ve saved it</button>
          </div>
        )}
        {tokens.length === 0 ? <p className="hint">No tokens yet.</p> : (
          <ul className="list">
            {tokens.map((t) => (
              <li key={t.id} className="row">
                <div className="grow"><strong>{t.name}</strong><div className="hint">{tokenScopeText(t)} · {tokenExpiryText(t)} · {tokenUsedText(t)}</div></div>
                {confirmDelete === t.id ? (
                  <>
                    <span>Delete this token? Apps using it will stop working.</span>
                    <button type="button" onClick={() => removeToken(t.id)}>Yes, delete</button>
                    <button type="button" onClick={() => setConfirmDelete(null)}>Cancel</button>
                  </>
                ) : <button type="button" aria-label={`Delete token ${t.name}`} onClick={() => setConfirmDelete(t.id)}>Delete</button>}
              </li>
            ))}
          </ul>
        )}
        <form className="row-inline wrap" onSubmit={createToken} style={{ marginTop: 12 }}>
          <label htmlFor="sec-token-name" className="sr-only">Token name</label>
          <input id="sec-token-name" className="grow" placeholder="What is it for? (e.g. Home Assistant)" value={tokenName}
            maxLength={60} onChange={(e) => setTokenName(e.target.value)} />
          <label htmlFor="sec-token-scope" className="sr-only">What the token may do</label>
          <select id="sec-token-scope" value={tokenScope} onChange={(e) => setTokenScope(e.target.value as "read" | "full")}>
            <option value="read">Read-only</option>
            <option value="full">Full access</option>
          </select>
          <label htmlFor="sec-token-days" className="sr-only">When the token expires</label>
          <select id="sec-token-days" value={tokenDays} onChange={(e) => setTokenDays(e.target.value)}>
            {EXPIRY_CHOICES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <button type="submit" className="primary" disabled={!tokenName.trim()}>Create token</button>
        </form>
        <p className="hint">Prefer read-only for dashboards and scripts that only look. A token that expires limits the damage if it leaks.</p>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Recent sign-in activity</h3>
        {audit.length === 0 ? <p className="hint">Nothing recorded yet.</p> : (
          <ul className="list">
            {audit.map((r) => (
              <li key={r.id} className="row">
                <div className="grow">
                  <span className={r.kind === "login_failed" ? "error" : undefined}>{auditText(r)}</span>
                  <div className="hint">{new Date(r.at + "Z").toLocaleString()}{r.ip ? ` · from ${r.ip}` : ""}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="hint">Kept for 180 days. Passwords and tokens are never written here.</p>
      </div>
        </>
      )}
    </section>
  );
}
