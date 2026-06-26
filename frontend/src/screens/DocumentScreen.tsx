import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AppShell, Container } from "../components/AppShell";
import { Button, Card, Chip, DomainChip, LevelBadge } from "../components/ui";
import { useBatchDocumentIds, useDocument, useEnrichedChunks } from "../lib/hooks";
import { DOMAIN_LABEL, type DocumentDetail, type EnrichedChunk, type L4Kind, type TaxonomyNode } from "../lib/types";

const TABS = ["Overview", "Explorer", "Entities"] as const;
type Tab = (typeof TABS)[number];

const L4_STYLE: Record<L4Kind, { label: string; bg: string; fg: string }> = {
  cases: { label: "Cases", bg: "#E7EEF9", fg: "#2B5C9B" },
  statutes: { label: "Statutes", bg: "#FBEAD9", fg: "#9A5A1B" },
  organizations: { label: "Organizations", bg: "#E8E6F8", fg: "#3B2B9B" },
  keywords: { label: "Keywords", bg: "#E7F1EA", fg: "#2E7D52" },
};

const L4_PREVIEW_LIMIT = 12;

// A click on a topic (L1/L2/L3) or an entity/keyword (L4) selects it; the
// source panel then shows the chunks that produced it.
type Selection =
  | { kind: "L1" | "L2" | "L3"; label: string }
  | { kind: "L4"; value: string };

function isNodeSelected(sel: Selection | null, level: "L1" | "L2" | "L3", label?: string): boolean {
  return !!sel && sel.kind === level && sel.label === label;
}
function isValueSelected(sel: Selection | null, value: string): boolean {
  return !!sel && sel.kind === "L4" && sel.value === value;
}

function chunkMatches(c: EnrichedChunk, sel: Selection): boolean {
  if (sel.kind === "L1") return true;
  if (sel.kind === "L2") return c.L2_Topic === sel.label;
  if (sel.kind === "L3") return c.L3_Sub_Topic === sel.label;
  if (sel.kind === "L4") {
    const needle = sel.value.toLowerCase();
    const md = c.L4_metadata;
    const all = [
      ...(md?.entities?.case_names ?? []),
      ...(md?.entities?.statutes_and_regulations ?? []),
      ...(md?.entities?.organizations ?? []),
      ...(md?.keywords?.existing_matched_keywords ?? []),
      ...(md?.keywords?.new_extracted_keywords ?? []),
    ];
    return all.some((v) => v.toLowerCase() === needle);
  }
  return false;
}

// fused_text = "[Container … │ Document … │ Section: id - title]\n\n<body>"
function parsePassage(fused: string): { breadcrumb: string | null; body: string } {
  const i = fused.indexOf("]\n\n");
  if (fused.startsWith("[") && i !== -1) return { breadcrumb: fused.slice(1, i), body: fused.slice(i + 3) };
  return { breadcrumb: null, body: fused };
}
function sectionFromCrumb(crumb: string): string {
  const parts = crumb.split("│").map((s) => s.trim());
  return parts[parts.length - 1] || crumb;
}

function Highlight({ text, term }: { text: string; term?: string }): ReactNode {
  if (!term) return text;
  const lower = text.toLowerCase();
  const t = term.toLowerCase();
  const parts: ReactNode[] = [];
  let i = 0;
  for (let j = lower.indexOf(t, i); j !== -1; j = lower.indexOf(t, i)) {
    if (j > i) parts.push(text.slice(i, j));
    parts.push(
      <mark key={j} className="rounded bg-[#FCEFC7] px-0.5">
        {text.slice(j, j + term.length)}
      </mark>,
    );
    i = j + term.length;
  }
  parts.push(text.slice(i));
  return <>{parts}</>;
}

