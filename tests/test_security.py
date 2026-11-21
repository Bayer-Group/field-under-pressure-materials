"""Unit tests of backend/app/core/security.py (demo authentication, no database)."""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.app.core import security as sec  # noqa: E402

SECRET = "test-secret"


class Passwords(unittest.TestCase):
    def test_hash_and_verify(self):
        h = sec.hash_password("demo")
        self.assertTrue(h.startswith("scrypt$"))
        self.assertTrue(sec.verify_password("demo", h))
        self.assertFalse(sec.verify_password("Demo", h))

    def test_salt_differs(self):
        self.assertNotEqual(sec.hash_password("demo"), sec.hash_password("demo"))

    def test_malformed_hash_is_false(self):
        for bad in ("", "plain", "scrypt$1$2", "md5$1$2$3$4$5", "scrypt$x$y$z$a$b"):
            self.assertFalse(sec.verify_password("demo", bad))


class Tokens(unittest.TestCase):
    def test_roundtrip(self):
        t = sec.make_token({"sub": "farmer001", "owner_id": "farmer-001", "role": "farmer"}, SECRET, 60, now=1000)
        c = sec.read_token(t, SECRET, now=1030)
        self.assertEqual((c["sub"], c["owner_id"], c["role"], c["exp"]), ("farmer001", "farmer-001", "farmer", 1060))

    def test_expired(self):
        t = sec.make_token({"sub": "a"}, SECRET, 60, now=1000)
        self.assertIsNone(sec.read_token(t, SECRET, now=1061))

    def test_wrong_secret_and_tampering(self):
        t = sec.make_token({"sub": "a", "role": "farmer"}, SECRET, 60, now=1000)
        self.assertIsNone(sec.read_token(t, "other", now=1010))
        body, sig = t.split(".")
        forged = sec.make_token({"sub": "a", "role": "analyst"}, "guess", 60, now=1000).split(".")[0]
        self.assertIsNone(sec.read_token(f"{forged}.{sig}", SECRET, now=1010))     # new body, old signature

    def test_garbage(self):
        for bad in ("", "abc", "a.b.c", "....", "!!!.???"):
            self.assertIsNone(sec.read_token(bad, SECRET))


if __name__ == "__main__":
    unittest.main()
