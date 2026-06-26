import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AppShell, Container } from "../components/AppShell";
import { Button, Card, Chip, FormatTag, PageTitle } from "../components/ui";
import { usePendingFiles, useRemoveFile, useUploadFiles } from "../lib/hooks";
import { formatBytes } from "../lib/format";

export function UploadScreen() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const pending = usePendingFiles();
  const files = pending.data ?? [];
  const upload = useUploadFiles();
  const remove = useRemoveFile();

  const apiBase = import.meta.env.VITE_API_BASE_URL;

  const handleFiles = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    upload.mutate(Array.from(list));
  };

  const needsDomain = files.filter((f) => f.needs_domain).length;

  return (
    <AppShell sidebar>
      <Container>
        <PageTitle>Upload documents</PageTitle>

        <div
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            handleFiles(e.dataTransfer.files);
          }}
          className={`flex cursor-pointer flex-col items-center gap-2.5 rounded-xl border-2 border-dashed py-10 transition ${
            dragging ? "border-bar bg-panel" : "border-[#9CA3AF] bg-[#FBFCFD] hover:bg-panel"
          }`}
        >
          <div className="text-lg font-semibold text-body">⬆ Drag files here</div>
          <div className="text-[13px] text-mut">or</div>
          <Button
            onClick={(e) => {
              e.stopPropagation();
              inputRef.current?.click();
            }}
            disabled={upload.isPending}
          >
            {upload.isPending ? "Uploading…" : "Browse files"}
          </Button>
          <div className="text-[13px] text-mut">XML · PDF · DOC · DOCX — multiple files allowed</div>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".xml,.pdf,.doc,.docx"
            className="hidden"
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {(upload.isError || pending.isError) && (
          <div className="mt-4 rounded-lg border border-[#F0C2C2] bg-[#FBEAEA] px-4 py-3 text-sm text-[#9B2B2B]">
            {upload.isError && <div>Upload failed: {(upload.error as Error).message}</div>}
            {pending.isError && (
              <div>
                Couldn't reach the API{apiBase ? ` at ${apiBase}` : ""}: {(pending.error as Error).message}
              </div>
            )}
            {apiBase && (
              <div className="mt-1 text-xs text-[#7A3030]">
                Is the backend running? Start it from the repo root with{" "}
                <code className="rounded bg-white px-1">uvicorn api.main:app --reload</code>
              </div>
            )}
          </div>
        )}

        <h2 className="mb-3 mt-8 text-base font-bold text-ink">Selected files ({files.length})</h2>

        {files.length === 0 ? (
          <p className="text-sm text-mut">No files selected yet. Drag files above or browse to add them.</p>
        ) : (
          <div className="space-y-3">
            {files.map((f) => (
              <Card key={f.id} className="flex items-center gap-4 px-4 py-3.5">
                <FormatTag format={f.format} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-ink">{f.filename}</div>
                  <div className="text-xs text-mut">
                    {formatBytes(f.size)} · {f.format.toUpperCase()}
                  </div>
                </div>
                {f.needs_domain ? (
                  <Chip bg="#FBE9D8" fg="#B5651D">Needs domain</Chip>
                ) : (
                  <Chip bg="#DCEFE3" fg="#2E7D52">Auto: {f.domain}</Chip>
                )}
                <button
                  onClick={() => remove.mutate(f.id)}
                  className="px-1 text-mut hover:text-ink"
                  aria-label="Remove file"
                >
                  ✕
                </button>
              </Card>
            ))}
          </div>
        )}

        <div className="mt-8 flex items-center gap-4">
          <p className="flex-1 text-[13px] text-mut">
            {files.length} file{files.length === 1 ? "" : "s"} selected
            {needsDomain > 0 && ` · ${needsDomain} need a domain before enrichment`}
          </p>
          <Button disabled={files.length === 0} onClick={() => navigate("/confirm")}>
            Continue →
          </Button>
        </div>
      </Container>
    </AppShell>
  );
}
