import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IncidentReport } from "../components/IncidentReport";
import { RuleAssist } from "../components/RuleAssist";
import { levelLabel, levelOf, levelTone, sortIssues } from "./healthIssues";
import { parseMarkdown, renderInline } from "./markdown";
import { describePreview, hasProblems, summarizeProposal, type Proposal } from "./ruleDraft";
import type { Camera, PluginType } from "../types";

const types: PluginType[] = [{
  key: "after_hours", label: "After-hours presence", fields: [
    { name: "start", type: "time", label: "Starts at", help: "", required: false },
    { name: "classes", type: "string_list", label: "Watch for", help: "", required: false },
  ],
}];
const cameras: Camera[] = [{ id: 3, name: "Back door", enabled: true }];
const proposal: Proposal = {
  type: "after_hours", name: "Back door at night", camera_id: 3, zone_id: null, severity: "critical", cooldown_seconds: 90,
  params: { start: "22:00", classes: ["person"] }, explanation: "Alerts when a person is at the back door at night.", problems: [],
};

afterEach(() => vi.unstubAllGlobals());

describe("summarizeProposal", () => {
  it("uses names and labels, never ids or JSON", () => {
    const s = summarizeProposal(proposal, types, cameras, []);
    expect(s.typeLabel).toBe("After-hours presence");
    expect(s.where).toBe("Back door");
    expect(s.wait).toBe("1.5 minutes");
    expect(s.settings).toEqual([{ label: "Starts at", text: "22:00" }, { label: "Watch for", text: "person" }]);
    expect(JSON.stringify(s)).not.toMatch(/"3"|camera_id/);
  });
  it("flags problems", () => { expect(hasProblems({ ...proposal, problems: ["x"] })).toBe(true); expect(hasProblems(proposal)).toBe(false); });
});

describe("describePreview", () => {
  it("words counts, examples and fallbacks", () => {
    const t = describePreview({ supported: true, hours: 72, samples_checked: 10, would_fire: 2, examples: ["2026-01-01T00:00:00Z"] }, () => "Jan 1");
    expect(t).toBe("Over the last 72 hours this would have alerted 2 times. For example: Jan 1.");
    expect(describePreview({ supported: false, hours: 72, note: "No preview." })).toBe("No preview.");
    expect(describePreview({ supported: true, hours: 72, samples_checked: 0, note: "Nothing yet." })).toBe("Nothing yet.");
  });
});

describe("markdown", () => {
  it("parses headings, bullets and paragraphs", () => {
    expect(parseMarkdown("# Title\n\n- a\n- b\n\nHello\nworld")).toEqual([
      { kind: "heading", level: 1, text: "Title" }, { kind: "list", items: ["a", "b"] }, { kind: "paragraph", text: "Hello world" },
    ]);
  });
  it("renders bold and italic as elements", () => {
    const nodes = renderInline("a **b** *c*") as unknown[];
    expect(nodes).toHaveLength(4);
  });
});

describe("health issue levels", () => {
  it("maps and sorts levels", () => {
    expect(levelLabel("critical")).toBe("Critical");
    expect(levelTone("warning")).toBe("warn");
    expect(levelOf("weird")).toBe("info");
    const sorted = sortIssues([{ level: "info", area: "a", message: "i", fix: "" }, { level: "critical", area: "a", message: "c", fix: "" }]);
    expect(sorted[0].message).toBe("c");
  });
});

function stubFetch(routes: Record<string, (init?: RequestInit) => { status?: number; body: unknown }>) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const key = Object.keys(routes).find((k) => url.startsWith(k));
    const r = key ? routes[key](init) : { body: [] };
    const status = r.status ?? 200;
    return { ok: status < 400, status, statusText: "", json: async () => r.body };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("RuleAssist", () => {
  it("drafts, shows a summary and preview, and saves", async () => {
    const fetchMock = stubFetch({
      "/api/rules/propose": () => ({ body: proposal }),
      "/api/rules/preview": () => ({ body: { supported: true, hours: 72, samples_checked: 5, would_fire: 4, examples: [] } }),
      "/api/cameras/3/zones": () => ({ body: [] }),
      "/api/rules": () => ({ status: 201, body: {} }),
    });
    const onSaved = vi.fn();
    render(<RuleAssist types={types} cameras={cameras} onSaved={onSaved} onEdit={() => undefined} />);
    fireEvent.change(screen.getByLabelText(/Say what you want/), { target: { value: "back door at night" } });
    fireEvent.click(screen.getByRole("button", { name: "Draft a rule" }));
    await screen.findByText("Back door at night");
    expect(screen.getByText("Back door")).toBeTruthy();
    await screen.findByText(/would have alerted 4 times/);
    fireEvent.click(screen.getByRole("button", { name: /save rule/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const post = fetchMock.mock.calls.find(([u, i]) => u === "/api/rules" && (i as RequestInit).method === "POST")!;
    expect(JSON.parse((post[1] as RequestInit).body as string)).toMatchObject({ type: "after_hours", camera_id: 3, cooldown_seconds: 90 });
  });

  it("disables saving when there are problems and offers edit", async () => {
    stubFetch({ "/api/rules/propose": () => ({ body: { ...proposal, problems: ["Pick a time."] } }), "/api/cameras/3/zones": () => ({ body: [] }) });
    const onEdit = vi.fn();
    render(<RuleAssist types={types} cameras={cameras} onSaved={() => undefined} onEdit={onEdit} />);
    fireEvent.change(screen.getByLabelText(/Say what you want/), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Draft a rule" }));
    await screen.findByText("Pick a time.");
    expect((screen.getByRole("button", { name: /save rule/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Edit settings" }));
    expect(onEdit).toHaveBeenCalled();
  });

  it("explains a 409 as the helper being off", async () => {
    stubFetch({ "/api/rules/propose": () => ({ status: 409, body: { detail: "off" } }) });
    render(<RuleAssist types={types} cameras={cameras} onSaved={() => undefined} onEdit={() => undefined} />);
    fireEvent.change(screen.getByLabelText(/Say what you want/), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Draft a rule" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/turned off/);
    expect(screen.getByRole("button", { name: "Open Agents" })).toBeTruthy();
  });
});

describe("IncidentReport", () => {
  it("shows the report as readable text and refetches with ai", async () => {
    const fetchMock = stubFetch({ "/api/events/7/incident-report": () => ({ body: { event_id: 7, markdown: "# Incident 7\n\n- **Camera:** Door" } }) });
    render(<IncidentReport eventId={7} />);
    fireEvent.click(screen.getByRole("button", { name: "Incident report" }));
    await screen.findByText("Incident 7");
    expect(screen.getByText("Camera:").tagName).toBe("STRONG");
    expect(screen.getByRole("button", { name: "Download .md" })).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Add AI summary"));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("ai=true"))).toBe(true));
  });
});
