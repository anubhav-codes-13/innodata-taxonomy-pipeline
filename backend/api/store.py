"""SQLite-backed metadata store for uploaded files.

Binary files live on disk under UPLOAD_DIR; this index holds their metadata
plus the on-disk `stored_path`. Stdlib `sqlite3` only — no ORM dependency.
A connection is opened per operation (SQLite handles this fine for local use).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_PATH
from .schemas import FileRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id            TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    size          INTEGER NOT NULL,
    format        TEXT NOT NULL,
    content_type  TEXT,
    domain        TEXT,
    needs_domain  INTEGER NOT NULL,
    status        TEXT NOT NULL,
    text_preview  TEXT,
    domain_source TEXT,
    created_at    TEXT NOT NULL,
    chunk_count   INTEGER,
    error         TEXT
);
"""

# Columns added after the table's first release. init_db backfills any that
# are missing so an existing insight_engine.db upgrades in place (SQLite has
# no "ADD COLUMN IF NOT EXISTS").
_ADDED_COLUMNS = {
    "chunk_count": "INTEGER",
    "error": "TEXT",
}

# One row per (document, keyword). Cross-document keyword frequency is then
# COUNT(*) per keyword. A mapping table (rather than a raw counter) keeps the
# frequency correct when a document is reprocessed or deleted.
_KEYWORDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS document_keywords (
    file_id  TEXT NOT NULL,
    keyword  TEXT NOT NULL,
    domain   TEXT,
    PRIMARY KEY (file_id, keyword)
);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.execute(_SCHEMA)
        existing = {row["name"] for row in c.execute("PRAGMA table_info(files)")}
        for name, decl in _ADDED_COLUMNS.items():
            if name not in existing:
                c.execute(f"ALTER TABLE files ADD COLUMN {name} {decl}")
        c.execute(_KEYWORDS_SCHEMA)
        c.execute("CREATE INDEX IF NOT EXISTS idx_dk_keyword ON document_keywords(keyword)")


def _to_record(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        id=row["id"],
        filename=row["filename"],
        size=row["size"],
        format=row["format"],
        content_type=row["content_type"],
        domain=row["domain"],
        needs_domain=bool(row["needs_domain"]),
        status=row["status"],
        text_preview=row["text_preview"],
        domain_source=row["domain_source"],
        created_at=row["created_at"],
        chunk_count=row["chunk_count"],
        error=row["error"],
    )


def insert_file(
    *,
    id: str,
    filename: str,
    stored_path: str,
    size: int,
    format: str,
    content_type: str | None,
    domain: str | None,
    needs_domain: bool,
    status: str,
    text_preview: str | None,
    domain_source: str | None,
    created_at: str,
) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO files
               (id, filename, stored_path, size, format, content_type, domain,
                needs_domain, status, text_preview, domain_source, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (id, filename, stored_path, size, format, content_type, domain,
             int(needs_domain), status, text_preview, domain_source, created_at),
        )


def get_file(file_id: str) -> FileRecord | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _to_record(row) if row else None


def list_files() -> list[FileRecord]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM files ORDER BY created_at DESC").fetchall()
    return [_to_record(r) for r in rows]


def get_stored_path(file_id: str) -> str | None:
    """On-disk path of the uploaded binary, or None if the id is unknown."""
    with _conn() as c:
        row = c.execute(
            "SELECT stored_path FROM files WHERE id = ?", (file_id,)
        ).fetchone()
    return row["stored_path"] if row else None


def set_status(
    file_id: str,
    status: str,
    *,
    chunk_count: int | None = None,
    error: str | None = None,
) -> bool:
    """Update a file's processing status (and optionally chunk_count/error).

    chunk_count/error are only written when provided, so a mid-pipeline
    transition (e.g. -> "chunking") doesn't clobber a previously set value.
    Returns False if the id is unknown.
    """
    sets = ["status = ?"]
    params: list = [status]
    if chunk_count is not None:
        sets.append("chunk_count = ?")
        params.append(chunk_count)
    if error is not None:
        sets.append("error = ?")
        params.append(error)
    params.append(file_id)
    with _conn() as c:
        cur = c.execute(
            f"UPDATE files SET {', '.join(sets)} WHERE id = ?", params
        )
        return cur.rowcount > 0


def set_domain(file_id: str, domain: str) -> bool:
    """Assign a domain manually; clears needs_domain. Returns False if missing."""
    with _conn() as c:
        cur = c.execute(
            "UPDATE files SET domain = ?, needs_domain = 0, domain_source = 'manual' "
            "WHERE id = ?",
            (domain, file_id),
        )
        return cur.rowcount > 0


def delete_file(file_id: str) -> str | None:
    """Delete the metadata row. Returns the on-disk path so the caller can
    remove the binary, or None if the id was unknown."""
    with _conn() as c:
        row = c.execute(
            "SELECT stored_path FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if row is None:
            return None
        c.execute("DELETE FROM files WHERE id = ?", (file_id,))
        return row["stored_path"]


# ---------------------------------------------------------------------------
# Cross-document keyword frequency
# ---------------------------------------------------------------------------

def set_document_keywords(file_id: str, keywords: list[str], domain: str | None) -> None:
    """Replace the keyword set recorded for a document (idempotent on reprocess).

    Keywords are stored per (file_id, keyword); cross-document frequency is then
    COUNT(*) per keyword. Replacing (delete-then-insert) keeps the frequency
    correct when a file is enriched more than once.
    """
    seen: set[str] = set()
    rows: list[tuple[str, str, str | None]] = []
    for kw in keywords:
        k = (kw or "").strip()
        key = k.casefold()
        if not k or key in seen:
            continue
        seen.add(key)
        rows.append((file_id, k, domain))
    with _conn() as c:
        c.execute("DELETE FROM document_keywords WHERE file_id = ?", (file_id,))
        if rows:
            c.executemany(
                "INSERT INTO document_keywords (file_id, keyword, domain) VALUES (?,?,?)",
                rows,
            )


def delete_document_keywords(file_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM document_keywords WHERE file_id = ?", (file_id,))


def keyworded_file_ids() -> set[str]:
    """File ids that already have keywords recorded — used to skip on backfill."""
    with _conn() as c:
        rows = c.execute("SELECT DISTINCT file_id FROM document_keywords").fetchall()
    return {r["file_id"] for r in rows}


def keyword_frequencies(
    domain: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Keyword → document-frequency, highest first.

    `domain` restricts to documents of that domain; `search` is a case-insensitive
    substring filter on the keyword.
    """
    where: list[str] = []
    params: list = []
    if domain:
        where.append("domain = ?")
        params.append(domain)
    if search:
        where.append("keyword LIKE ?")
        params.append(f"%{search}%")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = (
        f"SELECT keyword, COUNT(*) AS frequency FROM document_keywords {clause} "
        "GROUP BY keyword ORDER BY frequency DESC, keyword ASC LIMIT ?"
    )
    params.append(limit)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [{"keyword": r["keyword"], "frequency": r["frequency"]} for r in rows]
