"""Ingestion helpers used at upload time.

- Format detection from the file extension.
- XML domain auto-detection: reuse the pipeline's `preprocess()` to strip the
  legacy commented-out frontmatter (which can carry a stale <cust-group>), then
  read the live cust-group values. KA / KCL -> domain; anything else -> ambiguous.
- PDF/DOC text preview (best-effort; guarded imports so the API runs without the
  optional extraction libs installed).
"""
from __future__ import annotations

import re
from pathlib import Path

from .config import PREVIEW_CHARS
from .schemas import Domain, FileFormat

# Reuse the pipeline's landmine-stripping pre-processor when available.
try:  # pragma: no cover - import shim
    from src.rag_parser import preprocess as _preprocess
except Exception:  # pragma: no cover
    _preprocess = None

_EXT_FORMAT = {
    ".xml": FileFormat.xml,
    ".pdf": FileFormat.pdf,
    ".doc": FileFormat.docx,   # legacy binary; preview best-effort
    ".docx": FileFormat.docx,
}

_CUST_GROUP_RE = re.compile(rb'cust-group\s+value="([^"]+)"', re.IGNORECASE)
_KNOWN_DOMAINS = {"KA", "KCL"}


def detect_format(ext: str) -> FileFormat | None:
    return _EXT_FORMAT.get(ext.lower())


def detect_domain_xml(raw: bytes) -> Domain | None:
    """Return KA/KCL when exactly one known domain is declared, else None.

    None means "ambiguous / not found" -> the UI will ask the user to choose,
    same as it does for PDF/DOC.
    """
    data = raw
    if _preprocess is not None:
        try:
            data = _preprocess(raw)
        except Exception:
            data = raw
    found = {
        m.decode("ascii", "ignore").upper()
        for m in _CUST_GROUP_RE.findall(data)
    } & _KNOWN_DOMAINS
    if len(found) == 1:
        return Domain(next(iter(found)))
    return None


def _clean(text: str) -> str | None:
    text = " ".join(text.split())
    if not text:
        return None
    return text[:PREVIEW_CHARS] + "…" if len(text) > PREVIEW_CHARS else text


def extract_preview(fmt: FileFormat, path: Path) -> str | None:
    """First few hundred chars of body text for the Confirm screen. Returns
    None if the format is unsupported or the optional lib is missing."""
    try:
        if fmt is FileFormat.pdf:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            buf = ""
            for page in reader.pages:
                buf += page.extract_text() or ""
                if len(buf) >= PREVIEW_CHARS:
                    break
            return _clean(buf)

        if fmt is FileFormat.docx:
            import docx  # python-docx

            document = docx.Document(str(path))
            buf = ""
            for para in document.paragraphs:
                if para.text:
                    buf += para.text + " "
                if len(buf) >= PREVIEW_CHARS:
                    break
            return _clean(buf)
    except Exception:
        return None
    return None
