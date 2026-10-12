import { useEffect, useState } from "react";
import { API_BASE } from "../api";

/**
 * One still frame of a camera. The backend has no dedicated snapshot route, so we ask the
 * MJPEG stream for a single frame (`?max_frames=1`) and cut the JPEG out of the multipart body.
 * (Using the URL directly as a CSS background is unreliable for multipart responses.)
 */
export function extractFirstJpeg(bytes: Uint8Array): Uint8Array | null {
  let start = -1;
  for (let i = 0; i + 1 < bytes.length; i++) if (bytes[i] === 0xff && bytes[i + 1] === 0xd8) { start = i; break; }
  if (start < 0) return null;
  let end = -1;
  for (let i = bytes.length - 2; i > start; i--) if (bytes[i] === 0xff && bytes[i + 1] === 0xd9) { end = i + 2; break; }
  return end < 0 ? null : bytes.slice(start, end);
}

export async function fetchSnapshot(cameraId: number, timeoutMs = 8000): Promise<string> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}/stream/${cameraId}/mjpeg?max_frames=1`, { signal: controller.signal });
    if (!response.ok) throw new Error("The camera is not sending video right now.");
    const jpeg = extractFirstJpeg(new Uint8Array(await response.arrayBuffer()));
    if (!jpeg) throw new Error("The camera did not return a picture.");
    return URL.createObjectURL(new Blob([jpeg], { type: "image/jpeg" }));
  } catch (e) {
    if ((e as Error).name === "AbortError") throw new Error("The camera took too long to respond.");
    throw e;
  } finally { clearTimeout(timer); }
}

/** Snapshot for the chosen camera: { url, loading, error, refresh }. */
export function useSnapshot(cameraId: number | null) {
  const [url, setUrl] = useState<string | undefined>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (cameraId === null) { setUrl(undefined); setError(""); return; }
    let cancelled = false; let made: string | undefined;
    setLoading(true); setError("");
    fetchSnapshot(cameraId)
      .then((u) => { made = u; if (cancelled) URL.revokeObjectURL(u); else setUrl(u); })
      .catch((e: Error) => { if (!cancelled) { setUrl(undefined); setError(e.message); } })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made); };
  }, [cameraId, tick]);
  return { url, loading, error, refresh: () => setTick((t) => t + 1) };
}
