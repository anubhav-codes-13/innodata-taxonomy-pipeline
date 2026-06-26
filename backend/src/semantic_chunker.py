"""
Semantic chunker for KLI parsed_docs.json.

Reads the JSON produced by `src.rag_parser` and emits a flat list of
retrieval-ready chunks using two techniques:

  1. Paragraph Group Chunking (PGC)
     - Splits each section into paragraphs (preserved by rag_parser as
       section.paragraphs; falls back to splitting section.text on blank
       lines for older parser outputs).
     - Groups contiguous paragraphs until the running word count hits a
       soft target (default 500).
     - If adding the next paragraph would push the chunk "significantly"
       over the target (default: > target + slack, where slack = 150),
       finalise the current chunk and start a new one.
     - A single paragraph longer than a hard cap (default 800 words) is
       split on sentence boundaries, then on newlines, as a safety net —
       never with a mid-sentence character slice.

  2. Prefix-Fusion (Contextual Metadata Injection)
     - Prepends a one-line breadcrumb to each chunk before save:
         [Container: {container_title} | Document: {doc_title} | Section: {section_id} - {section_title}]
       followed by a blank line and the chunk body.
     - Missing pieces are omitted from the breadcrumb rather than shown as
       the literal string "None", because the breadcrumb becomes part of
       the embedding input and stray "None" tokens hurt retrieval quality.

Output (chunked_docs.json): a flat JSON array of chunk dicts with keys:
  doc_id, doc_type, section_id, chunk_id, fused_text,
  inherited_topics, inherited_keywords, case_metadata.

Usage:
    python -m src.semantic_chunker <parsed_docs.json> [--out chunked_docs.json]
                                    [--target-words 500] [--max-words 800]
                                    [--slack 150]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Tunable defaults. Kept as module constants so a library caller can import
# and tweak without touching argparse wiring.
# ---------------------------------------------------------------------------

DEFAULT_TARGET_WORDS = 500   # soft target per chunk
DEFAULT_MAX_WORDS    = 800   # hard cap before a single paragraph is split
DEFAULT_SLACK_WORDS  = 150   # "significantly over" = target + slack


# Sentence split that keeps the terminator with the sentence. It's not a full
# NLP sentence splitter; it's a safety-net fallback for paragraphs that are
# already pathologically long. Good enough for legal prose where sentence
# boundaries are usually well-punctuated.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")

# Blank-line paragraph split used ONLY when a parsed section is handed in
# without a pre-split paragraph list (older rag_parser output).
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------

def _word_count(text: str) -> int:
    """Fast whitespace-delimited word count — good enough for chunking budgets."""
    return len(text.split()) if text else 0


def _split_long_paragraph(paragraph: str, max_words: int) -> list[str]:
    """Split a paragraph longer than max_words without breaking sentences.

    Strategy (in order of preference):
      1. Sentence boundaries — preserves meaning best.
      2. Single-newline breaks — some paragraphs contain embedded line breaks.
      3. Hard word-count slice — last resort; only reached if a single
         sentence alone exceeds max_words.
    """
    if _word_count(paragraph) <= max_words:
        return [paragraph]

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(paragraph) if s.strip()]
    if len(sentences) > 1:
        return _pack_units(sentences, max_words)

    # No sentence boundaries found → try newlines.
    lines = [ln.strip() for ln in paragraph.split("\n") if ln.strip()]
    if len(lines) > 1:
        return _pack_units(lines, max_words)

    # Single runaway sentence. Slice on word boundaries — mid-sentence but
    # never mid-token. Flag this with a log line so we know when it happens.
    words = paragraph.split()
    chunks = [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    print(f"[chunker] warning: unsplittable paragraph "
          f"({len(words)} words) sliced on word boundaries", file=sys.stderr)
    return chunks


def _pack_units(units: list[str], max_words: int) -> list[str]:
    """Greedy pack a list of strings into groups of <= max_words.

    Used by the oversize-paragraph fallback — we've already lost paragraph
    structure at this point, so packing sentences tightly is the right move.
    """
    out: list[str] = []
    buf: list[str] = []
    buf_wc = 0
    for u in units:
        w = _word_count(u)
        if buf_wc + w > max_words and buf:
            out.append(" ".join(buf))
            buf, buf_wc = [u], w
        else:
            buf.append(u)
            buf_wc += w
    if buf:
        out.append(" ".join(buf))
    return out


# ---------------------------------------------------------------------------
# Paragraph Group Chunking
# ---------------------------------------------------------------------------

def paragraph_group_chunks(
    paragraphs: list[str],
    target_words: int = DEFAULT_TARGET_WORDS,
    max_words: int = DEFAULT_MAX_WORDS,
    slack_words: int = DEFAULT_SLACK_WORDS,
) -> list[str]:
    """Group `paragraphs` into chunks around `target_words` with `slack_words` grace.

    Rules (matching the brief):
      * Never split a paragraph unless it is natively too long.
      * Close the current chunk as soon as the next paragraph would push the
        total past `target_words + slack_words`.
      * Paragraphs longer than `max_words` are decomposed via
        `_split_long_paragraph` into sub-units that each fit the budget;
        those sub-units then re-enter the packing loop.
    """
    # Flatten oversize paragraphs up-front so the packing loop only deals
    # with paragraphs that are already individually within budget.
    units: list[str] = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if _word_count(p) > max_words:
            units.extend(_split_long_paragraph(p, max_words))
        else:
            units.append(p)

    chunks: list[str] = []
    current: list[str] = []
    current_wc = 0
    upper_bound = target_words + slack_words

    for unit in units:
        w = _word_count(unit)

        # Starting a fresh chunk: just take it, regardless of size. This
        # keeps a short section (e.g. a 40-word annex) as its own 1-chunk
        # output rather than returning an empty list.
        if not current:
            current.append(unit)
            current_wc = w
            continue

        # Would adding this unit overshoot? Close the chunk first.
        if current_wc + w > upper_bound:
            chunks.append("\n\n".join(current))
            current, current_wc = [unit], w
            continue

        # Under target: just append.
        if current_wc < target_words:
            current.append(unit)
            current_wc += w
            continue

        # Between target and upper_bound: accept the paragraph only if it's
        # short enough that the total stays within upper_bound; otherwise
        # start a new chunk. This biases toward respecting the target while
        # still absorbing a small trailing paragraph (e.g. a concluding
        # sentence) rather than orphaning it as its own chunk.
        if current_wc + w <= upper_bound:
            current.append(unit)
            current_wc += w
        else:
            chunks.append("\n\n".join(current))
            current, current_wc = [unit], w

    if current:
        chunks.append("\n\n".join(current))
    return chunks


# ---------------------------------------------------------------------------
# Prefix-Fusion
# ---------------------------------------------------------------------------

def _truthy(value) -> bool:
    """None / '' / [] / {} all count as 'absent' for breadcrumb purposes."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def build_prefix(container_title: str | None,
                 doc_title:       str | None,
                 section_id:      str | None,
                 section_title:   str | None) -> str:
    """Build the lineage breadcrumb.

    Any None / empty piece is silently omitted rather than rendered as
    "None". The section piece intelligently combines id + title depending
    on what's available.
    """
    parts: list[str] = []
    if _truthy(container_title):
        parts.append(f"Container: {container_title}")
    if _truthy(doc_title):
        parts.append(f"Document: {doc_title}")

    # Section sub-rendering: "{id} - {title}" when both present, else just
    # whichever is present. If neither, skip the whole Section segment.
    section_rendered: str | None = None
    if _truthy(section_id) and _truthy(section_title):
        section_rendered = f"{section_id} - {section_title}"
    elif _truthy(section_id):
        section_rendered = str(section_id)
    elif _truthy(section_title):
        section_rendered = str(section_title)
    if section_rendered:
        parts.append(f"Section: {section_rendered}")

    if not parts:
        return ""
    return "[" + " | ".join(parts) + "]"


