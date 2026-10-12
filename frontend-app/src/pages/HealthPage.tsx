import { useEffect, useState } from "react";
import { api } from "../api";
import type { Camera, Meta } from "../types";

interface CameraStatus {
  camera_id: number; connected: boolean; fps: number; source_type: string;
  last_frame_age: number | null; error: string | null;
}
interface Health { status: string; version: string; analysis_enabled: boolean; cameras: CameraStatus[] }

/** Plain-language camera state, so no one has to read raw status JSON. */
export function describeCamera(camera: Camera | undefined, status: CameraStatus | undefined): { text: string; tone: "ok" | "warn" | "off" } {
  if (camera && !camera.enabled) return { text: "Switched off", tone: "off" };
  if (!status) return { text: "Starting…", tone: "warn" };
  if (!status.connected) {
    return status.source_type === "webrtc"
      ? { text: "Waiting for the phone/browser to connect", tone: "warn" }
      : { text: status.error ? `Can’t reach the camera (${status.error})` : "Connecting…", tone: "warn" };
  }
  if (status.last_frame_age !== null && status.last_frame_age > 5) return { text: "Video has stalled", tone: "warn" };
  return { text: `Live · ${status.fps} frames/sec`, tone: "ok" };
}

export function HealthPage({ meta }: { meta: Meta | null }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  useEffect(() => {
    const tick = () => {
      api<Health>("/health").then(setHealth).catch(() => setHealth(null));
      api<Camera[]>("/api/cameras").then(setCameras).catch(() => undefined);
    };
    tick();
    const timer = window.setInterval(tick, 5000);
    return () => window.clearInterval(timer);
  }, []);
  const yes = (v?: boolean) => (v ? "Available" : "Not set up");
  return (
    <section>
      <h2>System health</h2>
      <div className="card">
        <p>{health ? <>Server running · version {health.version}</> : "Can’t reach the server."}</p>
        {meta && (
          <ul className="list">
            <li>AI assistant (cloud vision): <strong>{yes(meta.capabilities.vlm)}</strong></li>
            <li>Video recording: <strong>{meta.capabilities.recording ? "On" : "Off"}</strong></li>
            <li>Secure (HTTPS) connection: <strong>{meta.capabilities.https ? "On" : "Off"}</strong></li>
          </ul>
        )}
      </div>
      <h3>Cameras</h3>
      <ul className="list">
        {cameras.map((camera) => {
          const state = describeCamera(camera, health?.cameras.find((s) => s.camera_id === camera.id));
          return (
            <li key={camera.id} className="row">
              <span className={`dot ${state.tone}`} aria-hidden />
              <strong className="grow">{camera.name}</strong>
              <span>{state.text}</span>
            </li>
          );
        })}
        {!cameras.length && <li className="hint">No cameras added yet.</li>}
      </ul>
    </section>
  );
}
