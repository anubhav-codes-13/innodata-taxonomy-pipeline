// Domain types — mirror the API_REQUIREMENTS.md contract so the mock and the
// future FastAPI backend are interchangeable behind the ApiClient interface.

export type Domain = "KA" | "KCL";
export const DOMAIN_LABEL: Record<Domain, string> = {
  KA: "International Arbitration",
  KCL: "Competition Law",
};

export type FileFormat = "xml" | "pdf" | "docx";

export type FileStatus =
  | "pending" // selected, not yet enriching
  | "queued"
  | "extracting"
  | "parsing"
  | "chunking"
  | "routing" // Phase 3.1 — L1 domain + L2 topic
  | "enriching" // Phase 3.2/3.3 — L3 sub-topics + L4 entities/keywords
  | "synthesizing" // Phase 4 — roll up into L1–L4 taxonomy
  | "processing" // generic in-flight (backend back-compat)
  | "done"
  | "failed";

export interface UploadedFile {
  id: string;
  filename: string;
  size: number;
  format: FileFormat;
  domain: Domain | null;
  needs_domain: boolean;
  status: FileStatus;
  text_preview?: string;
}

export type BatchStatus = "draft" | "processing" | "complete" | "partial_failure";

export interface BatchFileState {
  id: string;
  filename: string;
  format: FileFormat;
  domain: Domain | null;
  status: FileStatus;
  phase: string | null;
  progress: number; // 0..1 for the active phase
  document_id?: string;
  top_topic?: string;
  chunk_count?: number; // populated on `done` (from the SSE event)
  error?: string;
}

export interface Batch {
  id: string;
  status: BatchStatus;
  created_at: string;
  overall_progress: number; // 0..1
  eta_seconds: number;
  files: BatchFileState[];
}

export interface BatchSummary {
  enriched: number;
  chunks: number;
  coverage_pct: number;
  failed: number;
}

export interface BatchResultRow {
  document_id: string;
  filename: string;
  domain: Domain;
  top_topic: string;
  levels: string; // e.g. "L1-L4"
  status: FileStatus;
}

export interface BatchResults {
  summary: BatchSummary;
  documents: BatchResultRow[];
}

// ---- Taxonomy ----

export type Level = "L1" | "L2" | "L3" | "L4";
export type L4Kind = "cases" | "statutes" | "organizations" | "keywords";

export interface TaxonomyNode {
  level: Level;
  label?: string; // for L1/L2/L3
  source?: "anchor" | "generator"; // L2 provenance
  similarity?: number; // L2 cosine
  kind?: L4Kind; // for L4 leaves
  values?: string[]; // for L4 leaves
  children?: TaxonomyNode[];
}

export interface CaseMetadata {
  court: string;
  case_name: string;
  case_number: string;
  decision_date: string;
  parties: { role: string; name: string }[];
}

export interface Provenance {
  summary: string;
  anchored_pct: number;
  expanded_pct: number;
}

export interface DocumentDetail {
  doc_id: string;
  filename: string;
  doc_type: string;
  domain: Domain;
  container_title?: string;
  publ_year?: number;
  chunk_count: number;
  case_metadata?: CaseMetadata | null;
  provenance: Provenance;
  taxonomy_tree: TaxonomyNode[];
  entities: {
    case_names: string[];
    statutes_and_regulations: string[];
    organizations: string[];
  };
  keywords: {
    all: string[];
    matched_from_dictionary: string[];
    newly_extracted: string[];
  };
}

export interface BeforeAfter {
  before: {
    topics: string[];
    keywords: string[];
    cases: string[];
    statutes: string[];
    organizations: string[];
  };
  uplift: { levels_before: number; levels_after: number };
}

// ---- Enriched chunks (source passages behind the taxonomy) ----

export interface EnrichedChunk {
  chunk_id: string;
  section_id?: string | null;
  fused_text: string;
  L1_Domain?: string | null;
  L2_Topic?: string | null;
  L2_Source?: string | null;
  L2_Similarity?: number | null;
  L3_Sub_Topic?: string | null;
  L4_metadata?: {
    entities?: {
      case_names?: string[];
      statutes_and_regulations?: string[];
      organizations?: string[];
    };
    keywords?: {
      existing_matched_keywords?: string[];
      new_extracted_keywords?: string[];
    };
  };
}

// ---- History / list ----

export interface DocumentListItem {
  document_id: string;
  filename: string;
  domain: Domain;
  doc_type: string;
  top_topic: string;
  levels: string;
  processed_at: string; // ISO
  batch_id: string;
}

export interface DocumentListParams {
  search?: string;
  domain?: Domain;
  type?: string;
  sort?: "newest" | "oldest" | "name";
  page?: number;
  page_size?: number;
}

export interface DocumentListResponse {
  total: number;
  page: number;
  items: DocumentListItem[];
}

export interface BatchListItem {
  id: string;
  created_at: string;
  file_count: number;
  status: BatchStatus;
  label: string; // e.g. "Jun 18, 2026 · batch of 4"
}

// ---- Keyword / topic frequency dashboard ----

export type TaxonomyLevel = "L1" | "L2" | "L3" | "L4";

export interface KeywordStat {
  keyword: string;
  frequency: number; // number of documents the keyword appears in
}

export interface KeywordStatsParams {
  level?: TaxonomyLevel;
  domain?: Domain;
  search?: string;
  limit?: number;
}
