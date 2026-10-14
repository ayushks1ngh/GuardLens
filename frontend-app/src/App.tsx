import { useCallback, useEffect, useState } from "react";
import { api, UNAUTHORIZED_EVENT } from "./api";
import { AuthScreen } from "./components/AuthScreens";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AUTH_CHANGED_EVENT, screenFor, type AuthStatus } from "./lib/auth";
import { MAIN_PAGES, PAGES, SETTINGS_PAGES } from "./pages/registry";
import type { Meta } from "./types";
import "./styles-search-auth.css";

export function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [authError, setAuthError] = useState(false);
  const loadAuth = useCallback(() => {
    setAuthError(false);
    api<AuthStatus>("/api/auth/status").then(setAuth).catch(() => setAuthError(true));
  }, []);
  useEffect(() => { loadAuth(); }, [loadAuth]);
  useEffect(() => {
    window.addEventListener(AUTH_CHANGED_EVENT, loadAuth);
    return () => window.removeEventListener(AUTH_CHANGED_EVENT, loadAuth);
  }, [loadAuth]);
  useEffect(() => {
    // Any later 401 means the session ended: show the login screen again.
    const bounce = () => setAuth((a) => (a ? { ...a, enabled: true, authenticated: false } : a));
    window.addEventListener(UNAUTHORIZED_EVENT, bounce);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, bounce);
  }, []);

  const screen = screenFor(auth);
  if (authError) return <div className="auth-screen"><div className="card auth-card"><p className="error" role="alert">Could not reach GuardLens.</p><button type="button" onClick={loadAuth}>Try again</button></div></div>;
  if (screen === "loading") return <div className="auth-screen" role="status">Loading…</div>;
  if (screen === "setup" || screen === "login") return <ErrorBoundary label="The sign-in screen"><AuthScreen mode={screen} onDone={loadAuth} /></ErrorBoundary>;
  return <Dashboard auth={auth!} onSignedOut={loadAuth} />;
}

function Dashboard({ auth, onSignedOut }: { auth: AuthStatus; onSignedOut: () => void }) {
  const [page, setPage] = useState(PAGES[0].key);
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => { api<Meta>("/api/meta").then(setMeta).catch(() => setMeta(null)); }, []);
  useEffect(() => {
    const go = (e: Event) => { const p = (e as CustomEvent<{ page?: string }>).detail?.page; if (p && PAGES.some((x) => x.key === p)) setPage(p); };
    window.addEventListener("guardlens:navigate", go);
    return () => window.removeEventListener("guardlens:navigate", go);
  }, []);
  const [bannerHidden, setBannerHidden] = useState(() => {
    try { return sessionStorage.getItem("gl-login-banner") === "1"; } catch { return false; }
  });
  const hideBanner = () => {
    setBannerHidden(true);
    try { sessionStorage.setItem("gl-login-banner", "1"); } catch { /* private mode */ }
  };
  const signOut = async () => { await api("/api/auth/logout", { method: "POST" }).catch(() => undefined); onSignedOut(); };
  const current = PAGES.find((p) => p.key === page) ?? PAGES[0];
  const Page = current.component;
  const inSettings = current.group === "settings";
  // Remember the last Settings tab so the Settings button returns to it.
  const [lastSetting, setLastSetting] = useState(SETTINGS_PAGES[0].key);
  useEffect(() => { if (inSettings) setLastSetting(current.key); }, [inSettings, current.key]);
  return (
    <div className="shell">
      <nav aria-label="Main">
        <h1>GuardLens</h1>
        {MAIN_PAGES.map((p) => (
          <button key={p.key} type="button" aria-current={page === p.key ? "page" : undefined} onClick={() => setPage(p.key)}>
            {p.label}
          </button>
        ))}
        <button type="button" aria-current={inSettings ? "page" : undefined} onClick={() => setPage(lastSetting)}>Settings</button>
        {auth.enabled && <button type="button" className="signout" onClick={signOut}>Sign out{auth.username ? ` (${auth.username})` : ""}</button>}
      </nav>
      <main>
        {!auth.enabled && !bannerHidden && (
          <div className="warn-box login-banner" role="status">
            <span>Login is off: anyone on your network can watch your cameras. </span>
            <button type="button" onClick={() => setPage("security")}>Set up login</button>
            <button type="button" aria-label="Dismiss" onClick={hideBanner}>×</button>
          </div>
        )}
        {inSettings && (
          <div className="settings-head">
            <h2>Settings</h2>
            <div className="subtabs" role="tablist" aria-label="Settings sections">
              {SETTINGS_PAGES.map((p) => (
                <button key={p.key} type="button" role="tab" aria-selected={page === p.key} onClick={() => setPage(p.key)}>{p.label}</button>
              ))}
            </div>
          </div>
        )}
        <ErrorBoundary key={page} label="This page"><Page meta={meta} /></ErrorBoundary>
      </main>
    </div>
  );
}
