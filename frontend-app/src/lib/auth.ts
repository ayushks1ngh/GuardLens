export interface AuthStatus { enabled: boolean; needs_setup: boolean; authenticated: boolean; username: string | null; setup_code_required?: boolean }
export interface ApiToken {
  id: number; name: string; created_at: string; last_used_at: string | null;
  scope?: "read" | "full"; expires_at?: string | null; expired?: boolean;
}
export interface AuditRow { id: number; at: string; kind: string; username: string | null; ip: string | null; detail: string }
/** Fired by screens that change the login state so the app shell re-reads it (banner, sign-out button). */
export const AUTH_CHANGED_EVENT = "guardlens:auth-changed";
export type Screen = "loading" | "setup" | "login" | "app";

export function screenFor(s: AuthStatus | null): Screen {
  if (!s) return "loading";
  // Login is optional and off by default: never block the dashboard on account creation.
  // (Setup is offered from the Security page; this screen is only for the odd "login on, no account" state.)
  if (s.enabled && !s.authenticated) return s.needs_setup ? "setup" : "login";
  return "app";
}

/** Returns a plain-language problem with the username/password, or null when fine. */
export function credentialProblem(username: string, password: string): string | null {
  if (username.trim().length < 3 || username.trim().length > 40) return "The username must be 3 to 40 characters.";
  if (password.length < 10) return "The password must be at least 10 characters.";
  return null;
}

export const EXPIRY_CHOICES = [
  { value: "", label: "Never expires" }, { value: "30", label: "30 days" }, { value: "90", label: "90 days" }, { value: "365", label: "1 year" },
];

export function tokenScopeText(t: ApiToken): string {
  return t.scope === "read" ? "Read-only (can look, not change)" : "Full access";
}

export function tokenExpiryText(t: ApiToken): string {
  if (!t.expires_at) return "Never expires";
  const when = new Date(t.expires_at).toLocaleDateString();
  return t.expired ? `Expired on ${when} — delete it` : `Expires ${when}`;
}

/** One plain sentence for an audit-log row. */
export function auditText(r: AuditRow): string {
  const who = r.username ? `“${r.username}”` : "someone";
  switch (r.kind) {
    case "setup": return "Administrator account created and login turned on";
    case "login_ok": return `${who} signed in`;
    case "login_failed": return `Failed sign-in attempt for ${who}`;
    case "logout": return `${who} signed out`;
    case "password_changed": return `${who} changed the password (other devices signed out)`;
    case "token_created": return `Access token created: ${r.detail}`;
    case "token_deleted": return `Access token deleted: ${r.detail}`;
    case "login_toggled": return r.detail ? r.detail.charAt(0).toUpperCase() + r.detail.slice(1) : "Login setting changed";
    default: return r.kind;
  }
}

export function tokenUsedText(t: ApiToken): string {
  return t.last_used_at ? `Last used ${new Date(t.last_used_at).toLocaleString()}` : "Never used";
}

export function bearerExample(token: string): string { return `Authorization: Bearer ${token}`; }

export function loginErrorText(status: number | undefined, message?: string): string {
  if (status === 401) return "That username or password is not right.";
  if (status === 429) return "Too many attempts. Wait a few minutes and try again.";
  return message || "Could not sign in. Check that GuardLens is running.";
}
