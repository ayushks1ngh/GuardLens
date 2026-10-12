import { useEffect, useState } from "react";
import { api } from "./api";
import { HealthPage } from "./pages/HealthPage";
import { RulesPage } from "./pages/RulesPage";
import type { Meta } from "./types";

const PAGES = [
  { key: "rules", label: "Rules" },
  { key: "health", label: "Health" },
] as const;
type PageKey = (typeof PAGES)[number]["key"];

export function App() {
  const [page, setPage] = useState<PageKey>("rules");
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => { api<Meta>("/api/meta").then(setMeta).catch(() => setMeta(null)); }, []);
  return (
    <div className="shell">
      <nav aria-label="Main">
        <h1>GuardLens</h1>
        {PAGES.map((p) => (
          <button key={p.key} type="button" aria-current={page === p.key ? "page" : undefined} onClick={() => setPage(p.key)}>
            {p.label}
          </button>
        ))}
        <a className="legacy" href="/">Classic dashboard</a>
      </nav>
      <main>
        {page === "rules" && <RulesPage meta={meta} />}
        {page === "health" && <HealthPage meta={meta} />}
      </main>
    </div>
  );
}
