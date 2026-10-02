def test_insert_is_idempotent(store, make_doc):
    doc = make_doc()
    assert store.add_raw(doc) is True
    assert store.add_raw(doc) is False
    # Same article via another feed, with tracking params and www: still a duplicate.
    assert store.add_raw(make_doc(source="gdelt", url="https://example.com/news/bank-liquidity")) is False
    assert store.count_raw() == 1


def test_count_by_source(store, make_doc):
    store.add_raw(make_doc())
    store.add_raw(make_doc(source="edgar", source_type="filing", url=None, external_id="acc-1"))
    assert store.count_raw("edgar") == 1
    assert store.count_raw() == 2


def test_health_reports_backend(store):
    health = store.health()
    assert health["ok"] is True
    assert health["backend"] == "sqlite"
