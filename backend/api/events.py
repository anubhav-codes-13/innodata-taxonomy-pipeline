"""In-process pub/sub for file-status events.

The pipeline publishes a small dict each time a file changes status; the SSE
endpoint (`GET /api/events`) holds one subscriber queue per connected client
and relays those dicts as `text/event-stream` frames.

This is deliberately in-memory and single-process — it matches the rest of the
local-device design (SQLite, on-disk uploads). If the API is ever scaled to
multiple workers, swap this for Redis pub/sub or similar without touching the
pipeline or the router (they only use publish() / subscribe()).

Thread-safety note: `publish()` uses `Queue.put_nowait`, which is only safe
when called from the event loop thread. The pipeline therefore publishes from
async context and offloads blocking work via `asyncio.to_thread`, so every
publish() call originates on the loop.
"""
from __future__ import annotations

import asyncio


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def publish(self, event: dict) -> None:
        """Fan `event` out to every current subscriber (non-blocking)."""
        for q in list(self._subscribers):
            q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        """Register a new subscriber and return its queue."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Module-level singleton shared by the pipeline and the SSE route.
bus = EventBus()
