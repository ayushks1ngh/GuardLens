import type { OverlayBox } from "../types";

/** The words drawn on a detection box, e.g. "person 61%" (a recognised name or gesture wins over the class). */
export function boxLabel(box: OverlayBox): string {
  return `${box.name || box.gesture || box.class} ${Math.round(box.conf * 100)}%`;
}

export function boxTone(box: OverlayBox): "person" | "face" | "other" {
  return box.class === "person" ? "person" : box.class === "face" ? "face" : "other";
}

/** CSS position (percent of the picture) for a normalised [x1, y1, x2, y2] box, clamped to the picture. */
export function boxStyle(box: OverlayBox): { left: string; top: string; width: string; height: string } {
  const [x1, y1, x2, y2] = box.bbox.map((v) => Math.min(1, Math.max(0, v)));
  return { left: `${x1 * 100}%`, top: `${y1 * 100}%`, width: `${(x2 - x1) * 100}%`, height: `${(y2 - y1) * 100}%` };
}

export function countsText(counts: Record<string, number> | undefined): string {
  return Object.entries(counts ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ");
}
