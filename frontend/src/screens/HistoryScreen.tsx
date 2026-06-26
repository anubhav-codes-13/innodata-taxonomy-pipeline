import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell, Container } from "../components/AppShell";
import { Card, DomainChip, PageTitle } from "../components/ui";
import { useDocumentList, useRemoveFile } from "../lib/hooks";
import { formatDate, formatTime } from "../lib/format";
import type { Domain, DocumentListItem } from "../lib/types";

export function HistoryScreen() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState<"" | Domain>("");
  const [type, setType] = useState("");
  const [sort, setSort] = useState<"newest" | "oldest" | "name">("newest");

  const { data, isLoading, isError, error } = useDocumentList({
    search: search || undefined,
    domain: domain || undefined,
    type: type || undefined,
    sort,
  });

  const remove = useRemoveFile();
  const apiBase = import.meta.env.VITE_API_BASE_URL;
  const hasFilters = Boolean(search || domain || type);
  const items = data?.items ?? [];

  const onDelete = (d: DocumentListItem) => {
    if (window.confirm(`Delete "${d.filename}"? This removes the file and its taxonomy.`)) {
      remove.mutate(d.document_id);
    }
  };

  // group consecutive items by processed date
  const groups: { date: string; rows: DocumentListItem[] }[] = [];
  for (const it of items) {
    const date = formatDate(it.processed_at);
    const last = groups[groups.length - 1];
    if (last && last.date === date) last.rows.push(it);
    else groups.push({ date, rows: [it] });
  }

  const select = "rounded-lg border border-line bg-white px-3 py-2 text-xs font-semibold text-body";

  return (
    <AppShell sidebar>
      <Container>
        <PageTitle>History</PageTitle>

        <div className="mb-5 flex flex-wrap items-center gap-3">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="🔍  search documents…"
            className="w-72 rounded-lg border border-line bg-white px-3 py-2 text-sm text-body placeholder:text-mut"
          />
          <div className="flex-1" />
          <select className={select} value={domain} onChange={(e) => setDomain(e.target.value as "" | Domain)}>
            <option value="">All domains</option>
            <option value="KA">KA — Arbitration</option>
            <option value="KCL">KCL — Competition</option>
          </select>
          <select className={select} value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>
            <option value="essay">Essay</option>
            <option value="commentary">Commentary</option>
            <option value="legislation">Legislation</option>
            <option value="caselaw">Caselaw</option>
            <option value="booktoc">Booktoc</option>
          </select>
          <select className={select} value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            <option value="newest">Sort: Newest</option>
            <option value="oldest">Sort: Oldest</option>
            <option value="name">Sort: Name</option>
          </select>
        </div>

        <Card className="overflow-hidden">
          <div className="flex items-center px-5 py-3 text-[11px] font-bold text-mut">
            <span className="flex-1">DOCUMENT</span>
            <span className="w-24">DOMAIN</span>
            <span className="w-80">TOP TOPIC</span>
            <span className="w-20">LEVELS</span>
            <span className="w-28 text-right">PROCESSED</span>
            <span className="w-10" />
          </div>

          {isLoading && <div className="border-t border-hair px-5 py-6 text-sm text-mut">Loading…</div>}
          {!isLoading && isError && (
            <div className="border-t border-hair px-5 py-6 text-sm text-[#9B2B2B]">
              Couldn't load documents{apiBase ? ` from ${apiBase}` : ""}: {(error as Error).message}.
              {apiBase && <> Is the backend running (<code className="rounded bg-panel px-1">uvicorn api.main:app --reload</code>)?</>}
            </div>
          )}
          {!isLoading && !isError && items.length === 0 && (
            <div className="border-t border-hair px-5 py-8 text-center text-sm text-mut">
              {hasFilters ? (
                "No documents match your filters."
              ) : (
                <>
                  No documents processed yet.{" "}
                  <button className="font-semibold text-ink underline" onClick={() => navigate("/")}>
                    Upload and enrich files
                  </button>{" "}
                  — completed documents appear here.
                </>
              )}
            </div>
          )}

          {groups.map((g) => (
            <div key={g.date}>
              <div className="border-t border-hair bg-[#F4F6F8] px-5 py-2.5 text-[11px] font-bold text-mut">
                {g.date.toUpperCase()} · {g.rows.length} DOCUMENT{g.rows.length === 1 ? "" : "S"}
              </div>
              {g.rows.map((d) => (
                <div
                  key={d.document_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/documents/${d.document_id}`)}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/documents/${d.document_id}`)}
                  className="flex w-full cursor-pointer items-center border-t border-hair px-5 py-3.5 text-left hover:bg-panel"
                >
                  <span className="flex-1 truncate text-sm font-semibold text-ink">{d.filename}</span>
                  <span className="w-24"><DomainChip domain={d.domain} /></span>
                  <span className="w-80 truncate text-[13px] text-body">{d.top_topic}</span>
                  <span className="w-20 text-[13px] text-body">{d.levels}</span>
                  <span className="w-28 text-right text-[13px] text-mut">{formatTime(d.processed_at)}</span>
                  <span className="w-10 text-right">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(d);
                      }}
                      aria-label={`Delete ${d.filename}`}
                      className="px-1 text-mut hover:text-[#9B2B2B]"
                    >
                      🗑
                    </button>
                  </span>
                </div>
              ))}
            </div>
          ))}
        </Card>

        <p className="mt-4 text-xs text-mut">Click any row to open its taxonomy →</p>
      </Container>
    </AppShell>
  );
}
