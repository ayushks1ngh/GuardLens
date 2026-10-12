import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";
import { credentialProblem, loginErrorText } from "../lib/auth";

export function AuthScreen({ mode, onDone }: { mode: "setup" | "login"; onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const setup = mode === "setup";

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (setup) {
      const problem = credentialProblem(username, password);
      if (problem) { setError(problem); return; }
    }
    setBusy(true);
    try {
      await api(setup ? "/api/auth/setup" : "/api/auth/login", { method: "POST", json: { username: username.trim(), password } });
      setPassword("");
      onDone();
    } catch (err) {
      if (err instanceof ApiError) setError(setup ? err.fields.map((f) => f.message).join(" ") || err.message : loginErrorText(err.status, err.message));
      else setError("Could not reach GuardLens. Check that it is running.");
    } finally { setBusy(false); }
  };

  return (
    <div className="auth-screen">
      <div className="card auth-card">
        <h1 style={{ marginTop: 0 }}>{setup ? "Create the administrator account" : "Sign in to GuardLens"}</h1>
        {setup && (
          <p className="hint">
            This protects your camera feeds. Once you create the account, GuardLens asks for this username and password
            before showing anything, so other devices on your network can’t watch your cameras without it.
          </p>
        )}
        <form onSubmit={submit}>
          <label htmlFor="auth-user">Username</label>
          <input id="auth-user" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          <label htmlFor="auth-pass">{setup ? "Password (at least 10 characters)" : "Password"}</label>
          <input id="auth-pass" type="password" autoComplete={setup ? "new-password" : "current-password"}
            value={password} onChange={(e) => setPassword(e.target.value)} required />
          {error && <p className="error" role="alert">{error}</p>}
          <button type="submit" className="primary" disabled={busy}>{setup ? "Create account" : "Sign in"}</button>
        </form>
      </div>
    </div>
  );
}
