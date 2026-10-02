"""Build the adapters selected by the settings (lite vs full mode)."""

from tripwire.adapters.memory_queue import MemoryQueue
from tripwire.adapters.sql_store import SqlStore
from tripwire.ports import Queue, Store
from tripwire.settings import Settings


def build_store(settings: Settings) -> Store:
    store = SqlStore(settings.database_url)
    store.init()
    return store


def build_queue(settings: Settings) -> Queue:
    if settings.queue == "memory":
        return MemoryQueue()
    raise NotImplementedError("Redis Streams adapter arrives with full mode (Part 1c)")
