import { ChatPanel } from "../components/ChatPanel";
import type { Meta } from "../types";

export function AssistantPage({ meta: _meta }: { meta: Meta | null }) {
  return (
    <section className="assistant-page">
      <h2>Ask GuardLens</h2>
      <ChatPanel />
    </section>
  );
}
