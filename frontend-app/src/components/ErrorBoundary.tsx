import { Component, type ErrorInfo, type ReactNode } from "react";

interface State { error: Error | null }

/** Shows what went wrong (and a way out) instead of a blank page when a screen throws while rendering. */
export class ErrorBoundary extends Component<{ children: ReactNode; label?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State { return { error }; }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("GuardLens screen crashed:", error, info.componentStack);
    try {
      void fetch("/api/client-log", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: `${error.name}: ${error.message}`, stack: (info.componentStack ?? "").slice(0, 2000), page: location.pathname, agent: navigator.userAgent.slice(0, 200) }) }).catch(() => undefined);
    } catch { /* ignore */ }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="card" role="alert" style={{ margin: 16 }}>
        <h2 style={{ marginTop: 0 }}>{this.props.label ?? "This screen"} hit a problem</h2>
        <p className="hint">The rest of GuardLens is still running. Details (send these if it keeps happening):</p>
        <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{error.name}: {error.message}</pre>
        <button type="button" className="primary" onClick={() => this.setState({ error: null })}>Try again</button>{" "}
        <button type="button" onClick={() => window.location.reload()}>Reload the page</button>
      </div>
    );
  }
}
