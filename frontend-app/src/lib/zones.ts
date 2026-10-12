import type { Point } from "../components/PointsCanvas";

export const MIN_CORNERS = 3;

export function zoneProblem(name: string, polygon: Point[]): string | null {
  if (!name.trim()) return "Give the zone a name.";
  if (polygon.length < MIN_CORNERS) return `Click at least ${MIN_CORNERS} corners on the picture.`;
  return null;
}

/** Body for POST /api/cameras/{id}/zones and PATCH /api/zones/{id}. */
export function zonePayload(name: string, polygon: Point[]) {
  return { name: name.trim(), polygon: polygon.map(([x, y]): [number, number] => [x, y]) };
}
