export interface EventUsed { id: number; type: string; camera: string; created_at: string; title: string | null }
export interface ChatResponse {
  session_id: string; answer: string; citations: number[]; frame_url: string | null; camera: string | null;
  provider: string; model: string; events_used: EventUsed[];
}
export interface ChatMessage {
  id: number; role: "user" | "assistant" | "error"; text: string;
  citations?: number[]; frameUrl?: string | null; camera?: string | null; provider?: string; model?: string;
}
export interface ChatState { messages: ChatMessage[]; sessionId: string | null; waiting: boolean }

export type ChatAction =
  | { type: "ask"; text: string }
  | { type: "answer"; response: ChatResponse }
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
    case "fail":
      return { ...state, waiting: false, messages: [...state.messages, { id: nextId, role: "error", text: action.text }] };
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
