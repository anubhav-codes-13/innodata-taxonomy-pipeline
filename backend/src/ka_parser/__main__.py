"""CLI: python -m src.ka_parser <xml_dir> [--json-out PATH]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .eda import run_eda


def main() -> int:
    ap = argparse.ArgumentParser(description="KA XML parser + EDA")
    ap.add_argument("xml_dir", help="Directory containing KA XML files")
    ap.add_argument("--json-out", help="Optional path to dump parsed documents as JSON")
    ap.add_argument("--csv-out", help="Optional path to dump document-level DataFrame as CSV")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    r = run_eda(args.xml_dir)
    docs = r["documents"]
    df = r["df"]
    cov = r["coverage"]

    print(f"Parsed {len(docs)} documents from {args.xml_dir}")
    print(f"  by type: {cov.by_doc_type}")
    print(f"  topic coverage: {cov.pct_with_topic}% | keyword coverage: {cov.pct_with_keywords}%")
    print(f"  length stats: {r['length_stats']}")
    print(f"  xref edges: {len(r['xrefs'])} (resolved-in-corpus: {int(r['xrefs']['resolved'].sum()) if len(r['xrefs']) else 0})")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps([d.to_dict() for d in docs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"wrote {args.json_out}")
    if args.csv_out:
        df.to_csv(args.csv_out, index=False, encoding="utf-8")
        print(f"wrote {args.csv_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
