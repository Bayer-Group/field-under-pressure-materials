"""Unit tests of backend/app/core/limits.py (rate limiter of the public demo)."""
import os
import sys
import unittest
from types import SimpleNamespace

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.core.limits import RateLimiter, client_ip  # noqa: E402


class Limiter(unittest.TestCase):
    def test_blocks_after_the_limit_and_recovers(self):
        rl = RateLimiter(3, 10)
        self.assertEqual([rl.allow("a", now=t) for t in (0, 1, 2, 3)], [True, True, True, False])
        self.assertTrue(rl.allow("a", now=10.5))                 # the oldest call left the window

    def test_keys_are_independent(self):
        rl = RateLimiter(1, 60)
        self.assertTrue(rl.allow("a", now=0))
        self.assertTrue(rl.allow("b", now=0))
        self.assertFalse(rl.allow("a", now=1))


class ClientIp(unittest.TestCase):
    def test_forwarded_for_and_peer(self):
        r = SimpleNamespace(headers={"x-forwarded-for": "203.0.113.7, 10.0.0.2"}, client=SimpleNamespace(host="172.18.0.3"))
        self.assertEqual(client_ip(r), "203.0.113.7")
        r = SimpleNamespace(headers={}, client=SimpleNamespace(host="172.18.0.3"))
        self.assertEqual(client_ip(r), "172.18.0.3")
        self.assertEqual(client_ip(SimpleNamespace(headers={}, client=None)), "unknown")


if __name__ == "__main__":
    unittest.main()
