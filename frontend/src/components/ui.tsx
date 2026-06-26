import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Domain, FileFormat, FileStatus, Level } from "../lib/types";
import { DOMAIN_LABEL } from "../lib/types";

export function Button({
  variant = "primary",
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  const base = "inline-flex items-center gap-2 rounded-lg text-sm font-semibold px-5 py-2.5 transition disabled:opacity-40 disabled:cursor-not-allowed";
  const styles = {
    primary: "bg-bar text-white hover:bg-ink",
    secondary: "bg-white text-body border border-line hover:bg-panel",
    ghost: "text-body hover:bg-panel",
  }[variant];
  return (
    <button className={`${base} ${styles} ${className}`} {...rest}>
      {children}
    </button>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-line bg-white ${className}`}>{children}</div>;
}

export function Chip({ children, bg, fg }: { children: ReactNode; bg: string; fg: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold" style={{ backgroundColor: bg, color: fg }}>
      {children}
    </span>
  );
}

export function LevelBadge({ level }: { level: Level }) {
  return (
    <span className="rounded-full bg-[#E3E7EB] px-2 py-0.5 text-[10px] font-bold text-mut">{level}</span>
  );
}

export function DomainChip({ domain, full = false }: { domain: Domain; full?: boolean }) {
  const c = domain === "KA" ? { bg: "#DCE7F7", fg: "#2B5C9B" } : { bg: "#E0DEF7", fg: "#3B2B9B" };
  return <Chip bg={c.bg} fg={c.fg}>{full ? DOMAIN_LABEL[domain] : domain}</Chip>;
}

export function FormatTag({ format }: { format: FileFormat }) {
  const map: Record<FileFormat, { label: string; bg: string; fg: string }> = {
    xml: { label: "XML", bg: "#DCE7F7", fg: "#2B5C9B" },
    pdf: { label: "PDF", bg: "#F7DCDC", fg: "#9B2B2B" },
    docx: { label: "DOC", bg: "#E0DEF7", fg: "#3B2B9B" },
  };
  const c = map[format];
  return (
    <span className="inline-flex w-12 justify-center rounded-md py-1 text-[11px] font-bold" style={{ backgroundColor: c.bg, color: c.fg }}>
      {c.label}
    </span>
  );
}

const STATUS_META: Record<FileStatus, { label: string; bg: string; fg: string }> = {
  pending: { label: "Ready", bg: "#EDF0F2", fg: "#6B7280" },
  queued: { label: "Queued", bg: "#F1F3F5", fg: "#8A93A0" },
  extracting: { label: "Extracting", bg: "#E3E7EB", fg: "#3A4250" },
  parsing: { label: "Parsing", bg: "#E3E7EB", fg: "#3A4250" },
  chunking: { label: "Chunking", bg: "#E3E7EB", fg: "#3A4250" },
  routing: { label: "Routing", bg: "#E3E7EB", fg: "#3A4250" },
  enriching: { label: "Enriching", bg: "#E3E7EB", fg: "#3A4250" },
  synthesizing: { label: "Synthesizing", bg: "#E3E7EB", fg: "#3A4250" },
  processing: { label: "Processing", bg: "#E3E7EB", fg: "#3A4250" },
  done: { label: "Done", bg: "#DCEFE3", fg: "#2E7D52" },
  failed: { label: "Failed", bg: "#F7DCDC", fg: "#9B2B2B" },
};

export function StatusChip({ status, label }: { status: FileStatus; label?: string }) {
  const m = STATUS_META[status];
  return <Chip bg={m.bg} fg={m.fg}>{label ?? m.label}</Chip>;
}

export function ProgressBar({ value, className = "" }: { value: number; className?: string }) {
  return (
    <div className={`h-2.5 w-full overflow-hidden rounded-full bg-[#E3E7EB] ${className}`}>
      <div className="h-full rounded-full bg-bar transition-all duration-500" style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-6">
      <h1 className="text-[28px] font-bold leading-tight text-ink">{children}</h1>
      {sub && <p className="mt-1 text-sm text-mut">{sub}</p>}
    </div>
  );
}
