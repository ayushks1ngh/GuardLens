import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

/** Sends uncaught browser errors to the server log so a crash can be diagnosed without the browser console. */
function reportClientError(message: string, stack = "") {
  try {
    void fetch("/api/client-log", {
      method: "POST", headers: { "Content-Type": "application/json" }, keepalive: true,
      body: JSON.stringify({ message: message.slice(0, 500), stack: stack.slice(0, 2000), page: location.pathname + location.hash, agent: navigator.userAgent.slice(0, 200) }),
    }).catch(() => undefined);
  } catch { /* reporting must never throw */ }
}
window.addEventListener("error", (e) => reportClientError(e.message, e.error?.stack));
window.addEventListener("unhandledrejection", (e) => reportClientError(String(e.reason?.message ?? e.reason), e.reason?.stack));

createRoot(document.getElementById("root")!).render(<App />);