def fuse(prefix: str, body: str) -> str:
    """Join prefix and body with a blank line, handling the no-prefix case."""
    if not prefix:
        return body
    return f"{prefix}\n\n{body}"


# ---------------------------------------------------------------------------
# Per-document driver
# ---------------------------------------------------------------------------

def _paragraphs_for_section(section: dict) -> list[str]:
    """Prefer the structured paragraph list; fall back to blank-line splitting."""
    paragraphs = section.get("paragraphs")
    if paragraphs:
        return [p for p in paragraphs if p and p.strip()]
    text = section.get("text") or ""
    if not text.strip():
        return []
    return [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]


def _topics_as_strings(topics: list[dict] | list[str] | None) -> list[str]:
    """Flatten rag_parser's {id, text} topics to a simple list of strings.

    We inherit into each chunk for retrieval-time filtering; embedding-time
    strings are simpler and already unique in practice (id & text never
    collide per earlier EDA). Keeps the chunk record cheap.
    """
    if not topics:
        return []
    out: list[str] = []
    for t in topics:
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, dict):
            label = t.get("text") or t.get("id")
            if label:
                out.append(label)
    return out


def chunk_document(doc: dict,
                   target_words: int = DEFAULT_TARGET_WORDS,
                   max_words:    int = DEFAULT_MAX_WORDS,
                   slack_words:  int = DEFAULT_SLACK_WORDS) -> Iterator[dict]:
    """Yield flat chunk dicts for every section in `doc`.

    Document-level fields (topics, keywords, case_metadata) are inherited
    onto each chunk so the chunk store is self-contained for retrieval —
    no join required back to the parsed-doc store.
    """
    metadata    = doc.get("metadata") or {}
    enrichment  = doc.get("enrichment") or {}

    container_title = metadata.get("container_title")
    doc_title       = metadata.get("title")
    doc_id          = doc.get("doc_id")
    doc_type        = doc.get("doc_type")

    inherited_topics   = _topics_as_strings(enrichment.get("topics"))
    inherited_keywords = list(enrichment.get("keywords") or [])
    # cust_groups rides on every chunk so downstream routers can do L1
    # domain assignment without rejoining back to the parsed_docs store.
    cust_groups        = list(metadata.get("cust_groups") or [])
    case_metadata      = doc.get("case_metadata")  # may be None; included only when present

    sections = (doc.get("body") or {}).get("sections") or []
    for section in sections:
        section_id    = section.get("id")
        section_title = section.get("title")
        paragraphs    = _paragraphs_for_section(section)
        if not paragraphs:
            continue

        chunks = paragraph_group_chunks(
            paragraphs,
            target_words=target_words,
            max_words=max_words,
            slack_words=slack_words,
        )

        prefix = build_prefix(container_title, doc_title, section_id, section_title)

        # Chunk IDs: sectionID_chunk_N (1-indexed). When section has no id,
        # fall back to the section's ordinal position to keep chunk_ids
        # unique within the document.
        id_stem = section_id if section_id else f"sec{sections.index(section) + 1}"

        for i, body_text in enumerate(chunks, start=1):
            record: dict = {
                "doc_id":             doc_id,
                "doc_type":           doc_type,
                "cust_groups":        cust_groups,
                "section_id":         section_id,
                "chunk_id":           f"{id_stem}_chunk_{i}",
                "fused_text":         fuse(prefix, body_text),
                "inherited_topics":   inherited_topics,
                "inherited_keywords": inherited_keywords,
            }
            # Only include case_metadata when populated, to keep the chunk
            # store tidy for non-case doc types.
            if case_metadata:
                record["case_metadata"] = case_metadata
            yield record


