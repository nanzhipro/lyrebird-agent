"""Observability primitives — EventBus, Event, EventType.

This is the cross-cutting concern. Per memo/07:
- The bus is the *only* sanctioned channel for "what's happening right now"
- Agents and Pipeline emit through ctx.bus
- ctx.bus may be None — in which case all emits are no-ops, so unit tests
  and the CLI path don't need to change
- The bus is thread-safe: producers run in worker threads, consumers
  (SSE handlers) run on the FastAPI event loop
"""
from __future__ import annotations

import queue as queue_lib
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    ARTIFACT_WRITTEN = "artifact.written"
    GATE_EVALUATED = "gate.evaluated"
    LOG = "log"


_TERMINAL_TYPES = {EventType.RUN_COMPLETED, EventType.RUN_FAILED}


@dataclass
class Event:
    seq: int
    run_id: str
    timestamp: str   # ISO8601 UTC
    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "type": self.type.value,
            "payload": self.payload,
        }


class EventBus:
    """Thread-safe pub/sub bus for a single pipeline run."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._lock = threading.Lock()
        self._seq = 0
        self._history: List[Event] = []
        self._subscribers: List[queue_lib.Queue] = []
        self._terminal = False

    def emit(self, type: EventType, **payload: Any) -> Event:
        with self._lock:
            self._seq += 1
            ev = Event(
                seq=self._seq,
                run_id=self.run_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                type=type,
                payload=payload,
            )
            self._history.append(ev)
            if type in _TERMINAL_TYPES:
                self._terminal = True
            subs = list(self._subscribers)

        # Fan out without holding the lock — slow subscribers can't stall producers
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue_lib.Full:
                # Slow consumer; drop. SSE client can use snapshot to resync.
                pass
        return ev

    def subscribe(self, maxsize: int = 1024) -> queue_lib.Queue:
        q: queue_lib.Queue = queue_lib.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue_lib.Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def snapshot(self, *, after_seq: int = 0) -> List[Event]:
        with self._lock:
            return [e for e in self._history if e.seq > after_seq]

    def is_terminal(self) -> bool:
        with self._lock:
            return self._terminal
