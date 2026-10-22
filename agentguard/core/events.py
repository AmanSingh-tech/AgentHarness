"""In-process event bus with SSE-friendly fan-out.

Synchronous subscribers (e.g. the store) are called inline, in publish order.
Async consumers (the SSE endpoint, milestone 8) get a bounded asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from typing import Callable

from agentguard.core.models import TraceEvent, TraceKind

Subscriber = Callable[[TraceEvent], None]
ALL = "*"


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Subscriber]] = defaultdict(list)
        self._queues: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, fn: Subscriber, run_id: str = ALL) -> Callable[[], None]:
        with self._lock:
            self._subs[run_id].append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._subs[run_id]:
                    self._subs[run_id].remove(fn)

        return unsubscribe

    def queue(self, run_id: str = ALL, maxsize: int = 1000) -> asyncio.Queue:
        """Must be called from inside a running event loop."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._queues[run_id].append((asyncio.get_running_loop(), q))
        return q

    def publish(self, event: TraceEvent) -> None:
        with self._lock:
            subs = list(self._subs[event.run_id]) + list(self._subs[ALL])
            queues = list(self._queues[event.run_id]) + list(self._queues[ALL])
        for fn in subs:
            fn(event)
        for loop, q in queues:
            loop.call_soon_threadsafe(_put_nowait_drop, q, event)


def _put_nowait_drop(q: asyncio.Queue, event: TraceEvent) -> None:
    # A slow SSE client must never block tool execution; it loses events instead.
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        pass


class Tracer:
    """Per-run event emitter that assigns a monotonically increasing seq."""

    def __init__(self, bus: EventBus, run_id: str) -> None:
        self.bus = bus
        self.run_id = run_id
        self._seq = 0
        self._lock = threading.Lock()

    def emit(self, kind: TraceKind, call_id: str | None = None, **payload) -> TraceEvent:
        with self._lock:
            self._seq += 1
            event = TraceEvent(run_id=self.run_id, seq=self._seq, kind=kind, call_id=call_id, payload=payload)
        self.bus.publish(event)
        return event