export function DocumentScreen() {
  const { documentId = "" } = useParams();
  const [params] = useSearchParams();
  const batchId = params.get("batch") ?? undefined;
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("Overview");

  const { data: doc, isLoading } = useDocument(documentId);
  const { data: batchDocIds } = useBatchDocumentIds(batchId);

  const idx = batchDocIds?.indexOf(documentId) ?? -1;
  const hasPager = !!batchDocIds && idx >= 0 && batchDocIds.length > 1;
  const goTo = (i: number) => navigate(`/documents/${batchDocIds![i]}?batch=${batchId}`);

  const pager = hasPager ? (
    <div className="flex items-center gap-3 rounded-lg bg-[#3B414D] px-3 py-2 text-white">
      <button disabled={idx <= 0} onClick={() => goTo(idx - 1)} className="disabled:opacity-30">◀</button>
      <span className="text-xs font-semibold">File {idx + 1} of {batchDocIds!.length}</span>
      <button disabled={idx >= batchDocIds!.length - 1} onClick={() => goTo(idx + 1)} className="disabled:opacity-30">▶</button>
    </div>
  ) : undefined;

  const exportJson = () => {
    if (!doc) return;
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${doc.filename}.taxonomy.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <AppShell rightSlot={pager}>
      {/* subheader */}
      <div className="border-b border-line bg-white px-10 pt-5">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-ink">{doc?.filename ?? "Loading…"}</h1>
          {doc && <DomainChip domain={doc.domain} full />}
          <div className="flex-1" />
          <Button variant="secondary" onClick={exportJson} disabled={!doc}>⬇ Export JSON</Button>
        </div>
        <div className="mt-4 flex gap-7">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`relative pb-2.5 text-sm ${tab === t ? "font-semibold text-ink" : "text-mut hover:text-body"}`}
            >
              {t}
              {tab === t && <span className="absolute inset-x-0 -bottom-px h-0.5 bg-ink" />}
            </button>
          ))}
        </div>
      </div>

      <div className="w-full px-8 py-6">
        {isLoading || !doc ? (
          <p className="text-sm text-mut">Loading taxonomy…</p>
        ) : (
          <>
            {tab === "Explorer" && <ExplorerTab doc={doc} documentId={documentId} />}
            {tab === "Entities" && <EntitiesTab doc={doc} />}
            {tab === "Overview" && <OverviewTab doc={doc} />}
          </>
        )}
      </div>
    </AppShell>
  );
}

// ---- Explorer ----

function ProvenancePill({ node }: { node: TaxonomyNode }) {
  if (node.level !== "L2" || !node.source) return null;
  if (node.source === "anchor")
    return <Chip bg="#DCEFE3" fg="#2E7D52">● anchored{node.similarity ? ` · ${node.similarity}` : ""}</Chip>;
  return <Chip bg="#FBE9D8" fg="#B5651D">⚡ expanded</Chip>;
}

function TreeNode({
  node,
  depth,
  selection,
  onSelect,
}: {
  node: TaxonomyNode;
  depth: number;
  selection: Selection | null;
  onSelect: (s: Selection) => void;
}) {
  const [open, setOpen] = useState(true);
  const indent = 8 + depth * 28;

  if (node.level === "L4") {
    return <L4Leaf node={node} indent={indent} selection={selection} onSelect={onSelect} />;
  }

  const hasChildren = !!node.children && node.children.length > 0;
  const isL1 = node.level === "L1";
  const caret = hasChildren ? (open ? "▾" : "▸") : "•";
  const level = node.level as "L1" | "L2" | "L3";
  const selected = isNodeSelected(selection, level, node.label);

  return (
    <>
      <div className="flex items-center gap-1.5 py-1.5" style={{ paddingLeft: indent }}>
        {/* caret = expand/collapse */}
        <button
          type="button"
          onClick={() => hasChildren && setOpen((o) => !o)}
          aria-expanded={hasChildren ? open : undefined}
          className={`w-3 shrink-0 text-xs text-mut ${hasChildren ? "cursor-pointer hover:opacity-70" : "cursor-default"}`}
        >
          {caret}
        </button>
        {/* label = select → show source passages */}
        <button
          type="button"
          onClick={() => node.label && onSelect({ kind: level, label: node.label })}
          title="Show source passages"
          className={`rounded px-1.5 py-0.5 text-left transition ${selected ? "bg-[#E7EEF9] ring-1 ring-[#B9CBEA]" : "hover:bg-panel"}`}
        >
          <span className={`${isL1 ? "text-[15px]" : "text-sm"} ${node.level === "L3" ? "text-body" : "font-semibold text-ink"}`}>
            {node.label}
          </span>
        </button>
        <div className="flex-1" />
        <ProvenancePill node={node} />
        <LevelBadge level={node.level} />
      </div>
      {hasChildren && open &&
        node.children!.map((child, i) => (
          <TreeNode key={i} node={child} depth={depth + 1} selection={selection} onSelect={onSelect} />
        ))}
    </>
  );
}

