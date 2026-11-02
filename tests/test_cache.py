from app.cache import TTLCache


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_second_call_is_a_hit_and_does_not_recompute():
    calls = []
    cache = TTLCache(60)
    compute = lambda: calls.append(1) or "v"  # noqa: E731
    assert cache.get_or_compute("k", compute) == ("v", False)
    assert cache.get_or_compute("k", compute) == ("v", True)
    assert len(calls) == 1
    assert (cache.hits, cache.misses) == (1, 1)


def test_entries_expire_after_ttl():
    clock = Clock()
    cache = TTLCache(10, clock=clock)
    cache.get_or_compute("k", lambda: 1)
    clock.now = 9.9
    assert cache.get_or_compute("k", lambda: 2) == (1, True)
    clock.now = 10.1
    assert cache.get_or_compute("k", lambda: 2) == (2, False)


def test_invalidate_clears_everything():
    cache = TTLCache(60)
    cache.get_or_compute("a", lambda: 1)
    cache.get_or_compute("b", lambda: 2)
    cache.invalidate()
    assert len(cache) == 0
    assert cache.get_or_compute("a", lambda: 3) == (3, False)


def test_write_during_compute_does_not_store_stale_value():
    cache = TTLCache(60)

    def slow_compute():
        cache.invalidate()  # a write lands while we are computing
        return "stale"

    assert cache.get_or_compute("k", slow_compute) == ("stale", False)
    assert len(cache) == 0
    assert cache.get_or_compute("k", lambda: "fresh") == ("fresh", False)


def test_bounded_size_evicts_least_recently_used():
    cache = TTLCache(60, max_entries=2)
    cache.get_or_compute("a", lambda: 1)
    cache.get_or_compute("b", lambda: 2)
    cache.get_or_compute("a", lambda: 1)  # touch a
    cache.get_or_compute("c", lambda: 3)  # evicts b
    assert cache.get_or_compute("a", lambda: 99)[1] is True
    assert cache.get_or_compute("b", lambda: 99)[1] is False


def test_zero_ttl_disables_caching():
    cache = TTLCache(0)
    assert cache.get_or_compute("k", lambda: 1) == (1, False)
    assert cache.get_or_compute("k", lambda: 2) == (2, False)
