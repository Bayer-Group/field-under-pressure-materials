"""Unit tests of the users (a login and a password): the helpers, the login lookup and the plan of the generated accounts. No database."""
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

from backend.app.core.security import hash_password  # noqa: E402
from backend.app.services import accounts as ac  # noqa: E402
from generate_user_accounts import external, plan_accounts  # noqa: E402


class Helpers(unittest.TestCase):
    def test_login(self):
        self.assertEqual(ac.normalize_login("  Jan.Kowalski "), "jan.kowalski")
        for good in ("jan", "jan.kowalski", "a1b", "x_y-z.9", "nowy.rolnik12", "a" * 30):
            self.assertTrue(ac.valid_login(good), good)
        for bad in ("", "ab", "a" * 31, ".jan", "-jan", "jan kowalski", "jan@example.com", "jan/kowalski", "łukasz", "farmer001 "[:0]):
            self.assertFalse(ac.valid_login(bad), bad)

    def test_registration_rules(self):
        self.assertIsNone(ac.validate_registration("Jan.Nowak", "abcd"))
        self.assertIn("login", ac.validate_registration("j", "abcd"))
        self.assertIn("password", ac.validate_registration("jan.nowak", "abc"))
        self.assertIn("password", ac.validate_registration("jan.nowak", "x" * 101))
        self.assertIsNone(ac.validate_registration("jan.nowak", "x" * 100))

    def test_owner_of_a_new_account(self):
        self.assertEqual(ac.owner_for("Jan.Kowalski"), "u-jan-kowalski")
        self.assertEqual(ac.owner_for("a_b.c"), "u-a-b-c")
        for login in ("jan.kowalski", "x_y-z", "abc"):
            o = ac.owner_for(login)
            self.assertTrue(o.startswith("u-") and not o.startswith(("sbx-", "farmer-")))

    def test_slugify_polish(self):
        self.assertEqual(ac.slugify("Józef Wiśniewski"), "jozef.wisniewski")
        self.assertEqual(ac.slugify("Łukasz Dąbrowski"), "lukasz.dabrowski")
        self.assertEqual(ac.slugify("Małgorzata Król"), "malgorzata.krol")
        self.assertEqual(ac.slugify("Nowy Rolnik 3", "-"), "nowy-rolnik-3")

    def test_password(self):
        pw = {ac.generate_password() for _ in range(200)}
        self.assertEqual(len(pw), 200)
        for p in pw:
            self.assertRegex(p, r"^[a-z2-9]{4}(-[a-z2-9]{4}){2}$")
            self.assertFalse(set(p) & set("01oli"))


class Plan(unittest.TestCase):
    def test_counts_and_roles(self):
        plan = plan_accounts(20, 2, 1, 1)
        self.assertEqual(len(plan), 23)
        self.assertEqual([p["role"] for p in plan].count("analyst"), 1)
        self.assertEqual(sum(1 for p in plan if p["farm"]), 20)
        self.assertIn("nowy.rolnik1", {p["login"] for p in plan})
        self.assertIn("analityk", {p["login"] for p in plan})

    def test_unique_valid_and_safe(self):
        plan = plan_accounts(60, 5, 3, 7)
        logins = [p["login"] for p in plan]
        owners = [p["owner_id"] for p in plan]
        self.assertEqual(len(set(logins)), len(logins))
        self.assertEqual(len(set(owners)), len(owners))
        for p in plan:
            self.assertTrue(ac.valid_login(p["login"]), p["login"])
            self.assertEqual(p["login"], ac.normalize_login(p["login"]))
            self.assertTrue(p["owner_id"].startswith("u-") and not p["owner_id"].startswith(("sbx-", "farmer-")), p["owner_id"])
            self.assertRegex(p["owner_id"], r"^[a-z0-9-]+$")

    def test_deterministic_for_a_seed_and_limited(self):
        self.assertEqual(plan_accounts(10, 1, 1, 3), plan_accounts(10, 1, 1, 3))
        self.assertNotEqual([p["login"] for p in plan_accounts(10, 0, 0, 3)], [p["login"] for p in plan_accounts(10, 0, 0, 4)])
        with self.assertRaises(SystemExit):
            plan_accounts(10000, 0, 0, 1)

    def test_ids_of_a_copy(self):
        self.assertEqual(external("farmer-001", "farmer-001-p1"), "p1")
        self.assertEqual(external("sbx-ab", "sbx-ab~field-1"), "field-1")
        self.assertEqual(external("sbx-ab", "sbx-ab-field-1"), "field-1")
        self.assertEqual(external("farmer-001", "other"), "other")


class FakeCon:
    """Answers the two lookups of authenticate from dictionaries (a stand-in for the database)."""

    def __init__(self, accounts, demo):
        self.accounts, self.demo, self.calls = accounts, demo, []

    def execute(self, sql, params):
        table = sql.split("FROM")[1].split()[0]
        self.calls.append(table)
        self._row = (self.accounts if table == "app.user_account" else self.demo).get(params[0])
        return self

    def fetchone(self):
        return self._row


class Authenticate(unittest.TestCase):
    PW = "kuxa-7mqe-9dwp"
    CON = FakeCon(
        {"anna.nowak": {"login": "anna.nowak", "password_hash": hash_password(PW), "owner_id": "u-anna-nowak", "role": "farmer",
                        "display_name": "Anna Nowak"}},
        {"farmer001": {"login": "farmer001", "password_hash": hash_password("demo001"), "owner_id": "farmer-001", "role": "farmer",
                       "display_name": "Farmer 001"}})

    def test_account_any_case(self):
        for ident in ("anna.nowak", " Anna.Nowak "):
            u = ac.authenticate(self.CON, ident, self.PW)
            self.assertEqual((u["kind"], u["id"], u["owner_id"], u["role"]), ("account", "anna.nowak", "u-anna-nowak", "farmer"))

    def test_example_farmer(self):
        u = ac.authenticate(self.CON, "farmer001", "demo001")
        self.assertEqual((u["kind"], u["id"], u["owner_id"]), ("example", "farmer001", "farmer-001"))

    def test_wrong_password_and_unknown_login_are_both_none(self):
        self.assertIsNone(ac.authenticate(self.CON, "anna.nowak", "wrong"))
        self.assertIsNone(ac.authenticate(self.CON, "nobody", self.PW))
        self.assertIsNone(ac.authenticate(self.CON, "farmer001", "wrong"))
        self.assertIsNone(ac.authenticate(self.CON, "farmer001", self.PW))
        self.assertIsNone(ac.authenticate(self.CON, "anna.nowak", "demo001"))       # one table's password does not open the other

    def test_accounts_are_asked_first_then_the_example_logins(self):
        con = FakeCon({}, {})
        ac.authenticate(con, "somebody", "p")
        self.assertEqual(con.calls, ["app.user_account", "app.demo_user"])
        con = FakeCon({"anna.nowak": {"login": "anna.nowak", "password_hash": hash_password("pw12"), "owner_id": "o", "role": "farmer",
                                      "display_name": None}}, {})
        ac.authenticate(con, "anna.nowak", "pw12")
        self.assertEqual(con.calls, ["app.user_account"])


if __name__ == "__main__":
    unittest.main()
