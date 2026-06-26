"""
EDA over a parsed KA corpus.

Produces coverage statistics, keyword/topic distributions, author graphs, and
a cross-reference graph — framed against the four business requirements:

  1. Blog -> paid-content bridging   (needs: keyword vocabulary, topic index)
  2. Enrich KA/KCL/KIPL with new tags (needs: coverage gaps to quantify)
  3. Keyword/topic dictionary + relations (needs: xref graph, co-occurrence)
  4. Enrich ingested primary content (awards, case decisions) (needs: schema
     map to know which fields are populated today vs. what NLP must fill)
"""
from __future__ import annotations

import pandas as pd
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .parser import Document, parse_directory


# ---------- flatten ----------

def documents_to_df(docs: Iterable[Document]) -> pd.DataFrame:
    rows = []
    for d in docs:
        rows.append({
            "file": Path(d.file_path).name,
            "doc_id": d.doc_id,
            "doc_type": d.doc_type,
            "essay_type": d.essay_type,
            "lang": d.lang,
            "title": d.title,
            "container_title": d.container_title,
            "publ_year": d.publ_year,
            "publisher": d.publisher,
            "n_authors": len(d.authors),
            "n_editors": len(d.editors),
            "cust_groups": tuple(d.cust_groups),
            "n_topics": len(d.topics),
            "n_keywords": len(d.keywords),
            "n_countries": len(d.countries),
            "n_orgs": len(d.organizations),
            "topics": tuple(d.topics),
            "keywords": tuple(d.keywords),
            "countries": tuple(d.countries),
            "organizations": tuple(d.organizations),
            "n_sections": len(d.sections),
            "n_xrefs": len(d.xrefs),
            "word_count": d.word_count,
            "isbn": d.isbn,
            "issn": d.issn,
            "pages_start": d.page_first,
            "pages_end": d.page_last,
            "supplement": d.supplement,
            "updated": d.updated,
        })
    return pd.DataFrame(rows)


# ---------- coverage (req #2 & #4) ----------

@dataclass
class CoverageReport:
    total_docs: int
    by_doc_type: dict
    pct_with_topic: float
    pct_with_keywords: float
    pct_with_country: float
    pct_with_org: float
    pct_with_isbn_or_issn: float
    empty_body_docs: list[str]   # docs with 0 sections or 0 words
    topic_coverage_by_type: dict
    keyword_coverage_by_type: dict


def coverage_report(df: pd.DataFrame) -> CoverageReport:
    total = len(df)
    if total == 0:
        return CoverageReport(0, {}, 0, 0, 0, 0, 0, [], {}, {})

    has_topic = df["n_topics"] > 0
    has_kw = df["n_keywords"] > 0
    has_country = df["n_countries"] > 0
    has_org = df["n_orgs"] > 0
    has_id = df["isbn"].notna() | df["issn"].notna()
    empty_body = df[(df["n_sections"] == 0) | (df["word_count"] == 0)]

    def pct_by_type(mask: pd.Series) -> dict:
        out = {}
        for t, sub in df.groupby("doc_type"):
            m = mask.loc[sub.index]
            out[t] = {"with": int(m.sum()), "total": int(len(sub)),
                      "pct": round(100 * m.sum() / max(len(sub), 1), 1)}
        return out

    return CoverageReport(
        total_docs=total,
        by_doc_type=df["doc_type"].value_counts().to_dict(),
        pct_with_topic=round(100 * has_topic.mean(), 1),
        pct_with_keywords=round(100 * has_kw.mean(), 1),
        pct_with_country=round(100 * has_country.mean(), 1),
        pct_with_org=round(100 * has_org.mean(), 1),
        pct_with_isbn_or_issn=round(100 * has_id.mean(), 1),
        empty_body_docs=empty_body["file"].tolist(),
        topic_coverage_by_type=pct_by_type(has_topic),
        keyword_coverage_by_type=pct_by_type(has_kw),
    )


# ---------- vocabularies (req #1 & #3) ----------

def keyword_vocabulary(docs: Iterable[Document]) -> Counter:
    c: Counter = Counter()
    for d in docs:
        for kw in d.keywords:
            c[kw.strip()] += 1
    return c


def topic_vocabulary(docs: Iterable[Document]) -> Counter:
    c: Counter = Counter()
    for d in docs:
        for t in d.topics:
            c[t.strip()] += 1
    return c


def organization_vocabulary(docs: Iterable[Document]) -> Counter:
    c: Counter = Counter()
    for d in docs:
        for o in d.organizations:
            c[o.strip()] += 1
    return c


def keyword_cooccurrence(docs: Iterable[Document]) -> Counter:
    """Unordered pairs of keywords that appear in the same document.

    Useful for req #3: seeding the topic/keyword relationship dictionary.
    """
    pairs: Counter = Counter()
    for d in docs:
        kws = sorted({k.strip() for k in d.keywords if k.strip()})
        for i in range(len(kws)):
            for j in range(i + 1, len(kws)):
                pairs[(kws[i], kws[j])] += 1
    return pairs


# ---------- cross-reference graph (req #3) ----------

def xref_edges(docs: Iterable[Document]) -> pd.DataFrame:
    """Internal KLI xrefs only (drop mailto/http).

    Each row is source_doc_id -> target_id. When a target id matches a
    known doc_id in the corpus we can flag it as resolved, which is the
    foundation for building a content-relationship graph.
    """
    known_ids = {d.doc_id for d in docs if d.doc_id}
    rows = []
    for d in docs:
        for x in d.xrefs:
            if x.type == "url":
                continue
            tgt = x.target
            if tgt and tgt.startswith(("mailto:", "http://", "https://")):
                continue
            rows.append({
                "source": d.doc_id,
                "target": tgt,
                "edge_type": x.type or "ref",
                "text": (x.text or "")[:100],
                "resolved": tgt in known_ids,
            })
    return pd.DataFrame(rows)


# ---------- author / editor network ----------

def author_stats(docs: Iterable[Document]) -> pd.DataFrame:
    counts: Counter = Counter()
    for d in docs:
        for a in d.authors:
            counts[a] += 1
    return pd.DataFrame(counts.most_common(), columns=["author", "n_docs"])


# ---------- text length (req #4: chunking planning) ----------

def length_stats(df: pd.DataFrame) -> dict:
    body = df[df["word_count"] > 0]["word_count"]
    if body.empty:
        return {}
    return {
        "n_with_body": int(len(body)),
        "min": int(body.min()),
        "p25": int(body.quantile(0.25)),
        "median": int(body.median()),
        "p75": int(body.quantile(0.75)),
        "max": int(body.max()),
        "mean": round(float(body.mean()), 1),
    }


# ---------- one-shot driver ----------

def run_eda(xml_dir: str | Path) -> dict:
    docs = list(parse_directory(xml_dir))
    df = documents_to_df(docs)
    return {
        "documents": docs,
        "df": df,
        "coverage": coverage_report(df),
        "keyword_vocab": keyword_vocabulary(docs),
        "topic_vocab": topic_vocabulary(docs),
        "org_vocab": organization_vocabulary(docs),
        "keyword_cooccurrence": keyword_cooccurrence(docs),
        "xrefs": xref_edges(docs),
        "authors": author_stats(docs),
        "length_stats": length_stats(df),
    }
