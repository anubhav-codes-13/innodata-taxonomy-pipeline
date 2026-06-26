"""
KLI KEA-BASIC XML -> RAG-ready JSON.

Parses a directory of Kluwer Law International XML files (all five KEA-BASIC
doc types: essay / legislation / commentary / caselaw / booktoc) into a clean
nested JSON structure suitable for an LLM-based RAG pipeline.

Pre-processing safeguards (critical — stock stdlib parsing WILL fail without
them on the real corpus):

  1. Strip DOCTYPE declarations, including internal subsets like
        <!DOCTYPE KEA-publ PUBLIC "..." "keabasic.dtd" [
          <!ENTITY SLSD_3321749_gif SYSTEM "..." NDATA GIF> ... ]>
     These internal subsets declare binary GIF entities that ElementTree
     cannot resolve and will raise ParseError on.

  2. Strip XML comments. 56% of KA files and 86% of KCL files in the sample
     keep an older <frontmatter> commented out alongside the current one.
     Without stripping, any comment-aware downstream logic would double-count
     metadata; additionally, some legacy comments contain malformed fragments
     that break strict parsers.

  3. Strip <?page nr="..."?> processing instructions. These pagination
     markers sit inline inside <p> text and otherwise duplicate whitespace
     around them when the element tree is flattened.

Output JSON shape (per document):

{
  "doc_type": "essay|legislation|commentary|caselaw|booktoc",
  "doc_id":   "KLI-JOIA-420501",
  "lang":     "en",
  "source_file": "KLI-JOIA-420501.xml",

  "metadata": {
    "title":            "...",
    "authors":          ["First Last", ...],
    "editors":          ["First Last", ...],
    "publisher":        "Kluwer Law International",
    "publ_year":        2025,
    "publ_date":        "20251000",
    "container_title":  "Journal of International Arbitration",
    "isbn":             null,
    "issn":             "0255-8106",
    "volume":           "42",
    "issue":            "5",
    "cust_groups":      ["KA", "CH"]
  },

  "enrichment": {
    "topics":        [{"id": "Arb-001", "text": "Investment Arbitration"}],
    "keywords":      ["ICSID Convention", ...],
    "countries":     [{"code": "LV", "name": "Latvia"}],
    "organizations": [{"code": "ORG0244", "name": "ICSID"}]
  },

  "case_metadata": {                   // only for commentary / caselaw; else null
    "court":         "European Union Court of Justice ...",
    "case_number":   "C-475/08",
    "case_name":     "Commission v. Belgium",
    "decision_date": "20091203",
    "parties": [
      {"role": "Applicant", "name": "Commission"},
      {"role": "Defendant", "name": "Belgium"}
    ]
  },

  "body": {
    "wrapper": "text|legis-text|juris-text|juris-comment|legis-comment",
    "sections": [
      {"id": "S0001", "title": "INTRODUCTION", "text": "..."}
    ]
  }
}

Usage:
    python -m src.rag_parser <xml_dir> [--out parsed_docs.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# Pre-processing regexes. All operate on bytes so we can run BEFORE decoding;
# this avoids re-encoding issues with the occasional non-ASCII name (e.g. "Rémy").
# ---------------------------------------------------------------------------

# Matches the entire DOCTYPE declaration, with or without an internal subset.
#   <!DOCTYPE KEA-publ PUBLIC "..." "keabasic.dtd">
#   <!DOCTYPE KEA-publ PUBLIC "..." "keabasic.dtd" [ <!ENTITY ...> ... ]>
# re.DOTALL because the internal subset can span multiple lines.
_DOCTYPE_RE = re.compile(rb"<!DOCTYPE\s[^\[>]*(\[[^\]]*\])?\s*>", re.DOTALL)

# Matches any XML comment (including multi-line ones).
_COMMENT_RE = re.compile(rb"<!--.*?-->", re.DOTALL)

# Matches <?page nr="533"?> and any similar page PI variants.
_PAGE_PI_RE = re.compile(rb"<\?page\b[^?]*\?>")

# Whitespace collapse for extracted text.
_WS_RE = re.compile(r"\s+")


def preprocess(raw: bytes) -> bytes:
    """Apply the three mandatory pre-processing steps in the required order.

    Order matters: comments must go first, because a DOCTYPE-looking string
    could appear inside a comment, and stripping the DOCTYPE regex across a
    commented block would leave an unbalanced `-->`.
    """
    raw = _COMMENT_RE.sub(b"", raw)
    raw = _DOCTYPE_RE.sub(b"", raw, count=1)
    raw = _PAGE_PI_RE.sub(b"", raw)
    return raw


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

# Tags whose content we deliberately SKIP when flattening section text. The
# spec mandates dropping <note> (footnotes) so they don't pollute retrieval.
_SKIP_TAGS: frozenset[str] = frozenset({"note"})


def _inner_text(elem: ET.Element | None, skip: frozenset[str] = _SKIP_TAGS) -> str:
    """Return whitespace-normalised text of `elem`, skipping subtrees in `skip`.

    This is a custom walker (not `ElementTree.itertext`) because we need to
    prune entire <note> subtrees while still keeping the surrounding .tail
    text that follows them. Omitting the .tail would fuse the words adjacent
    to the footnote marker into the previous token.
    """
    if elem is None:
        return ""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag in skip:
            # Drop child's own content, but keep child.tail (the text that
            # comes AFTER the closing </note> and belongs to the parent flow).
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(_inner_text(child, skip))
        if child.tail:
            parts.append(child.tail)
    return _WS_RE.sub(" ", "".join(parts)).strip()


def _first_text(parent: ET.Element, tag: str) -> str | None:
    """First matching child element's text, or None if missing/empty."""
    found = parent.find(tag)
    if found is None:
        return None
    t = _inner_text(found)
    return t or None


