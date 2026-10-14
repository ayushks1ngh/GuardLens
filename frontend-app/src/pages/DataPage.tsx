import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Meta } from "../types";

interface Backup { name: string; kind: "auto" | "manual"; size_mb: number; created_at: string }
interface DataStatus {
  backups: Backup[];
  storage: { database_mb: number; pictures_mb: number; clips_mb: number; backups_mb: number };
  backup_policy: { enabled: boolean; daily_at: string; keep_days: number };
  retention_policy: { enabled: boolean; events_days: number };
}

export function retentionText(p: DataStatus["retention_policy"]): string {
  return p.enabled
    ? `Events and their pictures older than ${p.events_days} days are removed automatically. Alerts nobody has resolved yet that are critical are always kept.`
    : "Automatic clean-up is off: events and pictures are kept forever.";
}

export function backupText(p: DataStatus["backup_policy"]): string {
  return p.enabled
    ? `A copy of the database is made every day at ${p.daily_at} and kept for ${p.keep_days} days (the newest 3 are always kept).`
    : "Automatic backups are off.";
}

export function DataPage({ meta: _meta }: { meta: Meta | null }) {
  const [status, setStatus] = useState<DataStatus | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const load = useCallback(() => api<DataStatus>("/api/data/status").then(setStatus).catch(() => setMessage({ ok: false, text: "Could not load data information." })), []);
  useEffect(() => { void load(); }, [load]);

  const run = async (work: () => Promise<string>) => {
    setBusy(true); setMessage(null);
    try { setMessage({ ok: true, text: await work() }); await load(); }
    catch (e) { setMessage({ ok: false, text: e instanceof ApiError ? e.message : "That did not work." }); }
    finally { setBusy(false); }
  };

  return (
    <section className="data-page">
      <div className="page-head"><h2>Data</h2></div>
      {message && <p className={message.ok ? "ok-text" : "error"} role={message.ok ? "status" : "alert"}>{message.text}</p>}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Backups</h3>
        {status && <p className="hint">{backupText(status.backup_policy)}</p>}
        <button type="button" className="primary" disabled={busy}
          onClick={() => run(async () => { const b = await api<Backup>("/api/data/backups", { method: "POST" }); return `Backup saved: ${b.name}`; })}>
          Back up now
        </button>
        {status && status.backups.length === 0 && <p className="hint">No backups yet.</p>}
        <ul className="list">
          {status?.backups.map((b) => (
            <li key={b.name} className="row">
              <div className="grow">
                <strong>{new Date(b.created_at).toLocaleString()}</strong>
                <div className="hint">{b.kind === "auto" ? "Automatic" : "Made by hand"} · {b.size_mb} MB</div>
              </div>
              <a href={`/api/data/backups/${b.name}`} download>Download</a>
              {confirmDelete === b.name ? (
                <>
                  <span>Delete this backup?</span>
                  <button type="button" onClick={() => run(async () => { await api(`/api/data/backups/${b.name}`, { method: "DELETE" }); setConfirmDelete(null); return "Backup deleted."; })}>Yes, delete</button>
                  <button type="button" onClick={() => setConfirmDelete(null)}>Cancel</button>
                </>
              ) : <button type="button" aria-label={`Delete backup from ${new Date(b.created_at).toLocaleString()}`} onClick={() => setConfirmDelete(b.name)}>Delete</button>}
            </li>
          ))}
        </ul>
        <p className="hint">To restore: stop GuardLens, run <code>python scripts/restore_backup.py</code>, then start it again.</p>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Keeping old events</h3>
        {status && <p className="hint">{retentionText(status.retention_policy)}</p>}
        <button type="button" disabled={busy}
          onClick={() => run(async () => { const r = await api<{ events_removed: number }>("/api/data/cleanup", { method: "POST" }); return r.events_removed ? `Removed ${r.events_removed} old events.` : "Nothing old enough to remove."; })}>
          Clean up now
        </button>
        <p className="hint">Change the number of days in <code>config.yaml</code> (<code>retention.events_days</code>).</p>
      </div>

      {status && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Disk use</h3>
          <ul className="list">
            <li>Database: {status.storage.database_mb} MB</li>
            <li>Pictures: {status.storage.pictures_mb} MB</li>
            <li>Video clips: {status.storage.clips_mb} MB</li>
            <li>Backups: {status.storage.backups_mb} MB</li>
          </ul>
        </div>
      )}
    </section>
  );
}
