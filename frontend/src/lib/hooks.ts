import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useApi } from "./api";
import type { Batch, DocumentListParams, Domain, KeywordStatsParams } from "./types";

// ---- queries ----

export function usePendingFiles() {
  const api = useApi();
  return useQuery({ queryKey: ["pendingFiles"], queryFn: () => api.listPendingFiles() });
}

export function useBatchResults(batchId: string) {
  const api = useApi();
  return useQuery({ queryKey: ["batchResults", batchId], queryFn: () => api.getBatchResults(batchId) });
}

export function useDocument(documentId: string) {
  const api = useApi();
  return useQuery({ queryKey: ["document", documentId], queryFn: () => api.getDocument(documentId) });
}

export function useBeforeAfter(documentId: string) {
  const api = useApi();
  return useQuery({ queryKey: ["beforeAfter", documentId], queryFn: () => api.getBeforeAfter(documentId) });
}

export function useEnrichedChunks(documentId: string) {
  const api = useApi();
  return useQuery({ queryKey: ["enrichedChunks", documentId], queryFn: () => api.getEnrichedChunks(documentId) });
}

export function useBatchDocumentIds(batchId: string | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: ["batchDocIds", batchId],
    queryFn: () => api.getBatchDocumentIds(batchId!),
    enabled: !!batchId,
  });
}

export function useDocumentList(params: DocumentListParams) {
  const api = useApi();
  return useQuery({ queryKey: ["documents", params], queryFn: () => api.listDocuments(params) });
}

export function useBatches() {
  const api = useApi();
  return useQuery({ queryKey: ["batches"], queryFn: () => api.listBatches() });
}

export function useKeywordStats(params: KeywordStatsParams) {
  const api = useApi();
  return useQuery({ queryKey: ["keywords", params], queryFn: () => api.getKeywordStats(params) });
}

// ---- mutations ----

export function useUploadFiles() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) => api.uploadFiles(files),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pendingFiles"] }),
  });
}

export function useSetFileDomain() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ fileId, domain }: { fileId: string; domain: Domain }) => api.setFileDomain(fileId, domain),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pendingFiles"] }),
  });
}

export function useRemoveFile() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fileId: string) => api.removeFile(fileId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pendingFiles"] });
      qc.invalidateQueries({ queryKey: ["documents"] }); // History list refreshes too
    },
  });
}

export function useCreateBatch() {
  const api = useApi();
  return useMutation({ mutationFn: (fileIds: string[]) => api.createBatch(fileIds) });
}

// ---- live progress (fake SSE) ----

export function useBatchEvents(batchId: string | undefined): Batch | null {
  const api = useApi();
  const [batch, setBatch] = useState<Batch | null>(null);
  useEffect(() => {
    if (!batchId) return;
    const unsub = api.subscribeBatch(batchId, setBatch);
    return unsub;
  }, [api, batchId]);
  return batch;
}
