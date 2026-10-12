import { describe, expect, it } from "vitest";
import { buildChoices, buildSourcePayload, wizardState, withDevices, toField, type SourceType } from "./sources";

const types: SourceType[] = [
  { key: "opencv", label: "Local", modes: [
    { key: "device", label: "Device", fields: [
      { key: "device_index", label: "Device index", type: "integer", default: 0 },
      { key: "pixel_format", label: "Pixel format", type: "select", default: "MJPG", options: ["MJPG", "YUYV"] },
    ] },
    { key: "network", label: "URL", fields: [{ key: "url", label: "URL", type: "url", required: true }] },
  ] },
  { key: "webrtc", label: "Browser", modes: [{ key: "publisher", label: "Publisher", fields: [{ key: "stream_id", label: "Stream ID", type: "text", required: true }] }] },
];
const [device, network, phone] = buildChoices(types);

describe("source choices", () => {
  it("flattens modes and flags pairing", () => {
    expect(buildChoices(types).map((c) => c.id)).toEqual(["opencv:device", "opencv:network", "webrtc:publisher"]);
    expect(phone.pairing).toBe(true);
    expect(device.title).toBe("This computer’s camera");
  });
  it("adapts select options and device lists", () => {
    expect(toField({ key: "k", label: "K", type: "select", options: ["a"] }).type).toBe("enum");
    const withList = withDevices(device.fields, [{ index: 2, path: "/dev/video2", label: "video2" }]);
    expect(withList[0].type).toBe("enum");
    expect(withList[0].default).toBe(2);
  });
});

describe("wizardState", () => {
  const base = { pairing: null, probedFingerprint: null, name: "Door" };
  it("requires required fields before testing", () => {
    expect(wizardState({ ...base, choice: network, values: {} }).canTest).toBe(false);
    expect(wizardState({ ...base, choice: network, values: { url: "rtsp://x" } }).canTest).toBe(true);
  });
  it("only allows adding after a passing test, a name, and an unchanged source", () => {
    const values = { url: "rtsp://x" };
    const fp = JSON.stringify(buildSourcePayload(network, values));
    expect(wizardState({ ...base, choice: network, values }).canAdd).toBe(false);
    expect(wizardState({ ...base, choice: network, values, probedFingerprint: fp }).canAdd).toBe(true);
    expect(wizardState({ ...base, choice: network, values, probedFingerprint: fp, name: " " }).canAdd).toBe(false);
    const edited = wizardState({ ...base, choice: network, values: { url: "rtsp://y" }, probedFingerprint: fp });
    expect(edited.canAdd).toBe(false);
    expect(edited.stale).toBe(true);
  });
  it("pairing is ready once the link exists, with no probe", () => {
    expect(wizardState({ ...base, choice: phone, values: {} }).canAdd).toBe(false);
    const s = wizardState({ ...base, choice: phone, values: {}, pairing: { stream_id: "abc12345" } });
    expect(s.canAdd).toBe(true);
    expect(s.canTest).toBe(false);
  });
  it("builds typed payloads with defaults and trimmed text", () => {
    expect(buildSourcePayload(device, {})).toEqual({ source_type: "opencv", source_config: { mode: "device", device_index: 0, pixel_format: "MJPG" } });
    expect(buildSourcePayload(phone, {}, { stream_id: "s" })).toEqual({ source_type: "webrtc", source_config: { mode: "publisher", stream_id: "s" } });
    expect(buildSourcePayload(network, { url: "  rtsp://a " }).source_config.url).toBe("rtsp://a");
  });
});
