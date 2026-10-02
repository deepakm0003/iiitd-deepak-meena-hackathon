from tripwire.adapters.memory_queue import MemoryQueue


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make_queue():
    clock = FakeClock()
    return MemoryQueue(visibility_timeout=10, max_attempts=3, clock=clock), clock


def test_ack_removes_message():
    q, _ = make_queue()
    q.publish("docs.raw", {"n": 1})
    [msg] = q.consume("docs.raw", "nlp", "w1")
    assert msg.attempts == 1
    q.ack("docs.raw", "nlp", msg.id)
    assert q.consume("docs.raw", "nlp", "w1") == []
    assert q.health()["pending"] == 0


def test_consumers_in_a_group_share_work_without_duplicates():
    q, _ = make_queue()
    for i in range(4):
        q.publish("docs.raw", {"n": i})
    a = q.consume("docs.raw", "nlp", "w1", count=2)
    b = q.consume("docs.raw", "nlp", "w2", count=2)
    assert {m.data["n"] for m in a} | {m.data["n"] for m in b} == {0, 1, 2, 3}
    assert not {m.id for m in a} & {m.id for m in b}


def test_separate_groups_each_get_every_message():
    q, _ = make_queue()
    q.publish("signals.out", {"n": 1})
    assert len(q.consume("signals.out", "module_b", "w")) == 1
    assert len(q.consume("signals.out", "dashboard", "w")) == 1


def test_unacked_message_is_redelivered_after_visibility_timeout():
    q, clock = make_queue()
    q.publish("docs.raw", {"n": 1})
    [first] = q.consume("docs.raw", "nlp", "w1")
    assert q.consume("docs.raw", "nlp", "w2") == []  # still invisible
    clock.now = 11
    [again] = q.consume("docs.raw", "nlp", "w2")  # worker w1 "crashed"
    assert again.id == first.id and again.attempts == 2


def test_nack_retries_then_dead_letters_after_max_attempts():
    q, _ = make_queue()
    q.publish("docs.raw", {"n": 1})
    for attempt in (1, 2, 3):
        [msg] = q.consume("docs.raw", "nlp", "w1")
        assert msg.attempts == attempt
        q.nack("docs.raw", "nlp", msg.id, error=f"boom {attempt}")
    assert q.consume("docs.raw", "nlp", "w1") == []
    [dead] = q.dead_letters("docs.raw")
    assert dead.data["n"] == 1 and dead.data["_error"] == "boom 3"
    assert q.health()["dead_letters"] == 1
