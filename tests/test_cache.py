"""Unit tests of backend/app/core/cache.py (the cache with a time to live)."""
import os
import sys
import threading
import time
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.core.cache import TtlCache  # noqa: E402


class Ttl(unittest.TestCase):
    def test_hit_then_expiry(self):
        c = TtlCache(60)
        c.put("a", 1, now=100.0)
        self.assertEqual(c.get("a", now=159.9), 1)
        self.assertIsNone(c.get("a", now=160.0))                 # expired at the end of the time to live
        self.assertIsNone(c.get("a", now=161.0))
        self.assertEqual(len(c), 0)                              # the expired entry is gone

    def test_miss_and_overwrite_renews(self):
        c = TtlCache(10)
        self.assertIsNone(c.get("x", now=0))
        c.put("x", 1, now=0)
        c.put("x", 2, now=8)
        self.assertEqual(c.get("x", now=15), 2)                  # renewed by the second put

    def test_bounded_least_recently_used_goes_first(self):
        c = TtlCache(1000, max_items=3)
        for i, k in enumerate("abc"):
            c.put(k, i, now=0)
        c.get("a", now=1)                                         # a is now the most recently used
        c.put("d", 9, now=2)
        self.assertIsNone(c.get("b", now=3))                      # b was the least recently used
        self.assertEqual([c.get(k, now=3) for k in "acd"], [0, 2, 9])
        self.assertEqual(len(c), 3)

    def test_clear_and_none_values(self):
        c = TtlCache(10)
        c.put("k", b"bytes", now=0)
        c.clear()
        self.assertIsNone(c.get("k", now=1))


class SingleFlight(unittest.TestCase):
    def test_a_burst_of_misses_builds_once(self):
        c, calls, results = TtlCache(60), [], []

        def builder():
            calls.append(1)
            time.sleep(0.15)                                   # slow enough for all the threads to arrive
            return {"built": True}

        threads = [threading.Thread(target=lambda: results.append(c.get_or_build("k", builder))) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [{"built": True}] * 8)
        self.assertEqual(c.get_or_build("k", lambda: {"other": 1}), {"built": True})       # later calls hit the cache

    def test_none_and_exceptions_are_not_cached(self):
        c = TtlCache(60)
        self.assertIsNone(c.get_or_build("none", lambda: None))
        self.assertEqual(c.get_or_build("none", lambda: 5), 5)                              # tried again, not stuck on None

        def boom():
            raise ValueError("no")

        with self.assertRaises(ValueError):
            c.get_or_build("err", boom)
        self.assertEqual(c.get_or_build("err", lambda: 7), 7)                               # the lock is free again

    def test_different_keys_do_not_wait_for_each_other(self):
        c, started = TtlCache(60), []
        slow = threading.Thread(target=lambda: c.get_or_build("slow", lambda: (started.append(1), time.sleep(0.3), 1)[2]))
        slow.start()
        time.sleep(0.05)
        t0 = time.perf_counter()
        self.assertEqual(c.get_or_build("fast", lambda: 2), 2)
        self.assertLess(time.perf_counter() - t0, 0.2)
        slow.join()


if __name__ == "__main__":
    unittest.main()
