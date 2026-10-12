import { describe, expect, it } from "vitest";
import { describeCamera } from "./HealthPage";

const status = (over = {}) => ({ camera_id: 1, connected: true, fps: 12.3, source_type: "opencv", last_frame_age: 0.1, error: null, ...over });

describe("describeCamera", () => {
  it("explains each state in plain language", () => {
    expect(describeCamera({ id: 1, name: "a", enabled: false }, undefined).text).toBe("Switched off");
    expect(describeCamera({ id: 1, name: "a", enabled: true }, status({ connected: false, source_type: "webrtc" })).text).toMatch(/Waiting for the phone/);
    expect(describeCamera({ id: 1, name: "a", enabled: true }, status({ last_frame_age: 9 })).text).toBe("Video has stalled");
    expect(describeCamera({ id: 1, name: "a", enabled: true }, status()).tone).toBe("ok");
  });
});
