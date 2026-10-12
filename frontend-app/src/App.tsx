import { useEffect, useState } from "react";
import { api } from "./api";
import { PAGES } from "./pages/registry";
import type { Meta } from "./types";

export function App() {
  const [page, setPage] = useState(PAGES[0].key);
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => { api<Meta>("/api/meta").then(setMeta).catch(() => setMeta(null)); }, []);
  useEffect(() => {
    const go = (e: Event) => { const p = (e as CustomEvent<{ page?: string }>).detail?.page; if (p && PAGES.some((x) => x.key === p)) setPage(p); };
    window.addEventListener("guardlens:navigate", go);
    return () => window.removeEventListener("guardlens:navigate", go);
  }, []);
  const Page = PAGES.find((p) => p.key === page)?.component ?? PAGES[0].component;
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
      <main><Page meta={meta} /></main>
    </div>
  );
}
