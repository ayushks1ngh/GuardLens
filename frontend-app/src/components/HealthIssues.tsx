import { useEffect, useState } from "react";
import { api } from "../api";
import { levelLabel, levelOf, levelTone, sortIssues, type HealthIssue } from "../lib/healthIssues";

export function HealthIssues() {
  const [issues, setIssues] = useState<HealthIssue[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const tick = () => api<HealthIssue[]>("/api/health/issues").then((r) => { setIssues(r); setFailed(false); }).catch(() => setFailed(true));
    tick();
    const timer = window.setInterval(tick, 15000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className="health-issues">
      <h3>Needs attention</h3>
      {failed && <p className="error" role="alert">Could not check for problems right now.</p>}
      {issues && !issues.length && <p className="card" role="status">All clear. Nothing needs your attention.</p>}
      <ul className="list">
        {issues && sortIssues(issues).map((issue, i) => (
          <li key={i} className={`card issue issue-${levelOf(issue.level)}`}>
            <span className={`pill pill-${levelTone(issue.level)}`}>{levelLabel(issue.level)}</span>
            <p><strong>{issue.message}</strong></p>
            {issue.fix && <p className="hint">How to fix: {issue.fix}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
