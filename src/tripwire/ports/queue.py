from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Message:
    id: str
    stream: str
    data: dict[str, Any]
    attempts: int


class Queue(Protocol):
    """At-least-once message queue with consumer groups, modelled on Redis Streams.

    A consumed message stays pending until acked. Pending messages idle longer than the visibility
    timeout are redelivered. After max_attempts failed deliveries a message moves to '<stream>.dlq'.
    Consumers must therefore be idempotent (the store's dedup key makes inserts safe to repeat).
    """

    def publish(self, stream: str, data: dict[str, Any]) -> str: ...

    def consume(self, stream: str, group: str, consumer: str, count: int = 10) -> list[Message]: ...

    def ack(self, stream: str, group: str, message_id: str) -> None: ...

    def nack(self, stream: str, group: str, message_id: str, error: str) -> None:
        """Report a failed attempt: retry later, or dead-letter after max_attempts."""

    def dead_letters(self, stream: str) -> list[Message]: ...

    def health(self) -> dict[str, Any]: ...
