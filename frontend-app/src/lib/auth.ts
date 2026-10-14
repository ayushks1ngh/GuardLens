export interface AuthStatus { enabled: boolean; needs_setup: boolean; authenticated: boolean; username: string | null }
export interface ApiToken { id: number; name: string; created_at: string; last_used_at: string | null }
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

export function tokenUsedText(t: ApiToken): string {
  return t.last_used_at ? `Last used ${new Date(t.last_used_at).toLocaleString()}` : "Never used";
}

export function bearerExample(token: string): string { return `Authorization: Bearer ${token}`; }

export function loginErrorText(status: number | undefined, message?: string): string {
  if (status === 401) return "That username or password is not right.";
  if (status === 429) return "Too many attempts. Wait a few minutes and try again.";
  return message || "Could not sign in. Check that GuardLens is running.";
}