function L4Leaf({
  node,
  indent,
  selection,
  onSelect,
}: {
  node: TaxonomyNode;
  indent: number;
  selection: Selection | null;
  onSelect: (s: Selection) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const style = L4_STYLE[node.kind!];
  const values = node.values ?? [];
  const shown = expanded ? values : values.slice(0, L4_PREVIEW_LIMIT);
  const hidden = values.length - shown.length;

  return (
    <div className="py-1.5" style={{ paddingLeft: indent }}>
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-[11px] font-bold uppercase tracking-wide" style={{ color: style.fg }}>
          {style.label}
        </span>
        <span className="rounded-full bg-[#EDF0F2] px-1.5 py-0.5 text-[10px] font-semibold text-mut">
          {values.length}
        </span>
        <div className="flex-1" />
        <LevelBadge level="L4" />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {shown.map((v, i) => {
          const sel = isValueSelected(selection, v);
          return (
            <button
              key={i}
              onClick={() => onSelect({ kind: "L4", value: v })}
              title="Show source passages"
              className={`rounded-md px-2 py-0.5 text-[12px] leading-5 transition hover:brightness-95 ${sel ? "ring-2 ring-bar ring-offset-1" : ""}`}
              style={{ backgroundColor: style.bg, color: style.fg }}
            >
              {v}
            </button>
          );
        })}
        {hidden > 0 && (
          <button
            onClick={() => setExpanded(true)}
            className="rounded-md border border-line px-2 py-0.5 text-[12px] font-semibold leading-5 text-body hover:bg-panel"
          >
            +{hidden} more
          </button>
        )}
        {expanded && values.length > L4_PREVIEW_LIMIT && (
          <button
            onClick={() => setExpanded(false)}
            className="rounded-md border border-line px-2 py-0.5 text-[12px] font-semibold leading-5 text-body hover:bg-panel"
          >
            Show less
          </button>
        )}
      </div>
    </div>
  );
}

// Prune the tree to nodes matching `q`. A topic (L1/L2/L3) whose label matches
// keeps its whole subtree; otherwise it's kept only if a descendant matches.
// An L4 leaf keeps the values that match (or all of them if its kind label,
// e.g. "Cases", matches the query).
function matchNode(node: TaxonomyNode, q: string): TaxonomyNode | null {
  if (node.level === "L4") {
    if (L4_STYLE[node.kind!].label.toLowerCase().includes(q)) return node;
    const vals = (node.values ?? []).filter((v) => v.toLowerCase().includes(q));
    return vals.length ? { ...node, values: vals } : null;
  }
  if ((node.label ?? "").toLowerCase().includes(q)) return node;
  const children = (node.children ?? [])
    .map((c) => matchNode(c, q))
    .filter((c): c is TaxonomyNode => c !== null);
  return children.length ? { ...node, children } : null;
}

function filterTree(nodes: TaxonomyNode[], query: string): TaxonomyNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return nodes;
  return nodes.map((n) => matchNode(n, q)).filter((n): n is TaxonomyNode => n !== null);
}

// Walk the full tree looking for an exact case-insensitive match on any
// L4 value or L1/L2/L3 label. Returns the first match as a Selection.
function findExactMatch(nodes: TaxonomyNode[], q: string): Selection | null {
  for (const node of nodes) {
    if (node.level === "L4") {
      const hit = (node.values ?? []).find((v) => v.toLowerCase() === q);
      if (hit) return { kind: "L4", value: hit };
    } else {
      if ((node.label ?? "").toLowerCase() === q)
        return { kind: node.level as "L1" | "L2" | "L3", label: node.label! };
      const found = findExactMatch(node.children ?? [], q);
      if (found) return found;
    }
  }
  return null;
}

function ExplorerTab({ doc, documentId }: { doc: DocumentDetail; documentId: string }) {
  const [query, setQuery] = useState("");
  const [selection, setSelection] = useState<Selection | null>(null);
  const tree = filterTree(doc.taxonomy_tree, query);
  const { data: chunks = [], isLoading: chunksLoading } = useEnrichedChunks(documentId);

  // Auto-select when the search query exactly equals a keyword, entity, or topic
  useEffect(() => {
    const q = query.trim().toLowerCase();
    if (!q) return;
    const match = findExactMatch(doc.taxonomy_tree, q);
    if (match) setSelection(match);
  }, [query, doc.taxonomy_tree]);

  return (
    <div className="grid grid-cols-2 gap-6">
      <div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="search within this taxonomy..."
          className="mb-4 w-full rounded-lg border border-line bg-white px-4 py-2.5 text-[13px] text-body placeholder:text-mut focus:border-mut focus:outline-none"
        />
        <Card className="px-4 py-3">
          {tree.length ? (
            tree.map((node, i) => (
              <TreeNode key={`${query}-${i}`} node={node} depth={0} selection={selection} onSelect={setSelection} />
            ))
          ) : (
            <p className="px-1 py-6 text-center text-sm text-mut">No matches for "{query.trim()}".</p>
          )}
        </Card>
        <p className="mt-4 text-[11px] text-mut">
          ● anchored = matched a seed topic (no LLM) &nbsp;&nbsp; ⚡ expanded = LLM-generated new topic &nbsp;&nbsp; · click any topic or entity to see its source
        </p>
      </div>
      <div className="sticky top-6 self-start">
        <SourcePanel chunks={chunks} selection={selection} loading={chunksLoading} />
      </div>
    </div>
  );
}

