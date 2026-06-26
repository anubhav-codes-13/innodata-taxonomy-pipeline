import type { ApiClient } from "./api";
import type {
  Batch,
  BatchFileState,
  BatchListItem,
  BatchResults,
  BeforeAfter,
  DocumentDetail,
  DocumentListParams,
  DocumentListResponse,
  Domain,
  EnrichedChunk,
  FileStatus,
  KeywordStat,
  KeywordStatsParams,
  UploadedFile,
} from "./types";

// Talks to the FastAPI backend for the implemented endpoints (file upload +
// confirm). Batch / document / history endpoints don't exist server-side yet,
// so those delegate to `sim` (the in-memory mock) seeded with the REAL uploaded
// files — the demo flow continues end-to-end past upload until the backend
// gains those routes. Swap each delegated method for a real fetch as the
// backend implements it; nothing in the screens changes.

interface BackendFile {
  id: string;
  filename: string;
  size: number;
  format: "xml" | "pdf" | "docx";
  domain: Domain | null;
  needs_domain: boolean;
  status: string;
  text_preview: string | null;
  domain_source: string | null;
  created_at: string;
  chunk_count?: number | null;
  error?: string | null;
}

interface SummaryDTO {
  document_id: string;
  filename: string;
  domain: Domain;
  doc_type: string;
  top_topic: string;
  levels: string;
  processed_at: string;
  chunk_count: number | null;
}

function mapFile(r: BackendFile): UploadedFile {
  return {
    id: r.id,
    filename: r.filename,
    size: r.size,
    format: r.format,
    domain: r.domain ?? null,
    needs_domain: r.needs_domain,
    status: r.status as FileStatus, // real backend status — NOT hardcoded
    text_preview: r.text_preview ?? undefined,
  };
}

async function req(url: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body?.error?.message ?? body?.detail ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message);
  }
  return res;
}

