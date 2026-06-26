import { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AppShell, Container } from "../components/AppShell";
import { Stepper } from "../components/Stepper";
import { Button, Card, PageTitle, ProgressBar, StatusChip } from "../components/ui";
import { useBatchEvents } from "../lib/hooks";
import type { BatchFileState } from "../lib/types";

const ACTIVE_STATUSES = new Set<BatchFileState["status"]>([
  "extracting",
  "parsing",
  "chunking",
  "routing",
  "enriching",
  "synthesizing",
  "processing",
]);

const PHASE_DETAIL: Record<string, string> = {
  extracting: "Extracting text from document…",
  parsing: "Parsing XML into structured JSON…",
  chunking: "Chunking into retrieval passages…",
  routing: "Routing to L1 domain + L2 topic…",
  enriching: "Extracting L3 sub-topics + L4 entities/keywords…",
  synthesizing: "Rolling up the L1–L4 taxonomy…",
};

function fileDetail(f: BatchFileState): string {
  if (f.status === "done")
    return f.chunk_count != null
      ? `Taxonomy L1–L4 complete · ${f.chunk_count} chunk${f.chunk_count === 1 ? "" : "s"}`
      : "Taxonomy L1–L4 complete";
  if (f.status === "failed") return f.error ?? "Failed";
  if (f.status === "queued") return "Waiting in queue";
  return PHASE_DETAIL[f.status] ?? "Processing…";
}

function Icon({ status }: { status: BatchFileState["status"] }) {
  if (status === "done") return <span className="text-base font-bold text-[#3FA66A]">✓</span>;
  if (status === "failed") return <span className="text-base font-bold text-[#9B2B2B]">✕</span>;
  if (status === "queued") return <span className="text-base text-mut">○</span>;
  return <span className="text-base text-bar">●</span>;
}

export function ProcessingScreen() {
  const { batchId } = useParams();
  const navigate = useNavigate();
  const batch = useBatchEvents(batchId);

  const done = batch?.status === "complete" || batch?.status === "partial_failure";
  useEffect(() => {
    if (done && batchId) {
      const t = setTimeout(() => navigate(`/batches/${batchId}/results`), 900);
      return () => clearTimeout(t);
    }
  }, [done, batchId, navigate]);

  if (!batch) {
    return (
      <AppShell>
        <Container>
          <Stepper current="Process" />
          <PageTitle>Processing</PageTitle>
          <p className="text-sm text-mut">
            This batch is no longer available (the demo keeps batches in memory).{" "}
            <button className="font-semibold text-ink underline" onClick={() => navigate("/")}>Start a new upload.</button>
          </p>
        </Container>
      </AppShell>
    );
  }

  const total = batch.files.length;
  const completed = batch.files.filter((f) => f.status === "done").length;
  const active = batch.files.filter((f) => ACTIVE_STATUSES.has(f.status)).length;
  const queued = batch.files.filter((f) => f.status === "queued").length;
  const failed = batch.files.filter((f) => f.status === "failed").length;

  return (
    <AppShell>
      <Container>
        <Stepper current="Process" />
        <PageTitle>Enriching {total} documents</PageTitle>

        <Card className="mb-5 px-5 py-4">
          <div className="mb-3 text-sm font-semibold text-ink">
            {completed} of {total} complete
            <span className="font-normal text-mut">
              {active > 0 && ` · ${active} processing`}
              {queued > 0 && ` · ${queued} queued`}
              {failed > 0 && ` · ${failed} failed`}
            </span>
          </div>
          <ProgressBar value={batch.overall_progress} />
        </Card>

        <div className="space-y-3">
          {batch.files.map((f) => (
            <Card key={f.id} className="flex items-center gap-3.5 px-4 py-4">
              <Icon status={f.status} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-ink">{f.filename}</div>
                <div className="text-xs text-mut">{fileDetail(f)}</div>
              </div>
              <StatusChip status={f.status} />
            </Card>
          ))}
        </div>

        {done && (
          <div className="mt-7 flex justify-end">
            <Button onClick={() => navigate(`/batches/${batchId}/results`)}>View results →</Button>
          </div>
        )}
      </Container>
    </AppShell>
  );
}