def _name_to_string(name_elem: ET.Element) -> str:
    """<name>First<surname value="123">Last</surname></name> -> 'First Last'."""
    first = (name_elem.text or "").strip()
    surname = name_elem.find("surname")
    last = _inner_text(surname) if surname is not None else ""
    return _WS_RE.sub(" ", f"{first} {last}".strip())


# ---------------------------------------------------------------------------
# Section extractor (top-level only per spec, notes stripped)
# ---------------------------------------------------------------------------

# Body wrappers per doc_type. Kept as a single mapping so unknown/new doc
# types fail loudly rather than silently yielding empty bodies.
_BODY_WRAPPERS: dict[str, tuple[str, ...]] = {
    "essay":       ("text",),
    "legislation": ("legis-text",),          # nested under <legis>
    "caselaw":     ("juris-text",),          # nested under <juris>
    "commentary":  ("juris-comment", "legis-comment"),
    "booktoc":     ("booktoc-text",),
}

# Section element names per wrapper. Legislation uses <legis-section>; the
# others all use <section>. Booktoc uses <booktoc-section> but booktoc has no
# real body and is handled separately.
_SECTION_TAGS: tuple[str, ...] = ("section", "legis-section")


def _locate_body_wrapper(inner: ET.Element, doc_type: str) -> tuple[str | None, ET.Element | None]:
    """Find the body wrapper element for the given doc type.

    Returns (wrapper_tag_name, wrapper_element) so the caller can record
    which variant was found — useful for downstream debugging and for
    emitting the `body.wrapper` field required by the output schema.
    """
    if doc_type == "legislation":
        legis = inner.find("legis")
        if legis is not None:
            lt = legis.find("legis-text")
            if lt is not None:
                return "legis-text", lt
        return None, None

    if doc_type == "caselaw":
        juris = inner.find("juris")
        if juris is not None:
            jt = juris.find("juris-text")
            if jt is not None:
                return "juris-text", jt
        return None, None

    for wrapper_name in _BODY_WRAPPERS.get(doc_type, ()):
        w = inner.find(wrapper_name)
        if w is not None:
            return wrapper_name, w
    return None, None


def _collect_paragraphs(section: ET.Element) -> list[str]:
    """Flatten a <section> into an ordered list of paragraph strings.

    We walk the section's direct children (and one level down for containers
    like <blockquote>/<list>) and emit one entry per <p>-like element.
    <note> subtrees are still skipped (note.tail text flows into the
    surrounding paragraph via _inner_text's skip handling).

    Why not just split on <p>? Because <list>/<item> and <blockquote> wrap
    their own <p> children — treating them as one logical paragraph each
    matches the visual reading structure better than exploding every leaf.
    """
    paragraphs: list[str] = []

    def emit(elem: ET.Element) -> None:
        t = _inner_text(elem)
        if t:
            paragraphs.append(t)

    for child in section:
        if child.tag in _SKIP_TAGS:
            continue
        if child.tag == "p":
            emit(child)
        elif child.tag in ("blockquote", "list", "item"):
            # One paragraph per block-level container — preserves quoted
            # material and list items as coherent units.
            emit(child)
        elif child.tag in _SECTION_TAGS:
            # Nested sections: expose their paragraphs at the same level as
            # the parent's so chunking sees a flat paragraph stream.
            paragraphs.extend(_collect_paragraphs(child))
        elif child.tag in ("number", "title"):
            # Section numbering/title are captured separately; don't double-emit.
            continue
        else:
            # Any other direct child (e.g. <abstract>, inline table wrappers)
            # treat as its own paragraph.
            emit(child)

    return paragraphs


