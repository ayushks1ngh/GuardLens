export interface EventUsed { id: number; type: string; camera: string; created_at: string; title: string | null }
export interface ChatResponse {
  session_id: string; answer: string; citations: number[]; frame_url: string | null; camera: string | null;
  provider: string; model: string; events_used: EventUsed[];
}
export interface ChatMessage {
  id: number; role: "user" | "assistant" | "error"; text: string;
  citations?: number[]; frameUrl?: string | null; camera?: string | null; provider?: string; model?: string;
  streaming?: boolean;
}
export interface ChatState { messages: ChatMessage[]; sessionId: string | null; waiting: boolean }

export type ChatAction =
  | { type: "ask"; text: string }
  | { type: "answer"; response: ChatResponse }
  | { type: "stream_start"; sessionId: string; frameUrl: string | null; camera: string | null }
  | { type: "stream_delta"; text: string }
  | { type: "stream_done"; response: ChatResponse }
  | { type: "fail"; text: string }
  | { type: "reset" };

export const initialChat: ChatState = { messages: [], sessionId: null, waiting: false };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  const nextId = state.messages.length ? state.messages[state.messages.length - 1].id + 1 : 1;
  switch (action.type) {
    case "ask":
      return { ...state, waiting: true, messages: [...state.messages, { id: nextId, role: "user", text: action.text }] };
    case "answer": {
      const r = action.response;
      return {
        waiting: false, sessionId: r.session_id,
        messages: [...state.messages, {
          id: nextId, role: "assistant", text: r.answer, citations: r.citations ?? [], frameUrl: r.frame_url,
          camera: r.camera, provider: r.provider, model: r.model,
        }],
      };
    }
    case "stream_start":
      return {
        ...state, sessionId: action.sessionId,
        messages: [...state.messages, { id: nextId, role: "assistant", text: "", streaming: true, frameUrl: action.frameUrl, camera: action.camera }],
      };
    case "stream_delta": {
      const last = state.messages[state.messages.length - 1];
      if (!last?.streaming) return state;
      return { ...state, messages: [...state.messages.slice(0, -1), { ...last, text: last.text + action.text }] };
    }
    case "stream_done": {
      const r = action.response;
      const final = { role: "assistant" as const, text: r.answer, citations: r.citations ?? [], frameUrl: r.frame_url, camera: r.camera, provider: r.provider, model: r.model, streaming: false };
      const last = state.messages[state.messages.length - 1];
      const messages = last?.streaming ? [...state.messages.slice(0, -1), { ...final, id: last.id }] : [...state.messages, { ...final, id: nextId }];
      return { waiting: false, sessionId: r.session_id, messages };
    }
    case "fail": {
      // A half-written streaming answer is dropped in favour of the error.
      const kept = state.messages.filter((m) => !(m.streaming && !m.text));
      const id = kept.length ? kept[kept.length - 1].id + 1 : 1;
      return { ...state, waiting: false, messages: [...kept.map((m) => (m.streaming ? { ...m, streaming: false } : m)), { id, role: "error", text: action.text }] };
    }
    case "reset":
      return initialChat;
  }
}

export function chatErrorText(status: number | undefined, detail?: string): string {
  switch (status) {
    case 503: return "No AI service is set up yet. Add an API key on the Agents page to turn on Ask GuardLens.";
    case 429: return "The AI is busy or today's free allowance is used up. Please try again in a little while.";
    case 403: return "This camera is set to keep its video on this device, so the AI is not allowed to look at it. You can change this on the Agents page.";
    case 502: return "The AI service did not answer properly. Please try again.";
    default: return detail && status && status < 500 ? detail : "Something went wrong. Please try again.";
  }
}

export const STARTER_QUESTIONS = [
  "What happened today?", "Which camera has people in it right now?", "Anything unusual in the last hour?",
];

const KEY = "guardlens.assistantSession";
export function loadSession(): string | null {
  try { return sessionStorage.getItem(KEY); } catch { return null; }
}
export function saveSession(id: string | null): void {
  try { if (id) sessionStorage.setItem(KEY, id); else sessionStorage.removeItem(KEY); } catch { /* storage blocked */ }
}
