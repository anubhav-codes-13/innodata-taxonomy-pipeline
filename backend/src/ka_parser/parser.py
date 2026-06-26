"""
KA (Kluwer Arbitration) XML parser.

Normalizes KEA-BASIC DTD documents (essay / legislation / booktoc) into a
uniform Document dataclass suitable for EDA, enrichment, and downstream
indexing.

Design notes:
- Uses stdlib xml.etree.ElementTree (no lxml dependency).
- Commented-out legacy <frontmatter> blocks are intentionally stripped before
  parsing, since they appear in many files as historical snapshots and would
  otherwise duplicate metadata (see e.g. KLI-KA-ICCA-HB-92-001-n.xml).
- Plain-text extraction preserves section boundaries but discards markup
  (xref targets are captured separately in Document.xrefs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


_COMMENT_RE = re.compile(rb"<!--.*?-->", re.DOTALL)
_WS_RE = re.compile(r"\s+")


@dataclass
class Section:
    id: str | None
    number: str | None
    title: str | None
    text: str
    word_count: int


@dataclass
class Xref:
    target: str
    type: str | None
    text: str


@dataclass
class Document:
    # identity
    file_path: str
    doc_id: str | None
    doc_type: str                      # essay | legislation | booktoc | unknown
    essay_type: str | None             # articles | monograph | None
    lang: str | None

    # frontmatter
    title: str | None = None
    short_title: str | None = None
    container_title: str | None = None        # journal/book this lives in
    authors: list[str] = field(default_factory=list)
    editors: list[str] = field(default_factory=list)
    publisher: str | None = None
    publ_date: str | None = None       # YYYYMMDD raw
    publ_year: int | None = None
    isbn: str | None = None
    issn: str | None = None
    volume: str | None = None
    issue: str | None = None
    supplement: str | None = None
    page_first: str | None = None
    page_last: str | None = None
    cust_groups: list[str] = field(default_factory=list)  # KA, IHB, CH, ...
    copyright: str | None = None
    updated: str | None = None

    # existing enrichment (the gap we care about for req #2 & #4)
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)

    # body
    sections: list[Section] = field(default_factory=list)
    plain_text: str = ""
    word_count: int = 0

    # graph edges
    xrefs: list[Xref] = field(default_factory=list)

    # toc-only
    toc_entries: list[dict] = field(default_factory=list)

    # commentary / case-note specific
    juris_parties: list[str] = field(default_factory=list)
    juris_court: str | None = None
    juris_date: str | None = None
    juris_case_name: str | None = None
    juris_case_number: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sections"] = [asdict(s) for s in self.sections]
        d["xrefs"] = [asdict(x) for x in self.xrefs]
        return d


# ---------- low-level helpers ----------

def _strip_comments(raw: bytes) -> bytes:
    """Remove XML comments.

    KA files routinely keep an older <frontmatter> version commented out
    alongside the current one. ET preserves nothing of comments, but stripping
    explicitly protects against malformed DOCTYPE/comment interactions and
    makes the parse deterministic.
    """
    return _COMMENT_RE.sub(b"", raw)


def _text(elem: ET.Element | None) -> str:
    """Recursive text extraction, whitespace-normalized."""
    if elem is None:
        return ""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_text(child))
        if child.tail:
            parts.append(child.tail)
    return _WS_RE.sub(" ", "".join(parts)).strip()


def _find_text(parent: ET.Element, path: str) -> str | None:
    found = parent.find(path)
    if found is None:
        return None
    t = _text(found)
    return t or None


def _attr(elem: ET.Element | None, name: str) -> str | None:
    if elem is None:
        return None
    v = elem.attrib.get(name)
    return v or None


def _name_text(name_elem: ET.Element) -> str:
    """<name>First<surname value="123">Last</surname></name> -> 'First Last'."""
    first = (name_elem.text or "").strip()
    surname = name_elem.find("surname")
    last = _text(surname) if surname is not None else ""
    full = f"{first} {last}".strip()
    return _WS_RE.sub(" ", full)


# ---------- section-level parsers ----------

def _parse_frontmatter(fm: ET.Element, doc: Document) -> None:
    doc.title = _find_text(fm, "title")

    for author in fm.findall("./authorgroup/author/name"):
        n = _name_text(author)
        if n:
            doc.authors.append(n)

    pub = fm.find("publication-info")
    if pub is not None:
        doc.container_title = _find_text(pub, "title")
        doc.short_title = _find_text(pub, "short-title")
        for editor in pub.findall("./authorgroup/editor/name"):
            n = _name_text(editor)
            if n:
                doc.editors.append(n)

        publisher = pub.find("./publisher/name")
        doc.publisher = _text(publisher) if publisher is not None else None

        pd = pub.find("publ-date")
        if pd is not None:
            doc.publ_date = pd.attrib.get("value")
            if doc.publ_date and doc.publ_date[:4].isdigit():
                doc.publ_year = int(doc.publ_date[:4])

        doc.isbn = _find_text(pub, "isbn")
        doc.issn = _find_text(pub, "issn")
        doc.volume = _find_text(pub, "edition/volume")
        doc.issue = _find_text(pub, "edition/issue")
        doc.supplement = _find_text(pub, "edition/supplement")

        rng = pub.find("range")
        if rng is not None:
            doc.page_first = rng.attrib.get("first") or None
            doc.page_last = rng.attrib.get("last") or None

        for cg in pub.findall("cust-group"):
            v = cg.attrib.get("value")
            if v:
                doc.cust_groups.append(v)

        doc.copyright = _find_text(pub, "copyright")
        upd = pub.find("updated")
        if upd is not None:
            doc.updated = upd.attrib.get("value")


def _parse_text_description(td: ET.Element, doc: Document) -> None:
    """<text-description> carries existing topics/keywords/scope."""
    for topic in td.findall("topic"):
        t = _text(topic)
        if t:
            doc.topics.append(t)
    for kw in td.findall("./keywords/keyword"):
        t = _text(kw)
        if t:
            doc.keywords.append(t)
    scope = td.find("text-scope")
    if scope is not None:
        for c in scope.findall("country"):
            t = _text(c) or c.attrib.get("value")
            if t:
                doc.countries.append(t)
        for o in scope.findall("organization"):
            t = _text(o)
            if t:
                doc.organizations.append(t)


def _parse_juris_description(jd: ET.Element, doc: Document) -> None:
    """Case-specific metadata living inside <juris-description>.

    Shape (from sampled commentaries):
      <juris-parties><juris-party>X</juris-party>...</juris-parties>
      <juris-court>...<organization/></juris-court>
      <juris-date value="YYYYMMDD"/>
      <juris-name>...</juris-name>
      <juris-number>...</juris-number>
    """
    for p in jd.findall("./juris-parties/juris-party"):
        t = _text(p)
        if t:
            doc.juris_parties.append(t)
    # Court identifier: commentary uses <juris-court>, caselaw uses <juris-authority>.
    # Either may wrap an <organization>, so fall back to the full text.
    doc.juris_court = (_find_text(jd, "juris-court")
                       or _find_text(jd, "juris-authority")
                       or None)
    jdate = jd.find("juris-date")
    if jdate is not None:
        doc.juris_date = jdate.attrib.get("value")
    doc.juris_case_name = _find_text(jd, "juris-name")
    doc.juris_case_number = _find_text(jd, "juris-number")


def _collect_xrefs(elem: ET.Element, doc: Document) -> None:
    for x in elem.iter("xref"):
        target = x.attrib.get("value")
        if not target:
            continue
        doc.xrefs.append(Xref(target=target, type=x.attrib.get("type"), text=_text(x)))


def _parse_sections(text_root: ET.Element, doc: Document) -> None:
    """Walk <section> elements (essay) or <legis-section> (legislation).

    We only take top-level sections; nested sections are collapsed into parent
    text to keep the section list tractable for EDA. For deep structural work
    (e.g. chunking for retrieval) a recursive variant would be appropriate.
    """
    tag_candidates = ("section", "legis-section")
    top_sections: list[ET.Element] = []
    for tag in tag_candidates:
        top_sections.extend([s for s in text_root.findall(tag)])

    if not top_sections:
        # fallback: body is a flat <p>-stream (some chapters have empty <text>)
        body_text = _text(text_root)
        if body_text:
            doc.sections.append(Section(id=None, number=None, title=None,
                                        text=body_text, word_count=len(body_text.split())))
        return

    for s in top_sections:
        sid = s.attrib.get("id")
        number = _find_text(s, "number")
        title = _find_text(s, "title")
        txt = _text(s)
        doc.sections.append(Section(id=sid, number=number, title=title,
                                    text=txt, word_count=len(txt.split())))


def _parse_booktoc(toc: ET.Element, doc: Document) -> None:
    for bsec in toc.findall("./booktoc-text/booktoc-section"):
        title_elem = bsec.find("booktoc-title")
        xref = title_elem.find("xref") if title_elem is not None else None
        entry = {
            "title": _text(title_elem) if title_elem is not None else None,
            "target": xref.attrib.get("value") if xref is not None else None,
            "authors": _text(bsec.find("p")) if bsec.find("p") is not None else None,
        }
        doc.toc_entries.append(entry)
        if entry["target"]:
            doc.xrefs.append(Xref(target=entry["target"], type="toc", text=entry["title"] or ""))


# ---------- top-level ----------

def parse_file(path: str | Path) -> Document:
    path = Path(path)
    raw = path.read_bytes()
    raw = _strip_comments(raw)

    # DOCTYPE may be simple (<!DOCTYPE ... "x.dtd">) or have an internal subset
    # declaring entities (<!DOCTYPE ... [ <!ENTITY ...> ... ]>). ET's default
    # parser rejects external entity references, so strip the whole DOCTYPE
    # including any internal subset.
    raw = re.sub(rb"<!DOCTYPE\s[^\[>]*(\[[^\]]*\])?\s*>", b"", raw, count=1, flags=re.DOTALL)

    root = ET.fromstring(raw)
    if root.tag == "KEA-publ" and len(root) >= 1:
        inner = root[0]
    else:
        inner = root

    doc_type_map = {
        "essay": "essay",
        "legislation": "legislation",
        "booktoc": "booktoc",
        "commentary": "commentary",
        "caselaw": "caselaw",
    }
    doc_type = doc_type_map.get(inner.tag, "unknown")

    doc = Document(
        file_path=str(path),
        doc_id=inner.attrib.get("id"),
        doc_type=doc_type,
        essay_type=inner.attrib.get("essay-type") or inner.attrib.get("commentary-type"),
        lang=inner.attrib.get("lang"),
    )

    fm = inner.find("frontmatter")
    if fm is not None:
        _parse_frontmatter(fm, doc)

    if doc_type == "essay":
        td = inner.find("text-description")
        if td is not None:
            _parse_text_description(td, doc)
        text_root = inner.find("text")
        if text_root is not None:
            _parse_sections(text_root, doc)
            _collect_xrefs(text_root, doc)
    elif doc_type == "commentary":
        # Two shapes observed:
        #   (a) case-note:  <commentary><frontmatter/><juris-comment>
        #                     <juris-description> (keywords, parties, court, date)
        #                     <section>... </juris-comment>
        #   (b) legis-note: <commentary><frontmatter/><legis-comment>
        #                     <legis-description> (topics, legis-name, ...)
        #                     <section>... </legis-comment>
        for wrapper_tag, desc_tag in (("juris-comment", "juris-description"),
                                      ("legis-comment", "legis-description")):
            wrapper = inner.find(wrapper_tag)
            if wrapper is None:
                continue
            desc = wrapper.find(desc_tag)
            if desc is not None:
                _parse_text_description(desc, doc)
                if desc_tag == "juris-description":
                    _parse_juris_description(desc, doc)
            _parse_sections(wrapper, doc)
            _collect_xrefs(wrapper, doc)
            break
    elif doc_type == "caselaw":
        # Structure: <caselaw><frontmatter/><juris juris-type="court-decision">
        #   <juris-description> (topic, keywords, parties, court, date, number, references)
        #   <juris-text><section>...
        # </juris></caselaw>
        juris = inner.find("juris")
        if juris is not None:
            jd = juris.find("juris-description")
            if jd is not None:
                _parse_text_description(jd, doc)
                _parse_juris_description(jd, doc)
            jt = juris.find("juris-text")
            if jt is not None:
                _parse_sections(jt, doc)
                _collect_xrefs(jt, doc)
    elif doc_type == "legislation":
        legis = inner.find("legis")
        if legis is not None:
            ld = legis.find("legis-description")
            if ld is not None:
                _parse_text_description(ld, doc)
            lt = legis.find("legis-text")
            if lt is not None:
                _parse_sections(lt, doc)
                _collect_xrefs(lt, doc)
    elif doc_type == "booktoc":
        _parse_booktoc(inner, doc)

    doc.plain_text = "\n\n".join(s.text for s in doc.sections if s.text)
    doc.word_count = sum(s.word_count for s in doc.sections)
    return doc


def parse_directory(dir_path: str | Path, pattern: str = "*.xml") -> Iterable[Document]:
    dir_path = Path(dir_path)
    for xml_file in sorted(dir_path.glob(pattern)):
        try:
            yield parse_file(xml_file)
        except ET.ParseError as e:
            # surface but don't abort a batch
            print(f"[parse-error] {xml_file.name}: {e}")