def _extract_sections(body: ET.Element) -> list[dict]:
    """Top-level <section>/<legis-section> children as {id, title, text, paragraphs}.

    Per spec:
      - only TOP-LEVEL sections are emitted (nested sections are flattened
        into their parent's text; nested-section-aware chunking is a
        downstream concern)
      - `<note>` footnotes are stripped from the text payload

    `paragraphs` is added for downstream semantic chunking; it preserves
    <p>-level boundaries that `text` (a single whitespace-collapsed string)
    loses. Consumers that only want the joined text can ignore it.
    """
    sections: list[dict] = []
    top = [c for c in body if c.tag in _SECTION_TAGS]

    # Some body wrappers (especially short entries) have no <section> — just
    # a bare <p> stream. Emit that as a single unnamed section so the doc
    # isn't silently dropped.
    if not top:
        flat = _inner_text(body)
        if flat:
            sections.append({
                "id": None, "title": None,
                "text": flat,
                "paragraphs": _collect_paragraphs(body),
            })
        return sections

    for s in top:
        sections.append({
            "id":         s.attrib.get("id"),
            "title":      _first_text(s, "title"),
            "text":       _inner_text(s),
            "paragraphs": _collect_paragraphs(s),
        })
    return sections


# ---------------------------------------------------------------------------
# Group extractors — one per JSON sub-block
# ---------------------------------------------------------------------------

def _extract_metadata(inner: ET.Element) -> dict:
    """Pull bibliographic fields out of <frontmatter>/<publication-info>."""
    md: dict = {
        "title": None,
        "authors": [],
        "editors": [],
        "publisher": None,
        "publ_year": None,
        "publ_date": None,
        "container_title": None,
        "isbn": None,
        "issn": None,
        "volume": None,
        "issue": None,
        "cust_groups": [],
    }
    fm = inner.find("frontmatter")
    if fm is None:
        return md

    md["title"] = _first_text(fm, "title")
    for name_elem in fm.findall("./authorgroup/author/name"):
        name = _name_to_string(name_elem)
        if name:
            md["authors"].append(name)

    pub = fm.find("publication-info")
    if pub is None:
        return md

    md["container_title"] = _first_text(pub, "title")
    for name_elem in pub.findall("./authorgroup/editor/name"):
        name = _name_to_string(name_elem)
        if name:
            md["editors"].append(name)

    publisher = pub.find("./publisher/name")
    md["publisher"] = _inner_text(publisher) if publisher is not None else None

    pd = pub.find("publ-date")
    if pd is not None:
        md["publ_date"] = pd.attrib.get("value")
        # publ-date uses YYYYMMDD (with MM/DD possibly "00" for year-only dates).
        if md["publ_date"] and md["publ_date"][:4].isdigit():
            md["publ_year"] = int(md["publ_date"][:4])

    md["isbn"] = _first_text(pub, "isbn")
    md["issn"] = _first_text(pub, "issn")
    md["volume"] = _first_text(pub, "edition/volume")
    md["issue"] = _first_text(pub, "edition/issue")

    for cg in pub.findall("cust-group"):
        v = cg.attrib.get("value")
        if v:
            md["cust_groups"].append(v)

    return md


def _extract_enrichment(desc: ET.Element | None) -> dict:
    """Pull existing enrichment out of a <text-description>-shaped element.

    `desc` can be <text-description> (essay), <legis-description> (legislation
    and legis-comment), or <juris-description> (caselaw and juris-comment).
    All three share the topic/keywords/text-scope sub-schema.
    """
    enr: dict = {"topics": [], "keywords": [], "countries": [], "organizations": []}
    if desc is None:
        return enr

    for topic in desc.findall("topic"):
        text = _inner_text(topic)
        tid = topic.attrib.get("id")
        # Skip topics that are both empty text AND missing an id: those are
        # placeholder <topic/> elements the editorial system emits when the
        # doc hasn't been classified yet.
        if not text and not tid:
            continue
        enr["topics"].append({"id": tid, "text": text or None})

    for kw in desc.findall("./keywords/keyword"):
        text = _inner_text(kw)
        if text:
            enr["keywords"].append(text)

    scope = desc.find("text-scope")
    if scope is not None:
        for c in scope.findall("country"):
            name = _inner_text(c)
            code = c.attrib.get("value")
            if name or code:
                enr["countries"].append({"code": code, "name": name or None})
        for o in scope.findall("organization"):
            name = _inner_text(o)
            code = o.attrib.get("value")
            if name or code:
                enr["organizations"].append({"code": code, "name": name or None})

    return enr


