import type { ApiClient } from "./api";
import type {
  Batch,
  BatchFileState,
  BatchListItem,
  BatchResults,
  BeforeAfter,
  DocumentDetail,
  DocumentListItem,
  DocumentListParams,
  DocumentListResponse,
  Domain,
  FileFormat,
  UploadedFile,
} from "./types";
import type { EnrichedChunk, KeywordStat, KeywordStatsParams } from "./types";
import {
  buildBeforeAfter,
  buildDocument,
  buildEnrichedChunks,
  buildKeywordStats,
  buildTopicStats,
  SEED_DOCUMENTS,
  topTopicFor,
} from "../mocks/seed";

const PREVIEW =
  "…the arbitral tribunal held that an issue conflict arose where the arbitrator had previously decided the same question between the parties…";

let seq = 0;
const id = (p: string) => `${p}-${Date.now().toString(36)}-${(seq++).toString(36)}`;
const delay = (ms = 220) => new Promise((r) => setTimeout(r, ms));

function inferFormat(name: string): FileFormat {
  const ext = name.split(".").pop()?.toLowerCase();
  if (ext === "pdf") return "pdf";
  if (ext === "doc" || ext === "docx") return "docx";
  return "xml";
}
function inferXmlDomain(name: string): Domain {
  return name.toUpperCase().includes("KCL") ? "KCL" : "KA";
}

function phasesFor(format: FileFormat): string[] {
  const core = ["parsing", "chunking", "enriching", "synthesizing"];
  return format === "xml" ? core : ["extracting", ...core];
}

interface JobFile {
  state: BatchFileState;
  phases: string[];
  phaseIndex: number; // -1 = queued
  phaseProgress: number; // 0..1 within current phase
}

interface Job {
  batch: Batch;
  files: JobFile[];
  timer: ReturnType<typeof setInterval> | null;
  subscribers: Set<(b: Batch) => void>;
}

const TICK_MS = 600;
const CONCURRENCY = 2;

class MockApi implements ApiClient {
  private pending = new Map<string, UploadedFile>();
  private jobs = new Map<string, Job>();
  private documents = new Map<string, DocumentDetail>();
  private history: DocumentListItem[] = [...SEED_DOCUMENTS];
  private batchList: BatchListItem[] = [
    { id: "batch-seed-a", created_at: "2026-06-13T10:20:00Z", file_count: 2, status: "complete", label: "Jun 13, 2026 · batch of 2" },
    { id: "batch-seed-b", created_at: "2026-06-11T14:02:00Z", file_count: 1, status: "complete", label: "Jun 11, 2026 · batch of 1" },
  ];

  // ---- upload + confirm ----
  /** Seed the in-memory pending pool from externally-uploaded files (used by
   *  HttpApiClient so the simulated enrichment can run on real uploads). */
  importPending(files: UploadedFile[]): void {
    for (const f of files) this.pending.set(f.id, { ...f });
  }

  async uploadFiles(files: File[]): Promise<UploadedFile[]> {
    await delay();
    const created = files.map(({ name, size }) => {
      const format = inferFormat(name);
      const isXml = format === "xml";
      const f: UploadedFile = {
        id: id("file"),
        filename: name,
        size,
        format,
        domain: isXml ? inferXmlDomain(name) : null,
        needs_domain: !isXml,
        status: "pending",
        text_preview: isXml ? undefined : PREVIEW,
      };
      this.pending.set(f.id, f);
      return f;
    });
    return created;
  }

  async listPendingFiles(): Promise<UploadedFile[]> {
    await delay(80);
    return [...this.pending.values()];
  }

  async setFileDomain(fileId: string, domain: Domain): Promise<UploadedFile> {
    await delay(80);
    const f = this.pending.get(fileId);
    if (!f) throw new Error("file not found");
    f.domain = domain;
    f.needs_domain = false;
    return { ...f };
  }

  async removeFile(fileId: string): Promise<void> {
    await delay(80);
    this.pending.delete(fileId);
  }

