"""In-process queue for lite mode, with the same delivery semantics as the Redis Streams adapter.

Per (stream, group) it keeps a read cursor and a pending list. Unacked messages idle longer than
`visibility_timeout` are redelivered with attempts + 1; after `max_attempts` they move to '<stream>.dlq'.
"""

import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tripwire.ports.queue import Message


@dataclass
class _Pending:
    message: Message
    consumer: str
    delivered_at: float


@dataclass
class _Group:
    cursor: int = 0
    pending: dict[str, _Pending] = field(default_factory=dict)


class MemoryQueue:
    def __init__(
        self,
        visibility_timeout: float = 30.0,
        max_attempts: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.visibility_timeout = visibility_timeout
        self.max_attempts = max_attempts
        self._clock = clock
        self._streams: dict[str, list[Message]] = {}
        self._groups: dict[tuple[str, str], _Group] = {}
        self._errors: dict[str, str] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def publish(self, stream: str, data: dict[str, Any]) -> str:
        with self._lock:
            return self._append(stream, data, attempts=0)

    def _append(self, stream: str, data: dict[str, Any], attempts: int) -> str:
        message_id = f"{next(self._ids)}-0"
        self._streams.setdefault(stream, []).append(Message(message_id, stream, dict(data), attempts))
        return message_id

    def consume(self, stream: str, group: str, consumer: str, count: int = 10) -> list[Message]:
        with self._lock:
            state = self._groups.setdefault((stream, group), _Group())
            now = self._clock()
            batch: list[Message] = []
            for message_id, pending in list(state.pending.items()):
                if len(batch) >= count:
                    break
                if now - pending.delivered_at >= self.visibility_timeout:
                    if pending.message.attempts >= self.max_attempts:
                        self._dead_letter(state, message_id, "visibility timeout after max attempts")
                        continue
                    batch.append(self._deliver(state, pending.message, consumer, now))
            entries = self._streams.get(stream, [])
            while len(batch) < count and state.cursor < len(entries):
                batch.append(self._deliver(state, entries[state.cursor], consumer, now))
                state.cursor += 1
            return batch

    def _deliver(self, state: _Group, message: Message, consumer: str, now: float) -> Message:
        delivered = Message(message.id, message.stream, message.data, message.attempts + 1)
        state.pending[message.id] = _Pending(delivered, consumer, now)
        return delivered

    def ack(self, stream: str, group: str, message_id: str) -> None:
        with self._lock:
            self._groups.setdefault((stream, group), _Group()).pending.pop(message_id, None)

    def nack(self, stream: str, group: str, message_id: str, error: str) -> None:
        with self._lock:
            state = self._groups.setdefault((stream, group), _Group())
            pending = state.pending.get(message_id)
            if pending is None:
                return
            if pending.message.attempts >= self.max_attempts:
                self._dead_letter(state, message_id, error)
            else:
                pending.delivered_at = float("-inf")  # eligible for immediate redelivery
                self._errors[message_id] = error

    def _dead_letter(self, state: _Group, message_id: str, error: str) -> None:
        pending = state.pending.pop(message_id)
        data = {**pending.message.data, "_error": error, "_original_id": message_id}
        self._append(f"{pending.message.stream}.dlq", data, attempts=pending.message.attempts)

    def dead_letters(self, stream: str) -> list[Message]:
        with self._lock:
            return list(self._streams.get(f"{stream}.dlq", []))

    def health(self) -> dict[str, Any]:
        with self._lock:
            pending = sum(len(g.pending) for g in self._groups.values())
            dlq = sum(len(v) for k, v in self._streams.items() if k.endswith(".dlq"))
        return {"ok": True, "backend": "memory", "pending": pending, "dead_letters": dlq}
