from datetime import UTC, datetime

import pytest

from tripwire.adapters.sql_store import SqlStore
from tripwire.models import RawDocument


@pytest.fixture
def store(tmp_path):
    s = SqlStore(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    s.init()
    return s


@pytest.fixture
def make_doc():
    def _make(**overrides):
        fields = {
            "source": "finnhub",
            "source_type": "news",
            "title": "Regional bank discloses liquidity shortfall",
            "url": "https://www.example.com/news/bank-liquidity?utm_source=feed",
            "published_at": datetime(2026, 10, 1, 9, 14, tzinfo=UTC),
        }
        fields.update(overrides)
        return RawDocument(**fields)

    return _make