  // ---- batch lifecycle ----
  async createBatch(fileIds: string[]): Promise<{ batch_id: string }> {
    await delay();
    const picked = fileIds.map((fid) => this.pending.get(fid)).filter(Boolean) as UploadedFile[];
    if (picked.some((f) => f.needs_domain || !f.domain)) {
      throw new Error("Every PDF/DOC file must have a domain before enrichment.");
    }
    const batchId = id("batch");
    const jobFiles: JobFile[] = picked.map((f) => ({
      state: {
        id: f.id,
        filename: f.filename,
        format: f.format,
        domain: f.domain,
        status: "queued",
        phase: null,
        progress: 0,
      },
      phases: phasesFor(f.format),
      phaseIndex: -1,
      phaseProgress: 0,
    }));
    const batch: Batch = {
      id: batchId,
      status: "processing",
      created_at: new Date().toISOString(),
      overall_progress: 0,
      eta_seconds: jobFiles.length * 4,
      files: jobFiles.map((j) => ({ ...j.state })),
    };
    const job: Job = { batch, files: jobFiles, timer: null, subscribers: new Set() };
    this.jobs.set(batchId, job);
    // remove from pending pool (now owned by the batch)
    picked.forEach((f) => this.pending.delete(f.id));
    this.startJob(job);
    return { batch_id: batchId };
  }

  private startJob(job: Job) {
    job.timer = setInterval(() => this.tick(job), TICK_MS);
  }

  private tick(job: Job) {
    const active = job.files.filter(
      (j) => j.phaseIndex >= 0 && j.state.status !== "done" && j.state.status !== "failed",
    );
    // promote queued files up to the concurrency limit
    let slots = CONCURRENCY - active.length;
    for (const j of job.files) {
      if (slots <= 0) break;
      if (j.phaseIndex === -1) {
        j.phaseIndex = 0;
        j.phaseProgress = 0;
        j.state.status = j.phases[0] as BatchFileState["status"];
        j.state.phase = j.phases[0];
        slots--;
      }
    }
    // advance in-progress files
    for (const j of job.files) {
      if (j.phaseIndex < 0 || j.state.status === "done" || j.state.status === "failed") continue;
      j.phaseProgress += 0.5;
      if (j.phaseProgress >= 1) {
        j.phaseIndex++;
        j.phaseProgress = 0;
        if (j.phaseIndex >= j.phases.length) {
          this.completeFile(job, j);
        } else {
          j.state.status = j.phases[j.phaseIndex] as BatchFileState["status"];
          j.state.phase = j.phases[j.phaseIndex];
        }
      }
      j.state.progress = j.phaseProgress;
    }
    this.recompute(job);
    this.emit(job);
    if (job.batch.status === "complete" || job.batch.status === "partial_failure") {
      if (job.timer) clearInterval(job.timer);
      job.timer = null;
    }
  }

  private completeFile(job: Job, j: JobFile) {
    const domain = (j.state.domain ?? "KA") as Domain;
    const docId = id("doc");
    const doc = buildDocument(docId, j.state.filename, domain);
    this.documents.set(docId, doc);
    j.state.status = "done";
    j.state.phase = "done";
    j.state.progress = 1;
    j.state.document_id = docId;
    j.state.top_topic = topTopicFor(domain);
    this.history.unshift({
      document_id: docId,
      filename: j.state.filename,
      domain,
      doc_type: doc.doc_type,
      top_topic: j.state.top_topic,
      levels: "L1-L4",
      processed_at: new Date().toISOString(),
      batch_id: job.batch.id,
    });
  }

  private recompute(job: Job) {
    const fractions = job.files.map((j) => {
      if (j.state.status === "done") return 1;
      if (j.phaseIndex < 0) return 0;
      return (j.phaseIndex + j.phaseProgress) / j.phases.length;
    });
    const overall = fractions.reduce((a, b) => a + b, 0) / job.files.length;
    job.batch.overall_progress = overall;
    job.batch.eta_seconds = Math.max(0, Math.round((1 - overall) * job.files.length * 4));
    job.batch.files = job.files.map((j) => ({ ...j.state }));
    const allDone = job.files.every((j) => j.state.status === "done" || j.state.status === "failed");
    if (allDone) {
      const failed = job.files.some((j) => j.state.status === "failed");
      job.batch.status = failed ? "partial_failure" : "complete";
      job.batch.overall_progress = 1;
      job.batch.eta_seconds = 0;
      if (!this.batchList.find((b) => b.id === job.batch.id)) {
        const n = job.files.length;
        this.batchList.unshift({
          id: job.batch.id,
          created_at: job.batch.created_at,
          file_count: n,
          status: job.batch.status,
          label: `${fmtDate(job.batch.created_at)} · batch of ${n}`,
        });
      }
    }
  }

