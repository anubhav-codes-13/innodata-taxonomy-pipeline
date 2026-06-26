"""File upload + management endpoints.

    POST   /api/files          upload 1..N files to local storage
    GET    /api/files          list uploaded files (newest first)
    GET    /api/files/{id}     fetch one
    PATCH  /api/files/{id}     assign/correct domain (KA|KCL)
    DELETE /api/files/{id}     remove metadata + binary

Files are streamed to disk in chunks with a hard size cap (never buffered
whole in memory). XML domain is auto-detected; PDF/DOC get a text preview and
are flagged needs_domain=True for the Confirm screen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import store
from ..config import (
    CHUNK_DIR,
    ENRICHED_CHUNK_DIR,
    ENRICHED_DIR,
    MAX_FILE_SIZE,
    MAX_FILE_SIZE_MB,
    UPLOAD_DIR,
)
from ..ingest import detect_domain_xml, detect_format, extract_preview
from ..schemas import FileFormat, FileRecord, FileUpdate

router = APIRouter(tags=["files"])

_CHUNK = 1024 * 1024  # 1 MiB


async def _stream_to_disk(upload: UploadFile, dest: Path, max_size: int) -> int:
    """Write the upload to `dest` in chunks, enforcing `max_size`. Returns the
    byte count. Removes the partial file and raises 413 if the cap is exceeded."""
    size = 0
    with open(dest, "wb") as fh:
        while True:
            chunk = await upload.read(_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > max_size:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"{upload.filename}: exceeds {MAX_FILE_SIZE_MB} MB limit",
                )
            fh.write(chunk)
    return size


@router.post("/files", response_model=list[FileRecord], status_code=201)
async def upload_files(files: list[UploadFile] = File(...)) -> list[FileRecord]:
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    # Validate every extension up front so we don't half-save a mixed batch.
    parsed: list[tuple[UploadFile, str, FileFormat]] = []
    for up in files:
        ext = Path(up.filename or "").suffix.lower()
        fmt = detect_format(ext)
        if fmt is None:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type: {up.filename or '?'} "
                f"(allowed: xml, pdf, doc, docx)",
            )
        parsed.append((up, ext, fmt))

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    records: list[FileRecord] = []

    for up, ext, fmt in parsed:
        file_id = uuid4().hex
        dest = UPLOAD_DIR / f"{file_id}{ext}"
        size = await _stream_to_disk(up, dest, MAX_FILE_SIZE)
        if size == 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"{up.filename}: empty file")

        domain: str | None = None
        domain_source: str | None = None
        needs_domain = True
        preview: str | None = None

        if fmt is FileFormat.xml:
            detected = detect_domain_xml(dest.read_bytes())
            if detected is not None:
                domain = detected.value
                domain_source = "auto"
                needs_domain = False
        else:
            preview = extract_preview(fmt, dest)

        store.insert_file(
            id=file_id,
            filename=up.filename or f"{file_id}{ext}",
            stored_path=str(dest),
            size=size,
            format=fmt.value,
            content_type=up.content_type,
            domain=domain,
            needs_domain=needs_domain,
            status="pending",
            text_preview=preview,
            domain_source=domain_source,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        rec = store.get_file(file_id)
        assert rec is not None
        records.append(rec)

    return records


@router.get("/files", response_model=list[FileRecord])
def list_files() -> list[FileRecord]:
    return store.list_files()


@router.get("/files/{file_id}", response_model=FileRecord)
def get_file(file_id: str) -> FileRecord:
    rec = store.get_file(file_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="File not found")
    return rec


@router.patch("/files/{file_id}", response_model=FileRecord)
def update_file(file_id: str, body: FileUpdate) -> FileRecord:
    if not store.set_domain(file_id, body.domain.value):
        raise HTTPException(status_code=404, detail="File not found")
    rec = store.get_file(file_id)
    assert rec is not None
    return rec


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: str) -> None:
    path = store.delete_file(file_id)
    if path is None:
        raise HTTPException(status_code=404, detail="File not found")
    Path(path).unlink(missing_ok=True)
    store.delete_document_keywords(file_id)  # drop from keyword-frequency table
    # Remove derived artifacts so a deleted doc fully disappears from History.
    for d in (CHUNK_DIR, ENRICHED_CHUNK_DIR, ENRICHED_DIR):
        (d / f"{file_id}.json").unlink(missing_ok=True)
