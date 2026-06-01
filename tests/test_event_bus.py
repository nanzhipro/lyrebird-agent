"""EventBus — the observability fact bus.

Tests cover: emit, subscribe/unsubscribe, monotonic seq, snapshot, terminality.
"""
import queue as queue_lib

import pytest

from lyrebird.observability import Event, EventBus, EventType


def test_emit_assigns_monotonic_seq():
    bus = EventBus(run_id="r1")
    e1 = bus.emit(EventType.STAGE_STARTED, stage="intake")
    e2 = bus.emit(EventType.STAGE_COMPLETED, stage="intake")
    assert e1.seq == 1
    assert e2.seq == 2


def test_emit_attaches_run_id_and_timestamp():
    bus = EventBus(run_id="r1")
    e = bus.emit(EventType.LOG, message="hello")
    assert e.run_id == "r1"
    assert e.type == EventType.LOG
    assert e.payload == {"message": "hello"}
    assert e.timestamp  # ISO8601


def test_subscriber_receives_emitted_events():
    bus = EventBus(run_id="r1")
    q = bus.subscribe()
    e = bus.emit(EventType.STAGE_STARTED, stage="intake")
    received = q.get(timeout=1)
    assert received.seq == e.seq
    assert received.type == EventType.STAGE_STARTED


def test_multiple_subscribers_each_get_a_copy():
    bus = EventBus(run_id="r1")
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.emit(EventType.LOG, message="x")
    assert q1.get(timeout=1).payload == {"message": "x"}
    assert q2.get(timeout=1).payload == {"message": "x"}


def test_unsubscribe_stops_delivery():
    bus = EventBus(run_id="r1")
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.emit(EventType.LOG, message="x")
    with pytest.raises(queue_lib.Empty):
        q.get(timeout=0.1)


def test_late_subscriber_can_still_get_snapshot():
    """SSE clients reconnect mid-run — they must be able to catch up."""
    bus = EventBus(run_id="r1")
    bus.emit(EventType.STAGE_STARTED, stage="intake")
    bus.emit(EventType.STAGE_COMPLETED, stage="intake")
    bus.emit(EventType.STAGE_STARTED, stage="interview")

    snap = bus.snapshot()
    assert len(snap) == 3
    assert [e.seq for e in snap] == [1, 2, 3]


def test_snapshot_after_seq_filters():
    bus = EventBus(run_id="r1")
    bus.emit(EventType.LOG, message="a")
    bus.emit(EventType.LOG, message="b")
    bus.emit(EventType.LOG, message="c")

    later = bus.snapshot(after_seq=1)
    assert [e.payload["message"] for e in later] == ["b", "c"]


def test_terminal_states_detected():
    bus = EventBus(run_id="r1")
    assert not bus.is_terminal()
    bus.emit(EventType.STAGE_STARTED, stage="intake")
    assert not bus.is_terminal()
    bus.emit(EventType.RUN_COMPLETED, summary={})
    assert bus.is_terminal()


def test_terminal_on_run_failed():
    bus = EventBus(run_id="r1")
    bus.emit(EventType.RUN_FAILED, error="x")
    assert bus.is_terminal()


def test_event_serializes_for_sse():
    e = Event(
        seq=42, run_id="r1", timestamp="2026-05-17T10:00:00Z",
        type=EventType.AGENT_STARTED, payload={"agent": "intake"},
    )
    d = e.to_dict()
    assert d["seq"] == 42
    assert d["type"] == "agent.started"
    assert d["payload"]["agent"] == "intake"


def test_event_bus_thread_safe_emit_and_drain():
    import threading
    bus = EventBus(run_id="r1")
    q = bus.subscribe()
    n_events = 100

    def producer():
        for i in range(n_events):
            bus.emit(EventType.LOG, message=f"e{i}")

    t = threading.Thread(target=producer)
    t.start()
    t.join()

    drained = []
    while True:
        try:
            drained.append(q.get_nowait())
        except queue_lib.Empty:
            break
    assert len(drained) == n_events
    assert [e.seq for e in drained] == list(range(1, n_events + 1))