  private emit(job: Job) {
    const snapshot: Batch = { ...job.batch, files: job.batch.files.map((f) => ({ ...f })) };
    job.subscribers.forEach((cb) => cb(snapshot));
  }

  async getBatch(batchId: string): Promise<Batch> {
    await delay(80);
    const job = this.jobs.get(batchId);
    if (!job) throw new Error("batch not found");
    return { ...job.batch, files: job.batch.files.map((f) => ({ ...f })) };
  }

  subscribeBatch(batchId: string, onUpdate: (b: Batch) => void): () => void {
    const job = this.jobs.get(batchId);
    if (!job) return () => {};
    job.subscribers.add(onUpdate);
    // immediate snapshot
    onUpdate({ ...job.batch, files: job.batch.files.map((f) => ({ ...f })) });
    return () => job.subscribers.delete(onUpdate);
  }

  async getBatchResults(batchId: string): Promise<BatchResults> {
    await delay();
    const job = this.jobs.get(batchId);
    if (!job) throw new Error("batch not found");
    const documents = job.batch.files
      .filter((f) => f.status === "done" && f.document_id)
      .map((f) => ({
        document_id: f.document_id!,
        filename: f.filename,
        domain: (f.domain ?? "KA") as Domain,
        top_topic: f.top_topic ?? "",
        levels: "L1-L4",
        status: f.status,
      }));
    const chunks = documents.reduce((sum, d) => sum + (this.documents.get(d.document_id)?.chunk_count ?? 0), 0);
    const failed = job.batch.files.filter((f) => f.status === "failed").length;
    return {
      summary: { enriched: documents.length, chunks, coverage_pct: 100, failed },
      documents,
    };
  }

  async getBatchDocumentIds(batchId: string): Promise<string[]> {
    await delay(60);
    const job = this.jobs.get(batchId);
    if (!job) return [];
    return job.batch.files.filter((f) => f.document_id).map((f) => f.document_id!);
  }

  // ---- documents ----
  async getDocument(documentId: string): Promise<DocumentDetail> {
    await delay();
    const doc = this.documents.get(documentId);
    if (doc) return doc;
    // history seed docs have no stored detail — synthesize one on demand
    const item = this.history.find((h) => h.document_id === documentId);
    const domain: Domain = item?.domain ?? "KA";
    const filename = item?.filename ?? "document.xml";
    const built = buildDocument(documentId, filename, domain);
    this.documents.set(documentId, built);
    return built;
  }

  async getBeforeAfter(documentId: string): Promise<BeforeAfter> {
    await delay();
    const doc = await this.getDocument(documentId);
    return buildBeforeAfter(doc.domain);
  }

  async getEnrichedChunks(documentId: string): Promise<EnrichedChunk[]> {
    await delay();
    const doc = await this.getDocument(documentId);
    return buildEnrichedChunks(doc.domain, doc.filename);
  }

  // ---- history ----
  async listDocuments(params: DocumentListParams): Promise<DocumentListResponse> {
    await delay(120);
    let items = [...this.history];
    if (params.search) {
      const q = params.search.toLowerCase();
      items = items.filter((d) => d.filename.toLowerCase().includes(q) || d.top_topic.toLowerCase().includes(q));
    }
    if (params.domain) items = items.filter((d) => d.domain === params.domain);
    if (params.type) items = items.filter((d) => d.doc_type === params.type);
    const sort = params.sort ?? "newest";
    items.sort((a, b) => {
      if (sort === "name") return a.filename.localeCompare(b.filename);
      const cmp = a.processed_at.localeCompare(b.processed_at);
      return sort === "oldest" ? cmp : -cmp;
    });
    const page = params.page ?? 1;
    const size = params.page_size ?? 20;
    const total = items.length;
    const start = (page - 1) * size;
    return { total, page, items: items.slice(start, start + size) };
  }

  async listBatches(): Promise<BatchListItem[]> {
    await delay(80);
    return [...this.batchList];
  }

  async getKeywordStats(params: KeywordStatsParams): Promise<KeywordStat[]> {
    await delay(120);
    const level = params.level ?? "L4";
    const out =
      level === "L4"
        ? buildKeywordStats(params.domain, params.search)
        : buildTopicStats(level, params.domain, params.search);
    return params.limit ? out.slice(0, params.limit) : out;
  }
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export const mockApi: ApiClient = new MockApi();