# Party strings in the corpus look like "Applicant Commission", "Defendant
# Belgium", "Appellant DJP". Role is the first whitespace-separated token;
# the rest is the name. Fall back to role=None when there's no space.
_PARTY_SPLIT_RE = re.compile(r"^\s*(\S+)\s+(.*\S)\s*$")


def _split_party(raw: str) -> dict:
    m = _PARTY_SPLIT_RE.match(raw)
    if not m:
        return {"role": None, "name": raw.strip() or None}
    role, name = m.group(1), m.group(2)
    return {"role": role, "name": name}


def _extract_case_metadata(desc: ET.Element) -> dict:
    """Case-specific metadata shared between caselaw and commentary/case-note.

    Element map (both shapes):
      <juris-description>
        <juris-authority>...</juris-authority>      # caselaw
        <juris-court>...</juris-court>              # commentary (case-note)
        <juris-name>Commission v. Belgium</juris-name>
        <juris-number>C-475/08</juris-number>
        <juris-date value="20091203"/>
        <juris-parties>
          <juris-party>Applicant Commission</juris-party>
          ...
        </juris-parties>
      </juris-description>
    """
    court = _first_text(desc, "juris-authority") or _first_text(desc, "juris-court")

    date = None
    jdate = desc.find("juris-date")
    if jdate is not None:
        date = jdate.attrib.get("value")

    parties = [_split_party(_inner_text(p))
               for p in desc.findall("./juris-parties/juris-party")
               if _inner_text(p)]

    return {
        "court":         court,
        "case_number":   _first_text(desc, "juris-number"),
        "case_name":     _first_text(desc, "juris-name"),
        "decision_date": date,
        "parties":       parties,
    }


# ---------------------------------------------------------------------------
# Doc-type-specific routing
# ---------------------------------------------------------------------------

def _find_description(inner: ET.Element, doc_type: str) -> ET.Element | None:
    """Locate the enrichment-carrying description element for a doc type.

    For essays it sits directly under the doc element; for commentary and
    caselaw it lives under the body wrapper (juris-comment / juris /
    legis-comment) as <juris-description> or <legis-description>.
    """
    if doc_type == "essay":
        return inner.find("text-description")

    if doc_type == "caselaw":
        juris = inner.find("juris")
        return juris.find("juris-description") if juris is not None else None

    if doc_type == "commentary":
        for wrapper_tag, desc_tag in (
            ("juris-comment", "juris-description"),
            ("legis-comment", "legis-description"),
        ):
            wrapper = inner.find(wrapper_tag)
            if wrapper is not None:
                return wrapper.find(desc_tag)
        return None

    if doc_type == "legislation":
        legis = inner.find("legis")
        return legis.find("legis-description") if legis is not None else None

    return None


def _is_case_type(doc_type: str) -> bool:
    return doc_type in ("caselaw", "commentary")


# ---------------------------------------------------------------------------
# Cross-reference / edge extraction (Phase 2.2 — knowledge graph input)
# ---------------------------------------------------------------------------