# ---------------------------------------------------------------------------
# Batch driver + CLI
# ---------------------------------------------------------------------------

def chunk_corpus(parsed_docs: list[dict],
                 target_words: int = DEFAULT_TARGET_WORDS,
                 max_words:    int = DEFAULT_MAX_WORDS,
                 slack_words:  int = DEFAULT_SLACK_WORDS) -> list[dict]:
    out: list[dict] = []
    for doc in parsed_docs:
        out.extend(chunk_document(doc, target_words, max_words, slack_words))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Semantic chunker (PGC + Prefix-Fusion)")
    ap.add_argument("parsed_json", type=Path,
                    help="Input parsed_docs.json produced by src.rag_parser")
    ap.add_argument("--out", type=Path, default=Path("chunked_docs.json"),
                    help="Output path (default: chunked_docs.json in CWD)")
    ap.add_argument("--target-words", type=int, default=DEFAULT_TARGET_WORDS)
    ap.add_argument("--max-words",    type=int, default=DEFAULT_MAX_WORDS)
    ap.add_argument("--slack",        type=int, default=DEFAULT_SLACK_WORDS,
                    help="Words above target at which a chunk is closed")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not args.parsed_json.is_file():
        print(f"[error] {args.parsed_json} not found", file=sys.stderr)
        return 2

    parsed_docs = json.loads(args.parsed_json.read_text(encoding="utf-8"))
    chunks = chunk_corpus(parsed_docs,
                          target_words=args.target_words,
                          max_words=args.max_words,
                          slack_words=args.slack)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(chunks, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # Per-run summary so you can sanity-check output shape.
    wcs = [_word_count(c["fused_text"]) for c in chunks]
    wcs.sort()
    if wcs:
        mid = wcs[len(wcs) // 2]
        print(f"Wrote {len(chunks)} chunks -> {args.out}")
        print(f"  fused_text word count  min={wcs[0]}  median={mid}  max={wcs[-1]}")
    else:
        print(f"Wrote 0 chunks -> {args.out} (no body text in input)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
