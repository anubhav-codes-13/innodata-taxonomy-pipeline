"""Processing kickoff + live status stream.

    POST /api/process     start the parse -> chunk pipeline over a file set
    GET  /api/events      Server-Sent Events: one frame per status change

The POST returns immediately after scheduling background work; clients watch
progress on the SSE stream. The stream sends a snapshot of every file's
current status on connect (so a late/reconnecting subscriber catches up),
then one frame per subsequent transition, with periodic keepalive comments.
"""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import store
from ..events import bus
from ..pipeline import run_batch
from ..schemas import ProcessRequest, ProcessResponse

router = APIRouter(tags=["process"])

_HEARTBEAT_SECONDS = 15.0

# asyncio keeps only weak references to bare tasks; hold strong refs here so an
# in-flight pipeline run isn't garbage-collected mid-batch.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


@router.post("/process", response_model=ProcessResponse)
async def start_processing(body: ProcessRequest) -> ProcessResponse:
    if body.file_ids:
        file_ids = body.file_ids
    else:
        file_ids = [f.id for f in store.list_files() if f.status.value == "pending"]

    task = asyncio.create_task(run_batch(file_ids))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    return ProcessResponse(batch_id=uuid4().hex, file_ids=file_ids)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    queue = bus.subscribe()

    async def stream():
        try:
            # Snapshot first: reflect current reality for late subscribers.
            for rec in store.list_files():
                yield _sse({
                    "id": rec.id,
                    "status": rec.status.value,
                    "chunk_count": rec.chunk_count,
                    "error": rec.error,
                })
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=_HEARTBEAT_SECONDS
                    )
                    yield _sse(event)
                except asyncio.TimeoutError:
                    # Comment frame — keeps the connection warm through idle.
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering if present
        },
    )
