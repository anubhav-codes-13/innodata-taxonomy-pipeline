import { createContext, useContext } from "react";
import type {
  Batch,
  BatchListItem,
  BatchResults,
  BeforeAfter,
  DocumentDetail,
  DocumentListParams,
  DocumentListResponse,
  Domain,
  EnrichedChunk,
  KeywordStat,
  KeywordStatsParams,
  UploadedFile,
} from "./types";

// A single seam the whole app talks to. The mock implements it today; a
// `fetch`-based HttpApiClient will implement the same interface against the
// FastAPI backend later — no screen/hook changes required.
export interface ApiClient {
  // upload + confirm
  uploadFiles(files: File[]): Promise<UploadedFile[]>;
  listPendingFiles(): Promise<UploadedFile[]>;
  setFileDomain(fileId: string, domain: Domain): Promise<UploadedFile>;
  removeFile(fileId: string): Promise<void>;

  // batch lifecycle
  createBatch(fileIds: string[]): Promise<{ batch_id: string }>;
  getBatch(batchId: string): Promise<Batch>;
  /** Fake SSE: invokes onUpdate as phases advance. Returns an unsubscribe fn. */
  subscribeBatch(batchId: string, onUpdate: (b: Batch) => void): () => void;
  getBatchResults(batchId: string): Promise<BatchResults>;

  // documents
  getDocument(documentId: string): Promise<DocumentDetail>;
  getBeforeAfter(documentId: string): Promise<BeforeAfter>;
  /** The enriched source chunks (passages + L1–L4) behind a document. */
  getEnrichedChunks(documentId: string): Promise<EnrichedChunk[]>;
  /** Ordered document ids in a batch — powers the Explorer file pager. */
  getBatchDocumentIds(batchId: string): Promise<string[]>;

  // history
  listDocuments(params: DocumentListParams): Promise<DocumentListResponse>;
  listBatches(): Promise<BatchListItem[]>;

  // dashboard — cross-document keyword frequency (highest first)
  getKeywordStats(params: KeywordStatsParams): Promise<KeywordStat[]>;
}

export const ApiContext = createContext<ApiClient | null>(null);

export function useApi(): ApiClient {
  const api = useContext(ApiContext);
  if (!api) throw new Error("useApi must be used within <ApiProvider>");
  return api;
}
