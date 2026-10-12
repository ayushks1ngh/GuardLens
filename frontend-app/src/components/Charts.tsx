import type { Bar } from "../lib/charts";

/** Horizontal bars with the value written next to each (no colour-only meaning). */
export function BarList({ title, bars, empty = "Nothing to show yet." }: { title: string; bars: Bar[]; empty?: string }) {
  return (
    <div className="chart">
      <h4>{title}</h4>
      {bars.length === 0 ? <p className="hint">{empty}</p> : (
        <ul className="bars">
          {bars.map((b) => (
            <li key={b.label}>
              <span className="bar-label">{b.label}</span>
              <span className="bar-track" aria-hidden><span className="bar-fill" style={{ width: `${b.pct}%` }} /></span>
              <span className="bar-value">{b.value}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Column chart over time as inline SVG; a screen-reader list carries the same numbers. */
export function ColumnChart({ title, bars }: { title: string; bars: Bar[] }) {
  const n = bars.length;
  const step = n > 12 ? Math.ceil(n / 8) : 1;
  const total = bars.reduce((a, b) => a + b.value, 0);
  return (
    <div className="chart">
      <h4>{title}</h4>
      {n === 0 || total === 0 ? <p className="hint">No events in this period.</p> : (
        <>
          <svg viewBox={`0 0 ${n * 10} 64`} className="columns" role="img" aria-label={`${title}: ${total} events in total`} preserveAspectRatio="none">
            {bars.map((b, i) => (
              <rect key={b.label} x={i * 10 + 1} width={8} y={50 - (b.pct / 100) * 48} height={Math.max(b.value > 0 ? 1 : 0, (b.pct / 100) * 48)} className="column">
                <title>{`${b.label}: ${b.value}`}</title>
              </rect>
            ))}
          </svg>
          <div className="column-labels" aria-hidden>
            {bars.map((b, i) => <span key={b.label} style={{ visibility: i % step === 0 ? "visible" : "hidden" }}>{b.label}</span>)}
          </div>
          <ul className="sr-only">{bars.map((b) => <li key={b.label}>{b.label}: {b.value}</li>)}</ul>
        </>
      )}
    </div>
  );
}
