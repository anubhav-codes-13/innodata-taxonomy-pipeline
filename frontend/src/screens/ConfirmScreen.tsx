import { useNavigate } from "react-router-dom";
import { AppShell, Container } from "../components/AppShell";
import { Stepper } from "../components/Stepper";
import { Button, Card, Chip, PageTitle } from "../components/ui";
import { useCreateBatch, usePendingFiles, useSetFileDomain } from "../lib/hooks";
import type { Domain } from "../lib/types";

export function ConfirmScreen() {
  const navigate = useNavigate();
  const { data: files = [] } = usePendingFiles();
  const setDomain = useSetFileDomain();
  const createBatch = useCreateBatch();

  const blocked = files.length === 0 || files.some((f) => f.needs_domain);

  const start = () => {
    createBatch.mutate(
      files.map((f) => f.id),
      { onSuccess: ({ batch_id }) => navigate(`/batches/${batch_id}/processing`) },
    );
  };

  const Segmented = ({ fileId, value }: { fileId: string; value: Domain | null }) => (
    <div className="flex items-center gap-1.5">
      {(["KA", "KCL"] as Domain[]).map((d) => (
        <button
          key={d}
          onClick={() => setDomain.mutate({ fileId, domain: d })}
          className={`rounded-md px-3.5 py-1.5 text-xs font-semibold transition ${
            value === d ? "bg-bar text-white" : "bg-[#EEF0F2] text-body hover:bg-[#E3E7EB]"
          }`}
        >
          {d}
        </button>
      ))}
    </div>
  );

  return (
    <AppShell>
      <Container>
        <Stepper current="Confirm" />
        <PageTitle sub="PDF and DOC files have no domain tag — assign one before enrichment. XML files are auto-detected from cust-group.">
          Confirm details
        </PageTitle>

        {files.length === 0 ? (
          <p className="text-sm text-mut">
            No files to confirm. <button className="font-semibold text-ink underline" onClick={() => navigate("/")}>Go back to upload.</button>
          </p>
        ) : (
          <Card className="overflow-hidden">
            <div className="flex items-center bg-[#F4F6F8] px-5 py-3 text-[11px] font-bold text-mut">
              <span className="flex-1">FILE</span>
              <span className="w-28">TYPE</span>
              <span className="w-60">LEGAL DOMAIN</span>
            </div>
            {files.map((f) => (
              <div key={f.id} className="flex items-center border-t border-hair px-5 py-4">
                <span className="flex-1 truncate text-sm font-semibold text-ink">{f.filename}</span>
                <span className="w-28 text-xs text-mut">{f.format.toUpperCase()}</span>
                <span className="w-60">
                  {f.format === "xml" ? (
                    <Chip bg="#DCEFE3" fg="#2E7D52">{f.domain} · auto</Chip>
                  ) : (
                    <Segmented fileId={f.id} value={f.domain} />
                  )}
                </span>
              </div>
            ))}
          </Card>
        )}

        {files.length > 0 && (
          <div className="mt-7 flex items-center">
            <Button variant="secondary" onClick={() => navigate("/")}>← Back</Button>
            <div className="flex-1" />
            <Button disabled={blocked || createBatch.isPending} onClick={start}>
              {createBatch.isPending ? "Starting…" : `Enrich all ${files.length} file${files.length === 1 ? "" : "s"} →`}
            </Button>
          </div>
        )}
        {createBatch.isError && (
          <p className="mt-3 text-sm text-[#9B2B2B]">{(createBatch.error as Error).message}</p>
        )}
      </Container>
    </AppShell>
  );
}