function SourcePanel({
  chunks,
  selection,
  loading,
}: {
  chunks: EnrichedChunk[];
  selection: Selection | null;
  loading: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || loading) return;
    container.scrollTop = 0;
    // Double RAF: first tick lets React commit the new passages,
    // second tick reads accurate layout and scrolls to the first highlight.
    const af = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (!el) return;
        const mark = el.querySelector("mark");
        if (!mark) return;
        const offset = mark.getBoundingClientRect().top - el.getBoundingClientRect().top;
        el.scrollTop = Math.max(0, offset - 80);
      });
    });
    return () => cancelAnimationFrame(af);
  }, [selection, loading]);

  const term = selection?.kind === "L4" ? selection.value : undefined;
  const heading = selection ? (selection.kind === "L4" ? selection.value : selection.label) : null;
  const matches = selection ? chunks.filter((c) => chunkMatches(c, selection)) : [];

  return (
    <div className="flex flex-col rounded-xl border border-line bg-white">
      {/* sticky header */}
      <div className="shrink-0 border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-ink">Source passages</h3>
          {selection && (
            <span className="rounded-full bg-[#EDF0F2] px-2 py-0.5 text-[11px] font-semibold text-mut">{matches.length}</span>
          )}
        </div>
        {heading && (
          <p className="mt-0.5 truncate text-[12px] text-mut">
            for <span className="font-semibold text-body">{heading}</span>
          </p>
        )}
      </div>

      {/* scrollable body */}
      <div ref={scrollRef} className="overflow-y-auto p-4" style={{ maxHeight: "calc(100vh - 220px)" }}>
        {!selection && (
          <p className="py-8 text-center text-sm text-mut">
            Select a topic or entity on the left to see the source passages it came from.
          </p>
        )}
        {selection && loading && <p className="text-sm text-mut">Loading passages...</p>}
        {selection && !loading && matches.length === 0 && (
          <p className="text-sm text-mut">No source passage found for this selection.</p>
        )}
        <div className="space-y-3">
          {matches.map((c) => {
            const { breadcrumb, body } = parsePassage(c.fused_text);
            const verbatim = term ? body.toLowerCase().includes(term.toLowerCase()) : true;
            return (
              <Card key={c.chunk_id} className="px-4 py-3">
                {breadcrumb && (
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-mut">
                    {sectionFromCrumb(breadcrumb)}
                  </div>
                )}
                {!verbatim && (
                  <div className="mb-2 rounded bg-[#FFF8E6] px-2.5 py-1 text-[11px] text-[#8A6200]">
                    Entity identified by AI — not mentioned verbatim in this passage
                  </div>
                )}
                <p className="text-[13px] leading-relaxed text-body">
                  <Highlight text={body} term={term} />
                </p>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---- Entities ----

function extractL2Labels(tree: TaxonomyNode[]): string[] {
  const out: string[] = [];
  for (const l1 of tree) {
    for (const l2 of l1.children ?? []) {
      if (l2.level === "L2" && l2.label) out.push(l2.label);
    }
  }
  return out;
}

function extractL3Labels(tree: TaxonomyNode[]): string[] {
  const out: string[] = [];
  for (const l1 of tree) {
    for (const l2 of l1.children ?? []) {
      for (const l3 of l2.children ?? []) {
        if (l3.level === "L3" && l3.label) out.push(l3.label);
      }
    }
  }
  return out;
}

function TopicChips({ title, items, bg, fg, emptyText }: { title: string; items: string[]; bg: string; fg: string; emptyText: string }) {
  return (
    <div className="mb-6">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-bold text-ink">{title}</h3>
        <span className="rounded-full bg-[#EDF0F2] px-1.5 py-0.5 text-[10px] font-semibold text-mut">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <p className="text-[13px] text-mut">{emptyText}</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((v) => (
            <span
              key={v}
              className="rounded-md px-2.5 py-1 text-[12px] font-medium leading-5"
              style={{ backgroundColor: bg, color: fg }}
            >
              {v}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function EntityList({ title, items, emptyText = "None extracted." }: { title: string; items: string[]; emptyText?: string }) {
  return (
    <div className="mb-6">
      <h3 className="mb-2 text-sm font-bold text-ink">{title} ({items.length})</h3>
      {items.length === 0 ? (
        <p className="text-[13px] text-mut">{emptyText}</p>
      ) : (
        <ul className="space-y-1">
          {items.map((v) => (
            <li key={v} className="text-[13px] text-body">• {v}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EntitiesTab({ doc }: { doc: DocumentDetail }) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const f = (xs: string[]) => (q ? xs.filter((v) => v.toLowerCase().includes(q)) : xs);
  const emptyText = q ? "No matches." : "None extracted.";

  const l2Topics = f(extractL2Labels(doc.taxonomy_tree));
  const l3SubTopics = f(extractL3Labels(doc.taxonomy_tree));
  const matched = f(doc.keywords.matched_from_dictionary);
  const discovered = f(doc.keywords.newly_extracted);
  const noKeywords = matched.length + discovered.length === 0;

  return (
    <div className="max-w-4xl">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="search entities..."
        className="mb-5 w-full rounded-lg border border-line bg-white px-4 py-2.5 text-[13px] text-body placeholder:text-mut focus:border-mut focus:outline-none"
      />
      <TopicChips title="Topics (L2)" items={l2Topics} bg="#E7EEF9" fg="#2B5C9B" emptyText={emptyText} />
      <TopicChips title="Sub-topics (L3)" items={l3SubTopics} bg="#E8E6F8" fg="#3B2B9B" emptyText={emptyText} />
      <EntityList title="Cases" items={f(doc.entities.case_names)} emptyText={emptyText} />
      <EntityList title="Statutes" items={f(doc.entities.statutes_and_regulations)} emptyText={emptyText} />
      <EntityList title="Organizations" items={f(doc.entities.organizations)} emptyText={emptyText} />
      <div>
        <h3 className="mb-2 text-sm font-bold text-ink">Keywords ({matched.length + discovered.length})</h3>
        <div className="flex flex-wrap gap-2">
          {matched.map((k) => (
            <Chip key={k} bg="#E3E7EB" fg="#3A4250">▣ {k}</Chip>
          ))}
          {discovered.map((k) => (
            <span key={k} className="inline-flex items-center gap-1 rounded-full border border-line bg-white px-2.5 py-1 text-[11px] font-semibold text-body">
              ◇ {k}
            </span>
          ))}
          {noKeywords && <p className="text-[13px] text-mut">{emptyText}</p>}
        </div>
        <p className="mt-3 text-[11px] text-mut">▣ matched from dictionary &nbsp;&nbsp; ◇ newly discovered</p>
      </div>
    </div>
  );
}

// ---- Overview ----

function OverviewTab({ doc }: { doc: DocumentDetail }) {
  return (
    <div className="grid max-w-4xl grid-cols-1 gap-5 md:grid-cols-2">
      <Card className="px-5 py-5">
        <h3 className="mb-3 text-sm font-bold text-ink">Document</h3>
        <Row k="Type" v={doc.doc_type} />
        <Row k="Domain" v={DOMAIN_LABEL[doc.domain]} />
        <Row k="Container" v={doc.container_title ?? "—"} />
        <Row k="Year" v={String(doc.publ_year ?? "—")} />
        <Row k="Chunks" v={String(doc.chunk_count)} />
        <Row k="L2 provenance" v={doc.provenance.summary} />
      </Card>
      {doc.case_metadata && (
        <Card className="px-5 py-5">
          <h3 className="mb-3 text-sm font-bold text-ink">Case</h3>
          <Row k="Court" v={doc.case_metadata.court} />
          <Row k="Case" v={doc.case_metadata.case_name} />
          <Row k="Number" v={doc.case_metadata.case_number} />
          <Row k="Decision date" v={doc.case_metadata.decision_date} />
          <Row k="Parties" v={doc.case_metadata.parties.map((p) => `${p.role}: ${p.name}`).join(", ")} />
        </Card>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex border-b border-hair py-2 last:border-0">
      <span className="w-36 shrink-0 text-[13px] text-mut">{k}</span>
      <span className="text-[13px] text-body">{v}</span>
    </div>
  );
}
