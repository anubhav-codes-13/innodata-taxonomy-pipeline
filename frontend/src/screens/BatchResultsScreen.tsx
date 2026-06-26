import { useNavigate, useParams } from "react-router-dom";
import { AppShell, Container } from "../components/AppShell";
import { Stepper } from "../components/Stepper";
import { Button, Card, DomainChip, PageTitle } from "../components/ui";
import { useBatchResults } from "../lib/hooks";

export function BatchResultsScreen() {
  const { batchId = "" } = useParams();
  const navigate = useNavigate();
  const { data, isLoading } = useBatchResults(batchId);

  const stats = [
    { n: data?.summary.enriched ?? "—", label: "documents enriched" },
    { n: data?.summary.chunks ?? "—", label: "retrieval chunks" },
    { n: data ? `${data.summary.coverage_pct}%` : "—", label: "taxonomy coverage" },
    { n: data?.summary.failed ?? "—", label: "failed" },
  ];

  return (
    <AppShell>
      <Container>
        <Stepper current="Results" />
        <PageTitle sub="Every document now carries a full L1–L4 taxonomy. Open any one to explore, or view all in History.">
          {isLoading ? "Batch complete" : `Batch complete — ${data?.summary.enriched} documents enriched`}
        </PageTitle>

        <div className="mb-6 grid grid-cols-2 gap-5 sm:grid-cols-4">
          {stats.map((s) => (
            <Card key={s.label} className="px-5 py-5">
              <div className="text-[28px] font-bold leading-none text-ink">{s.n}</div>
              <div className="mt-1.5 text-xs text-mut">{s.label}</div>
            </Card>
          ))}
        </div>

        <Card className="overflow-hidden">
          <div className="flex items-center bg-[#F4F6F8] px-5 py-3 text-[11px] font-bold text-mut">
            <span className="flex-1">DOCUMENT</span>
            <span className="w-24">DOMAIN</span>
            <span className="w-80">TOP TOPIC</span>
            <span className="w-20">LEVELS</span>
            <span className="w-8" />
          </div>
          {data?.documents.map((d) => (
            <button
              key={d.document_id}
              onClick={() => navigate(`/documents/${d.document_id}?batch=${batchId}`)}
              className="flex w-full items-center border-t border-hair px-5 py-4 text-left hover:bg-panel"
            >
              <span className="flex-1 truncate text-sm font-semibold text-ink">{d.filename}</span>
              <span className="w-24"><DomainChip domain={d.domain} /></span>
              <span className="w-80 truncate text-[13px] text-body">{d.top_topic}</span>
              <span className="w-20 text-[13px] text-body">{d.levels}</span>
              <span className="w-8 text-bar">→</span>
            </button>
          ))}
        </Card>

        <div className="mt-6 flex items-center">
          <p className="flex-1 text-xs text-mut">Click any row to open its taxonomy →</p>
          <Button onClick={() => navigate("/history")}>View all in History</Button>
        </div>
      </Container>
    </AppShell>
  );
}
