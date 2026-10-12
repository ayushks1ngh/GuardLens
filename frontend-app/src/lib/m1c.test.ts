import { describe, expect, it } from "vitest";
import { extractFirstJpeg } from "./snapshot";
import { zonePayload, zoneProblem } from "./zones";
import { RECORDING_FIELDS, describeRecording, withDefaults } from "./recordingFields";
import { barsFromCounts, fillBuckets, rangeQuery, scaleBars } from "./charts";
import { describeActivity, toReportView } from "./report";
import { describeTest } from "../pages/NotifiersPage";

describe("snapshot", () => {
  it("cuts the jpeg out of a multipart body", () => {
    const body = new Uint8Array([45, 45, 10, 0xff, 0xd8, 1, 2, 3, 0xff, 0xd9, 13, 10]);
    expect(Array.from(extractFirstJpeg(body)!)).toEqual([0xff, 0xd8, 1, 2, 3, 0xff, 0xd9]);
    expect(extractFirstJpeg(new Uint8Array([1, 2, 3]))).toBeNull();
  });
});

describe("zones", () => {
  it("validates and builds the payload", () => {
    expect(zoneProblem("", [])).toMatch(/name/);
    expect(zoneProblem("Door", [[0, 0], [1, 1]])).toMatch(/3 corners/);
    expect(zoneProblem("Door", [[0, 0], [1, 0], [1, 1]])).toBeNull();
    expect(zonePayload("  Door ", [[0.1, 0.2], [0.5, 0.2], [0.5, 0.9]])).toEqual({ name: "Door", polygon: [[0.1, 0.2], [0.5, 0.2], [0.5, 0.9]] });
  });
});

describe("recording", () => {
  it("covers every API field with limits matching the backend", () => {
    expect(RECORDING_FIELDS.map((f) => f.name)).toEqual(["enabled", "mode", "pre_roll_seconds", "post_roll_seconds", "max_clip_seconds", "segment_seconds", "retention_days", "quota_mb", "codec_preferences"]);
    expect(RECORDING_FIELDS.find((f) => f.name === "mode")!.enum!.map((c) => c.value)).toEqual(["off", "motion", "event", "continuous"]);
    expect(RECORDING_FIELDS.find((f) => f.name === "retention_days")).toMatchObject({ min: 0, max: 3650 });
  });
  it("fills defaults for a full-body save", () => {
    expect(withDefaults({ enabled: true })).toMatchObject({ enabled: true, mode: "event", retention_days: 7, codec_preferences: ["mp4v", "MJPG"] });
  });
  it("explains status in plain language", () => {
    expect(describeRecording({ enabled: false, mode: "off", active: {}, errors: {}, clips: 0 }).headline).toMatch(/switched off/);
    const s = describeRecording({ enabled: true, mode: "event", active: { "1": "a.mp4" }, errors: { "2": "codec" }, clips: 1 }, (id) => `Cam ${id}`);
    expect(s.tone).toBe("warn");
    expect(s.details.join(" ")).toMatch(/Cam 2 could not record: codec/);
    expect(s.details.join(" ")).toMatch(/1 saved file on disk/);
  });
});

describe("charts", () => {
  it("scales relative to the largest", () => {
    expect(scaleBars([{ label: "a", value: 5 }, { label: "b", value: 10 }]).map((b) => b.pct)).toEqual([50, 100]);
    expect(scaleBars([{ label: "a", value: 0 }])[0].pct).toBe(0);
    expect(barsFromCounts({ x: 1, y: 3 }).map((b) => b.label)).toEqual(["y", "x"]);
  });
  const now = new Date("2026-10-13T05:30:00Z");
  it("builds the query for each range", () => {
    expect(rangeQuery("today", now)).toMatchObject({ from: "2026-10-13T00:00:00.000Z", bucket: "hour" });
    expect(rangeQuery("week", now)).toMatchObject({ from: "2026-10-07T00:00:00.000Z", bucket: "day" });
  });
  it("fills empty buckets with zero", () => {
    const hours = fillBuckets([{ bucket: "2026-10-13T02:00:00Z", count: 4 }], "today", now);
    expect(hours).toHaveLength(6);
    expect(hours[2]).toMatchObject({ label: "02:00", value: 4, pct: 100 });
    const days = fillBuckets([{ bucket: "2026-10-13", count: 2 }], "week", now);
    expect(days).toHaveLength(7);
    expect(days[6]).toMatchObject({ label: "10-13", value: 2 });
  });
});

describe("report", () => {
  it("builds a readable view", () => {
    const v = toReportView({ id: 1, date: "2026-10-13", generated_at: "", generator: "structured", text: "Line one\n\nLine two", content: {
      date: "2026-10-13", event_count: 2, events_by_type: { a: 2 }, events_by_severity: { warning: 2 },
      cameras: { "1": { peak_people: 3, peak_vehicles: 0, known: ["Sam"], unknown_faces: 1, samples: 9 } },
      highlights: [{ id: 5, type: "intrusion", severity: "warning", camera_id: 1, created_at: "2026-10-13T01:00:00" }],
    } });
    expect(v.headline).toBe("2 security events recorded.");
    expect(v.paragraphs).toEqual(["Line one", "Line two"]);
    expect(v.cameras[0]).toMatchObject({ peakPeople: 3, known: ["Sam"] });
    expect(v.highlights[0].type).toBe("intrusion");
  });
  it("copes with an empty report", () => {
    expect(toReportView({ id: 1, date: "2026-10-13", generated_at: "", generator: "x", content: {}, text: "" }).headline).toMatch(/quiet day/);
  });
  it("describes activity samples", () => {
    expect(describeActivity({ people: 2, vehicles: { car: 1, bus: 1 }, known: ["Sam"] })).toBe("2 people, 2 vehicles, recognised Sam");
    expect(describeActivity({})).toBe("Nothing notable");
  });
});

describe("notifier test result", () => {
  it("is readable", () => {
    expect(describeTest({ ok: true })).toMatch(/Test sent/);
    expect(describeTest({ ok: false, error: "notifier failed: timeout" })).toBe("The test did not go through: timeout");
  });
});
