import type { MouseEvent } from "react";

export type Point = [number, number];

interface Props {
  points: Point[];
  onChange: (points: Point[]) => void;
  /** 1 = single spot, 2 = line, undefined = polygon. */
  maxPoints?: number;
  closed?: boolean;
  /** Optional snapshot so the user draws on what the camera sees. */
  background?: string;
}

/** Click-to-place editor for zones, lines and spots. Coordinates are normalized 0..1. */
export function PointsCanvas({ points, onChange, maxPoints, closed = false, background }: Props) {
  const place = (event: MouseEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    const y = Math.min(1, Math.max(0, (event.clientY - box.top) / box.height));
    const next: Point[] = [...points, [Number(x.toFixed(3)), Number(y.toFixed(3))]];
    onChange(maxPoints && next.length > maxPoints ? next.slice(-maxPoints) : next);
  };
  const path = points.map(([x, y]) => `${x},${y}`).join(" ");
  return (
    <div className="points">
      <div
        className="points-surface"
        role="img"
        aria-label="Click to place points"
        onClick={place}
        style={background ? { backgroundImage: `url(${background})` } : undefined}
      >
        <svg viewBox="0 0 1 1" preserveAspectRatio="none">
          {points.length > 1 && (closed && points.length > 2
            ? <polygon points={path} className="points-shape" />
            : <polyline points={path} className="points-shape" />)}
        </svg>
        {points.map(([x, y], index) => (
          <span key={index} className="points-dot" style={{ left: `${x * 100}%`, top: `${y * 100}%` }}>
            {index + 1}
          </span>
        ))}
      </div>
      <div className="points-actions">
        <button type="button" onClick={() => onChange(points.slice(0, -1))} disabled={!points.length}>Undo</button>
        <button type="button" onClick={() => onChange([])} disabled={!points.length}>Clear</button>
        <span className="hint">
          {maxPoints === 1 ? "Click to set the spot." : maxPoints === 2 ? "Click two points for the line." : "Click to add corners."}
        </span>
      </div>
    </div>
  );
}
