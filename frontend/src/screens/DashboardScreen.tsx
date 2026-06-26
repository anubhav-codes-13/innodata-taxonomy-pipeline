import { useEffect, useState } from "react";
import { AppShell, Container } from "../components/AppShell";
import { Button, Card, PageTitle } from "../components/ui";
import { useKeywordStats } from "../lib/hooks";
import type { Domain, TaxonomyLevel } from "../lib/types";

const PAGE_SIZE = 10;

const LEVEL_OPTIONS: { value: TaxonomyLevel; label: string }[] = [
  { value: "L4", label: "L4 — Keywords" },
  { value: "L1", label: "L1 — Domains" },
  { value: "L2", label: "L2 — Topics" },
  { value: "L3", label: "L3 — Sub-topics" },
];

const LEVEL_CHART_TITLE: Record<TaxonomyLevel, string> = {
  L1: "Domains by frequency",
  L2: "Topics by frequency",
  L3: "Sub-topics by frequency",
  L4: "Keywords by frequency",
};

const LEVEL_EMPTY_MSG: Record<TaxonomyLevel, string> = {
  L1: "No domain data yet — enrich some documents first.",
  L2: "No topic data yet — enrich some documents first.",
  L3: "No sub-topic data yet — enrich some documents first.",
  L4: "No keywords yet — enrich some documents and they'll appear here, ranked by how many documents use them.",
};

export function DashboardScreen() {
  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState<"" | Domain>("");
  const [level, setLevel] = useState<TaxonomyLevel>("L4");
  const [page, setPage] = useState(1);

  const { data = [], isLoading, isError, error } = useKeywordStats({
    level,
    domain: domain || undefined,
    search: search || undefined,
    limit: 500,
  });

  // Reset page on any filter change
  useEffect(() => setPage(1), [search, domain, level]);

  const apiBase = import.meta.env.VITE_API_BASE_URL;
  const max = data.length ? data[0].frequency : 0;
  const total = data.length;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const current = Math.min(page, totalPages);
  const start = (current - 1) * PAGE_SIZE;
  const pageItems = data.slice(start, start + PAGE_SIZE);

  const select = "rounded-lg border border-line bg-white px-3 py-2 text-xs font-semibold text-body";
  const barColor = domain === "KCL" ? "#3B2B9B" : "#2B5C9B";

  return (
    <AppShell sidebar>
      <Container>
        <PageTitle sub="How often each item appears across all enriched documents — most frequent first.">
          Taxonomy dashboard
        </PageTitle>

        <div className="mb-5 flex flex-wrap items-center gap-3">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="search..."
            className="w-72 rounded-lg border border-line bg-white px-3 py-2 text-sm text-body placeholder:text-mut"
          />
          <div className="flex-1" />
          <select
            className={select}
            value={level}
            onChange={(e) => setLevel(e.target.value as TaxonomyLevel)}
          >
            {LEVEL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select className={select} value={domain} onChange={(e) => setDomain(e.target.value as "" | Domain)}>
            <option value="">All domains</option>
            <option value="KA">KA — Arbitration</option>
            <option value="KCL">KCL — Competition</option>
          </select>
        </div>

        <Card className="p-5">
          <div className="mb-4 flex items-center gap-2">
            <h2 className="text-sm font-bold text-ink">{LEVEL_CHART_TITLE[level]}</h2>
            <span className="rounded-full bg-[#EDF0F2] px-2 py-0.5 text-[11px] font-semibold text-mut">{data.length}</span>
          </div>

          {isLoading && <p className="text-sm text-mut">Loading...</p>}
          {isError && (
            <p className="text-sm text-[#9B2B2B]">
              Could not load data{apiBase ? ` from ${apiBase}` : ""}: {(error as Error).message}
            </p>
          )}
          {!isLoading && !isError && data.length === 0 && (
            <p className="text-sm text-mut">{LEVEL_EMPTY_MSG[level]}</p>
          )}

          <div className="space-y-2.5">
            {pageItems.map((k, i) => (
              <div key={k.keyword} className="flex items-center gap-3">
                <div className="w-6 shrink-0 text-right text-[12px] text-mut">{start + i + 1}</div>
                <div className="w-52 shrink-0 truncate text-[13px] font-medium text-ink" title={k.keyword}>
                  {k.keyword}
                </div>
                <div className="h-6 flex-1 overflow-hidden rounded bg-panel">
                  <div
                    className="h-full rounded"
                    style={{ width: `${max ? Math.max((k.frequency / max) * 100, 3) : 0}%`, backgroundColor: barColor }}
                  />
                </div>
                <div className="w-10 shrink-0 text-right text-[13px] font-semibold text-body">{k.frequency}</div>
              </div>
            ))}
          </div>

          {total > 0 && (
            <div className="mt-5 flex items-center justify-between border-t border-hair pt-4">
              <span className="text-xs text-mut">
                Showing {start + 1}–{Math.min(start + PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex items-center gap-3">
                <Button variant="secondary" disabled={current <= 1} onClick={() => setPage(current - 1)}>
                  &larr; Prev
                </Button>
                <span className="text-xs font-semibold text-body">
                  Page {current} of {totalPages}
                </span>
                <Button variant="secondary" disabled={current >= totalPages} onClick={() => setPage(current + 1)}>
                  Next &rarr;
                </Button>
              </div>
            </div>
          )}
        </Card>

        <p className="mt-4 text-[11px] text-mut">
          Frequency = number of documents an item appears in.
        </p>
      </Container>
    </AppShell>
  );
}
