import { useCallback, useEffect, useState } from "react";
import { API_BASE, api } from "../api";
import { BarList, ColumnChart } from "../components/Charts";
import { RANGES, barsFromCounts, fillBuckets, rangeQuery, scaleBars, type Range } from "../lib/charts";
import { describeActivity, humanize, toReportView, todayIso } from "../lib/report";
import type { ActivityRow, AnalyticsSummary, Camera, CameraCount, Meta, ReportRow, TimelinePoint } from "../types";

type Tab = "daily" | "activity" | "analytics";
const TABS: { key: Tab; label: string }[] = [
  { key: "daily", label: "Daily report" }, { key: "activity", label: "Activity" }, { key: "analytics", label: "Charts" },
];

function cameraNamer(cameras: Camera[]) {
  return (id: number | string) => cameras.find((c) => String(c.id) === String(id))?.name ?? `Camera ${id}`;
}

function DailyReport({ date, cameras }: { date: string; cameras: Camera[] }) {
  const [report, setReport] = useState<ReportRow | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const name = cameraNamer(cameras);
  const load = useCallback(async (regenerate: boolean) => {
    setBusy(true); setMessage("");
    try {
      setReport(await api<ReportRow>(`/api/reports/daily${regenerate ? "/regenerate" : ""}?date=${date}`, { method: regenerate ? "POST" : "GET" }));
    } catch (e) { setReport(null); setMessage(e instanceof Error ? e.message : "Could not load the report."); }
    finally { setBusy(false); }
  }, [date]);
  useEffect(() => { void load(false); }, [load]);
  const view = report ? toReportView(report) : null;
  return (
    <div>
      <div className="actions">
        <button type="button" onClick={() => load(true)} disabled={busy}>Refresh this report</button>
        <a className="button-like" href={`${API_BASE}/api/reports/daily/download?date=${date}`} download>Download as text</a>
      </div>
      {busy && <p className="hint" role="status">Loading…</p>}
      {message && <p className="error" role="alert">{message}</p>}
      {view && report && (
        <div className="card">
          <h3>{view.date}: {view.headline}</h3>
          <p className="hint">Written {new Date(report.generated_at).toLocaleString()}</p>
          {view.paragraphs.map((p, i) => <p key={i}>{p}</p>)}
          <div className="chart-grid">
            <BarList title="Events by type" bars={barsFromCounts(view.byType, humanize)} empty="No events." />
            <BarList title="Events by seriousness" bars={barsFromCounts(view.bySeverity, humanize)} empty="No events." />
          </div>
          {view.cameras.length > 0 && (
            <>
              <h4>Cameras</h4>
              <ul className="list">
                {view.cameras.map((c) => (
                  <li key={c.id} className="row"><div className="grow"><strong>{name(c.id)}</strong>
                    <div className="hint">
                      Most people at once: {c.peakPeople} · Most vehicles at once: {c.peakVehicles}
                      {c.known.length ? ` · Recognised: ${c.known.join(", ")}` : ""}{c.unknownFaces ? ` · Unknown faces: ${c.unknownFaces}` : ""}
                    </div></div></li>
                ))}
              </ul>
            </>
          )}
          {view.highlights.length > 0 && (
            <>
              <h4>Things worth a look</h4>
              <ul className="list">
                {view.highlights.map((h) => (
                  <li key={h.id} className="row"><span className={`badge ${h.severity}`}>{h.severity}</span>
                    <div className="grow">{humanize(h.type)} on {name(h.cameraId)}<div className="hint">{h.time ? new Date(h.time).toLocaleTimeString() : ""}</div></div></li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ActivityList({ date, cameras }: { date: string; cameras: Camera[] }) {
  const [cameraId, setCameraId] = useState<number | "">("");
  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [message, setMessage] = useState("");
  const name = cameraNamer(cameras);
  useEffect(() => {
    const from = `${date}T00:00:00Z`;
    const to = new Date(Date.parse(from) + 86400000).toISOString();
    const query = new URLSearchParams({ from, to, limit: "200" });
    if (cameraId !== "") query.set("camera_id", String(cameraId));
    api<ActivityRow[]>(`/api/activity?${query}`).then((r) => { setRows(r); setMessage(""); })
      .catch((e: Error) => setMessage(e.message));
  }, [date, cameraId]);
  return (
    <div>
      <p className="field"><label htmlFor="activity-camera">Camera</label>
        <select id="activity-camera" value={cameraId} onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : "")}>
          <option value="">All cameras</option>
          {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select></p>
      {message && <p className="error" role="alert">{message}</p>}
      <ul className="list">
        {rows.map((r) => (
          <li key={r.id} className="row"><span className="hint">{new Date(r.timestamp).toLocaleTimeString()}</span>
            <div className="grow"><strong>{name(r.camera_id)}</strong> <span className="hint">{describeActivity(r.summary)}</span></div></li>
        ))}
        {!rows.length && !message && <li className="hint">No activity was logged on this day.</li>}
      </ul>
    </div>
  );
}

function Analytics({ cameras }: { cameras: Camera[] }) {
  const [range, setRange] = useState<Range>("week");
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [timeline, setTimeline] = useState<TimelinePoint[]>([]);
  const [byCamera, setByCamera] = useState<CameraCount[]>([]);
  const [message, setMessage] = useState("");
  const name = cameraNamer(cameras);
  useEffect(() => {
    const q = rangeQuery(range);
    const range_ = new URLSearchParams({ from: q.from, to: q.to });
    Promise.all([
      api<AnalyticsSummary>(`/api/analytics/summary?${range_}`),
      api<TimelinePoint[]>(`/api/analytics/timeline?${range_}&bucket=${q.bucket}`),
      api<CameraCount[]>("/api/analytics/by-camera"),
    ]).then(([s, t, c]) => { setSummary(s); setTimeline(t); setByCamera(c); setMessage(""); })
      .catch((e: Error) => setMessage(e.message));
  }, [range]);
  return (
    <div>
      <p className="field"><label htmlFor="analytics-range">Period</label>
        <select id="analytics-range" value={range} onChange={(e) => setRange(e.target.value as Range)}>
          {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select></p>
      {message && <p className="error" role="alert">{message}</p>}
      {summary && (
        <div className="card">
          <p><strong>{summary.total}</strong> event{summary.total === 1 ? "" : "s"} in this period.</p>
          <ColumnChart title="Events over time" bars={fillBuckets(timeline, range)} />
          <div className="chart-grid">
            <BarList title="By type" bars={barsFromCounts(summary.by_type, humanize)} />
            <BarList title="By seriousness" bars={barsFromCounts(summary.by_severity, humanize)} />
            <BarList title="By camera (all time)" bars={scaleBars(byCamera.map((c) => ({ label: name(c.camera_id), value: c.count })).sort((a, b) => b.value - a.value))} />
          </div>
        </div>
      )}
    </div>
  );
}

export function ReportsPage(_props: { meta: Meta | null }) {
  const [tab, setTab] = useState<Tab>("daily");
  const [date, setDate] = useState(todayIso());
  const [cameras, setCameras] = useState<Camera[]>([]);
  useEffect(() => { api<Camera[]>("/api/cameras").then(setCameras).catch(() => setCameras([])); }, []);
  return (
    <section>
      <header className="page-head">
        <h2>Reports</h2>
        {tab !== "analytics" && (
          <label>Day <input type="date" value={date} max={todayIso()} onChange={(e) => e.target.value && setDate(e.target.value)} /></label>
        )}
      </header>
      <div className="tabs" role="group" aria-label="Report sections">
        {TABS.map((t) => (
          <button key={t.key} type="button" aria-pressed={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>
      {tab === "daily" && <DailyReport date={date} cameras={cameras} />}
      {tab === "activity" && <ActivityList date={date} cameras={cameras} />}
      {tab === "analytics" && <Analytics cameras={cameras} />}
    </section>
  );
}
