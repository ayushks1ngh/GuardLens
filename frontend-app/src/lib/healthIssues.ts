export type IssueLevel = "info" | "warning" | "critical";
export interface HealthIssue { level: IssueLevel; area: string; message: string; fix: string }

const LABEL: Record<IssueLevel, string> = { critical: "Critical", warning: "Warning", info: "Info" };
const TONE: Record<IssueLevel, string> = { critical: "crit", warning: "warn", info: "ok" };
const ORDER: Record<IssueLevel, number> = { critical: 0, warning: 1, info: 2 };

export function levelOf(level: string): IssueLevel { return level === "critical" || level === "warning" ? level : "info"; }
export const levelLabel = (level: string) => LABEL[levelOf(level)];
export const levelTone = (level: string) => TONE[levelOf(level)];
export const sortIssues = (issues: HealthIssue[]) => [...issues].sort((a, b) => ORDER[levelOf(a.level)] - ORDER[levelOf(b.level)]);