export class HttpApiClient implements ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly sim: ApiClient & { importPending?: (f: UploadedFile[]) => void },
  ) {}

  // Files belonging to each created batch, so subscribeBatch can render their
  // rows while the backend streams real status transitions over SSE.
  private readonly batchFiles = new Map<string, UploadedFile[]>();

  private url(path: string) {
    return `${this.baseUrl}${path}`;
  }

  // ---- real backend (file endpoints) ----

  async uploadFiles(files: File[]): Promise<UploadedFile[]> {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    const res = await req(this.url("/api/files"), { method: "POST", body: fd });
    return ((await res.json()) as BackendFile[]).map(mapFile);
  }

  async listPendingFiles(): Promise<UploadedFile[]> {
    const res = await req(this.url("/api/files"));
    return ((await res.json()) as BackendFile[]).map(mapFile).filter((f) => f.status === "pending");
  }

  async setFileDomain(fileId: string, domain: Domain): Promise<UploadedFile> {
    const res = await req(this.url(`/api/files/${fileId}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain }),
    });
    return mapFile((await res.json()) as BackendFile);
  }

  async removeFile(fileId: string): Promise<void> {
    await req(this.url(`/api/files/${fileId}`), { method: "DELETE" });
  }

  // ---- delegated to the simulator (backend routes pending) ----

  async createBatch(fileIds: string[]): Promise<{ batch_id: string }> {
    // Seed the simulator with the real uploaded files so the downstream
    // Results / Document / History screens keep working (those backend routes
    // don't exist yet). The live Processing stream below is the REAL backend.
    const files = await this.listPendingFiles();
    this.sim.importPending?.(files);
    const created = await this.sim.createBatch(fileIds);

    // Remember this batch's files for subscribeBatch's row rendering.
    this.batchFiles.set(created.batch_id, files.filter((f) => fileIds.includes(f.id)));

    // Kick off the REAL parse -> chunk pipeline on the backend. Progress is
    // observed via the SSE stream opened in subscribeBatch.
    await req(this.url("/api/process"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_ids: fileIds }),
    });

    return created;
  }

  getBatch(batchId: string): Promise<Batch> {
    return this.sim.getBatch(batchId);
  }

  /** Live batch progress: SSE (`GET /api/events`) for instant updates, with a
   * `GET /api/files` polling fallback so statuses still advance if the
   * EventSource never connects, drops, or is buffered. Whichever sees a change
   * first wins; both feed the same per-file state. */
  subscribeBatch(batchId: string, onUpdate: (b: Batch) => void): () => void {
    const files = this.batchFiles.get(batchId) ?? [];
    const states = new Map<string, BatchFileState>(
      files.map((f) => [
        f.id,
        { id: f.id, filename: f.filename, format: f.format, domain: f.domain, status: "queued", phase: null, progress: 0 },
      ]),
    );
    const FINAL: FileStatus[] = ["done", "failed"];

    const emit = () => {
      const arr = [...states.values()];
      const total = arr.length;
      const finished = arr.filter((f) => FINAL.includes(f.status)).length;
      const complete = total > 0 && finished === total;
      onUpdate({
        id: batchId,
        status: complete ? (arr.some((f) => f.status === "failed") ? "partial_failure" : "complete") : "processing",
        created_at: new Date().toISOString(),
        overall_progress: total ? finished / total : 0,
        eta_seconds: 0,
        files: arr,
      });
    };

    // Apply one status update; returns true if it actually changed something.
    const apply = (id: string, status: FileStatus, chunkCount?: number | null, error?: string | null): boolean => {
      const f = states.get(id);
      if (!f || f.status === status) return false;
      f.status = status;
      f.progress = FINAL.includes(status) ? 1 : 0.5;
      if (chunkCount != null) f.chunk_count = chunkCount;
      if (status === "failed") f.error = error ?? "Failed";
      return true;
    };

    const allFinal = () => {
      const arr = [...states.values()];
      return arr.length > 0 && arr.every((f) => FINAL.includes(f.status));
    };

    emit(); // initial render

    // --- SSE: instant updates ---
    const es = new EventSource(this.url("/api/events"));
    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data) as { id: string; status: FileStatus; chunk_count?: number | null; error?: string | null };
        if (apply(ev.id, ev.status, ev.chunk_count, ev.error)) emit();
      } catch {
        /* keepalive / malformed frame */
      }
    };
    es.onerror = () => {
      /* EventSource auto-reconnects; the poll below covers any gap. */
    };

    // --- Poll fallback: reliable even if SSE is blocked/buffered/dropped ---
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (stopped) return;
      try {
        const all = await this.listAllFiles();
        let changed = false;
        for (const r of all) {
          if (apply(r.id, r.status as FileStatus, r.chunk_count, r.error)) changed = true;
        }
        if (changed) emit();
      } catch {
        /* transient; try again next tick */
      }
      if (!stopped && !allFinal()) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, 1200);

    return () => {
      stopped = true;
      es.close();
      clearTimeout(timer);
    };
  }
  private async fetchSummaries(): Promise<SummaryDTO[]> {
    const res = await req(this.url("/api/documents"));
    return (await res.json()) as SummaryDTO[];
  }

  private async listAllFiles(): Promise<BackendFile[]> {
    const res = await req(this.url("/api/files"));
    return (await res.json()) as BackendFile[];
  }

  /** Real: aggregate the batch's processed documents from GET /api/documents. */
  async getBatchResults(batchId: string): Promise<BatchResults> {
    const [summaries, files] = await Promise.all([this.fetchSummaries(), this.listAllFiles()]);
    const batchIds = (this.batchFiles.get(batchId) ?? []).map((f) => f.id);
    const inBatch = (id: string) => batchIds.length === 0 || batchIds.includes(id);

    const docs = summaries.filter((s) => inBatch(s.document_id));
    const documents = docs.map((s) => ({
      document_id: s.document_id,
      filename: s.filename,
      domain: s.domain,
      top_topic: s.top_topic,
      levels: s.levels,
      status: "done" as const,
    }));
    const chunks = docs.reduce((sum, s) => sum + (s.chunk_count ?? 0), 0);
    const failed = files.filter((f) => inBatch(f.id) && f.status === "failed").length;

    return { summary: { enriched: documents.length, chunks, coverage_pct: 100, failed }, documents };
  }

  /** Real: full L1–L4 taxonomy (tree composed server-side from enriched chunks). */
  async getDocument(documentId: string): Promise<DocumentDetail> {
    const res = await req(this.url(`/api/files/${documentId}/document`));
    return (await res.json()) as DocumentDetail;
  }

  /** Real: the enriched source chunks behind a document (passages + L1–L4). */
  async getEnrichedChunks(documentId: string): Promise<EnrichedChunk[]> {
    const res = await req(this.url(`/api/files/${documentId}/enriched-chunks`));
    return (await res.json()) as EnrichedChunk[];
  }

  /** Before/After: AFTER comes from the real document (the screen derives it
   *  from the doc); BEFORE (editorial XML tags) isn't persisted yet, so it's
   *  empty for now — a small follow-up is to surface parsed enrichment. */
  async getBeforeAfter(_documentId: string): Promise<BeforeAfter> {
    return {
      before: { topics: [], keywords: [], cases: [], statutes: [], organizations: [] },
      uplift: { levels_before: 0, levels_after: 4 },
    };
  }

  /** Real: ordered document (= file) ids for this batch's pager. */
  async getBatchDocumentIds(batchId: string): Promise<string[]> {
    const summaries = await this.fetchSummaries();
    const done = new Set(summaries.map((s) => s.document_id));
    const batchIds = (this.batchFiles.get(batchId) ?? []).map((f) => f.id);
    return batchIds.length ? batchIds.filter((id) => done.has(id)) : summaries.map((s) => s.document_id);
  }

  /** Real: History list from GET /api/documents, filtered/sorted client-side. */
  async listDocuments(params: DocumentListParams): Promise<DocumentListResponse> {
    const summaries = await this.fetchSummaries();
    let items = summaries.map((s) => ({
      document_id: s.document_id,
      filename: s.filename,
      domain: s.domain,
      doc_type: s.doc_type,
      top_topic: s.top_topic,
      levels: s.levels,
      processed_at: s.processed_at,
      batch_id: "",
    }));
    if (params.search) {
      const q = params.search.toLowerCase();
      items = items.filter((d) => d.filename.toLowerCase().includes(q) || d.top_topic.toLowerCase().includes(q));
    }
    if (params.domain) items = items.filter((d) => d.domain === params.domain);
    if (params.type) items = items.filter((d) => d.doc_type === params.type);
    const sort = params.sort ?? "newest";
    items.sort((a, b) =>
      sort === "name"
        ? a.filename.localeCompare(b.filename)
        : sort === "oldest"
          ? a.processed_at.localeCompare(b.processed_at)
          : b.processed_at.localeCompare(a.processed_at),
    );
    const page = params.page ?? 1;
    const size = params.page_size ?? 20;
    const total = items.length;
    const start = (page - 1) * size;
    return { total, page, items: items.slice(start, start + size) };
  }

  listBatches(): Promise<BatchListItem[]> {
    return this.sim.listBatches();
  }

  /** Real: frequency stats for the dashboard — keywords (L4) or topic labels (L1/L2/L3). */
  async getKeywordStats(params: KeywordStatsParams): Promise<KeywordStat[]> {
    const q = new URLSearchParams();
    if (params.domain) q.set("domain", params.domain);
    if (params.search) q.set("search", params.search);
    if (params.limit) q.set("limit", String(params.limit));
    const level = params.level ?? "L4";
    if (level === "L4" || !params.level) {
      const res = await req(this.url(`/api/keywords?${q.toString()}`));
      return (await res.json()) as KeywordStat[];
    }
    q.set("level", level);
    const res = await req(this.url(`/api/topic-stats?${q.toString()}`));
    return (await res.json()) as KeywordStat[];
  }
}