def _extract_xrefs(inner: ET.Element, doc_type: str) -> list[dict]:
    """Collect every <xref> inside the document as a graph-edge candidate.

    We traverse the ENTIRE inner element (body + frontmatter + description)
    because cross-references can legitimately appear anywhere — footnotes,
    TOC titles, author bio lines, etc. The downstream relationship extractor
    decides which ones to promote into the graph.

    Each entry:
      {target: "<xref/@value>", type: "<xref/@type>", text: "<inner text>"}

    For <booktoc> docs we additionally surface each <booktoc-section> as a
    synthetic toc-type edge, even if its <xref> had no explicit type.
    """
    edges: list[dict] = []

    for x in inner.iter("xref"):
        target = (x.attrib.get("value") or "").strip()
        if not target:
            continue
        edges.append({
            "target": target,
            "type":   x.attrib.get("type") or None,
            "text":   _inner_text(x) or None,
        })

    # Booktoc: the <xref> inside <booktoc-title> often has no type attribute
    # in source XML, so it wouldn't be marked as a TOC edge without this
    # override. Mark those edges as type="toc" explicitly.
    if doc_type == "booktoc":
        for bsec in inner.findall(".//booktoc-section"):
            title = bsec.find("booktoc-title")
            if title is None:
                continue
            xref = title.find("xref")
            if xref is None:
                continue
            target = (xref.attrib.get("value") or "").strip()
            if not target:
                continue
            # Find the matching edge already collected by the generic pass
            # and upgrade its type to "toc". If it's not found for some
            # reason, append a new one.
            matched = next((e for e in edges
                            if e["target"] == target and not e["type"]), None)
            if matched is not None:
                matched["type"] = "toc"
                # Prefer the richer breadcrumb text from <booktoc-title>
                # over the bare <xref> label when we upgrade.
                full_title = _inner_text(title)
                if full_title:
                    matched["text"] = full_title
            else:
                edges.append({
                    "target": target,
                    "type":   "toc",
                    "text":   _inner_text(title) or None,
                })

    return edges


# ---------------------------------------------------------------------------
# Top-level parse entry
# ---------------------------------------------------------------------------

_VALID_DOC_TYPES: frozenset[str] = frozenset({
    "essay", "legislation", "commentary", "caselaw", "booktoc",
})


def parse_file(path: Path) -> dict | None:
    """Parse a single XML file and return a dict matching the output schema.

    Returns None (after logging) for files that (a) fail XML parsing or
    (b) have an unrecognised inner doc type. Callers that care about
    partial failures should check the return value.
    """
    raw = path.read_bytes()
    raw = preprocess(raw)

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"[parse-error] {path.name}: {e}", file=sys.stderr)
        return None

    # Real content lives under <KEA-publ> → doc-type element. When the root
    # IS the doc-type element (defensive), fall through to using root itself.
    inner = root[0] if (root.tag == "KEA-publ" and len(root) > 0) else root
    doc_type = inner.tag

    if doc_type not in _VALID_DOC_TYPES:
        print(f"[unknown-doc-type] {path.name}: <{doc_type}>", file=sys.stderr)
        return None

    # Body extraction. Booktoc has no body text; the body block is just empty.
    wrapper_name, body_elem = _locate_body_wrapper(inner, doc_type)
    sections = _extract_sections(body_elem) if body_elem is not None else []

    # Enrichment lives in a doc-type-specific description element.
    desc = _find_description(inner, doc_type)

    out: dict = {
        "doc_type":    doc_type,
        "doc_id":      inner.attrib.get("id"),
        "lang":        inner.attrib.get("lang"),
        "source_file": path.name,
        "metadata":    _extract_metadata(inner),
        "enrichment":  _extract_enrichment(desc),
        # Case metadata slot is present for ALL docs (value=null when N/A) so
        # downstream schema validation doesn't need per-type handling.
        "case_metadata": _extract_case_metadata(desc) if (_is_case_type(doc_type) and desc is not None) else None,
        "body": {
            "wrapper":  wrapper_name,
            "sections": sections,
        },
        # edges.xrefs: a flat list of every <xref> seen in the document.
        # Consumed by src.relationship_extractor to build the knowledge graph.
        "edges": {
            "xrefs": _extract_xrefs(inner, doc_type),
        },
    }
    return out


def parse_directory(xml_dir: Path) -> list[dict]:
    docs: list[dict] = []
    for xml_file in sorted(xml_dir.glob("*.xml")):
        result = parse_file(xml_file)
        if result is not None:
            docs.append(result)
    return docs


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="KLI KEA-BASIC XML -> RAG-ready JSON")
    ap.add_argument("xml_dir", type=Path, help="Directory of XML files to parse")
    ap.add_argument("--out", type=Path, default=Path("parsed_docs.json"),
                    help="Output JSON path (default: parsed_docs.json in CWD)")
    args = ap.parse_args()

    # UTF-8 stdout on Windows consoles that otherwise default to cp1252.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not args.xml_dir.is_dir():
        print(f"[error] {args.xml_dir} is not a directory", file=sys.stderr)
        return 2

    docs = parse_directory(args.xml_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(docs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Small human-readable summary so you can sanity-check the run.
    by_type: dict[str, int] = {}
    for d in docs:
        by_type[d["doc_type"]] = by_type.get(d["doc_type"], 0) + 1
    print(f"Parsed {len(docs)} documents -> {args.out}")
    print(f"  by type: {by_type}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
