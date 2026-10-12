import { useEffect, useReducer, useRef, useState } from "react";
import { api, API_BASE, ApiError } from "../api";
import {
  STARTER_QUESTIONS, chatErrorText, chatReducer, initialChat, loadSession, saveSession, type ChatResponse,
} from "../lib/chat";
import { requestNavigate } from "../lib/navigate";
import type { Camera, Meta } from "../types";

function frameSrc(url: string): string {
  if (/^https?:/.test(url)) return url;
  return API_BASE + (url.startsWith("/") ? url : `/history/${url}`);
}

export function AssistantPage({ meta: _meta }: { meta: Meta | null }) {
  const [state, dispatch] = useReducer(chatReducer, undefined, () => ({ ...initialChat, sessionId: loadSession() }));
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [zoom, setZoom] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef(state.sessionId);
  sessionRef.current = state.sessionId;

  useEffect(() => { api<Camera[]>("/api/cameras").then(setCameras).catch(() => undefined); }, []);
  useEffect(() => { saveSession(state.sessionId); }, [state.sessionId]);
  useEffect(() => { endRef.current?.scrollIntoView?.({ block: "end" }); }, [state.messages.length, state.waiting]);

  const cameraLabel = cameraId === null ? "all cameras" : cameras.find((c) => c.id === cameraId)?.name ?? `camera ${cameraId}`;

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || state.waiting) return;
    setDraft("");
    dispatch({ type: "ask", text: question });
    try {
      const body: Record<string, unknown> = { question, camera_id: cameraId };
      if (sessionRef.current) body.session_id = sessionRef.current;
      dispatch({ type: "answer", response: await api<ChatResponse>("/api/assistant/chat", { method: "POST", json: body }) });
    } catch (e) {
      dispatch({ type: "fail", text: e instanceof ApiError ? chatErrorText(e.status, e.message) : chatErrorText(undefined) });
    }
  };

  const reset = async () => {
    const id = sessionRef.current;
    dispatch({ type: "reset" });
    saveSession(null);
    if (id) await api(`/api/assistant/sessions/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => undefined);
  };

  return (
    <section className="assistant-page">
      <div className="page-head">
        <h2>Ask GuardLens</h2>
        <button type="button" onClick={reset} disabled={state.waiting || (!state.messages.length && !state.sessionId)}>New conversation</button>
      </div>
      <div className="card row-inline wrap">
        <label htmlFor="assistant-camera">Ask about</label>
        <select id="assistant-camera" value={cameraId === null ? "" : String(cameraId)}
          onChange={(e) => setCameraId(e.target.value === "" ? null : Number(e.target.value))}>
          <option value="">All cameras</option>
          {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <p className="hint" aria-live="polite">Questions will be about {cameraLabel}. Pictures are sent to an outside AI unless the camera is set to stay on this device.</p>

      <div className="chat-log card" role="log" aria-live="polite" aria-label="Conversation">
        {!state.messages.length && (
          <div>
            <p>Ask in your own words about what your cameras have seen.</p>
            <div className="chips-row">
              {STARTER_QUESTIONS.map((q) => <button key={q} type="button" className="fchip" onClick={() => send(q)}>{q}</button>)}
            </div>
          </div>
        )}
        {state.messages.map((m) => (
          <div key={m.id} className={`bubble bubble-${m.role}`}>
            {m.role === "error" ? <p className="error" role="alert">{m.text}</p> : <p className="bubble-text">{m.text}</p>}
            {m.role === "assistant" && m.frameUrl && (
              <button type="button" className="thumb" onClick={() => setZoom(m.frameUrl ?? null)} aria-label="Enlarge the picture the AI looked at">
                <img src={frameSrc(m.frameUrl)} alt={`The picture the AI looked at${m.camera ? ` from ${m.camera}` : ""}`} loading="lazy" />
              </button>
            )}
            {m.role === "assistant" && !!m.citations?.length && (
              <div className="chips-row" aria-label="Alerts mentioned">
                {m.citations.map((id) => (
                  <button key={id} type="button" className="fchip" onClick={() => requestNavigate("events", id)}>Alert #{id}</button>
                ))}
              </div>
            )}
            {m.role === "assistant" && (m.provider || m.camera) && (
              <p className="hint">{[m.camera, m.provider && `${m.provider}${m.model ? ` · ${m.model}` : ""}`].filter(Boolean).join(" · ")}</p>
            )}
          </div>
        ))}
        {state.waiting && <p className="hint" role="status">Thinking…</p>}
        <div ref={endRef} />
      </div>

      <form className="row-inline" onSubmit={(e) => { e.preventDefault(); void send(draft); }}>
        <label className="sr-only" htmlFor="assistant-input">Your question</label>
        <input id="assistant-input" type="text" value={draft} maxLength={1000} placeholder="Ask a question…" disabled={state.waiting}
          onChange={(e) => setDraft(e.target.value)} />
        <button type="submit" className="primary" disabled={state.waiting || !draft.trim()}>Send</button>
      </form>

      {zoom && (
        <div className="lightbox" role="dialog" aria-modal="true" aria-label="Picture the AI looked at">
          <img src={frameSrc(zoom)} alt="Enlarged picture the AI looked at" />
          <button type="button" onClick={() => setZoom(null)} autoFocus>Close</button>
        </div>
      )}
    </section>
  );
}
