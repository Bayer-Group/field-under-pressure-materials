#!/usr/bin/env python3
"""Create the demo user accounts (a login and a password) and give each farmer an own, editable farm. A mock for switching users.

    export LOAD_DB_DSN="postgresql://user:password@localhost:5433/dbname"      # the same variable as the loader
    python scripts/generate_user_accounts.py --farmers 20 --empty 2 --analysts 1

Needs migration 010 (app.user_account). What it creates:
* `--farmers N` accounts with Polish names (login jan.kowalski), each with a COPY of an example farm (the example farms are
  handed out in turn; the copy includes the parcels and the computed risk, and can be edited: it is not an example farm),
* `--empty M` accounts without any field (login nowy.rolnik1), to try creating the first field,
* `--analysts K` accounts with the analyst role (login analityk): sees everything, edits nothing.
Passwords are random by default (for example kuxa-7mqe-9dwp) or, with --password, ONE simple password for every account (for tests of
the front end: a mock, the same for everybody). They are stored only as scrypt hashes and written to a CSV file (--out, by default
data/_loader/user_accounts.csv, which git ignores). With random passwords the file is the only place that has them: give it to the team
through a private channel.

Safe to run again: an existing account keeps its password (unless --reset-passwords) and an account without fields gets its farm
back (the mock data generator deletes every mock farm, accounts included in that: run this script again after it).
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.core.security import hash_password  # noqa: E402
from backend.app.services.accounts import generate_password, slugify  # noqa: E402

MALE = ["Jan", "Piotr", "Krzysztof", "Andrzej", "Tomasz", "Paweł", "Michał", "Marcin", "Józef", "Stanisław", "Marek", "Grzegorz",
        "Łukasz", "Adam", "Zbigniew", "Rafał", "Wojciech", "Jacek", "Dariusz", "Mateusz"]
FEMALE = ["Anna", "Maria", "Katarzyna", "Małgorzata", "Agnieszka", "Barbara", "Ewa", "Krystyna", "Elżbieta", "Zofia", "Teresa",
          "Joanna", "Magdalena", "Monika", "Danuta", "Halina", "Irena", "Aleksandra", "Beata", "Dorota"]
SURNAMES = [("Kowalski", "Kowalska"), ("Nowak", "Nowak"), ("Wiśniewski", "Wiśniewska"), ("Wójcik", "Wójcik"),
            ("Kowalczyk", "Kowalczyk"), ("Kamiński", "Kamińska"), ("Lewandowski", "Lewandowska"), ("Zieliński", "Zielińska"),
            ("Szymański", "Szymańska"), ("Woźniak", "Woźniak"), ("Dąbrowski", "Dąbrowska"), ("Kozłowski", "Kozłowska"),
            ("Jankowski", "Jankowska"), ("Mazur", "Mazur"), ("Kwiatkowski", "Kwiatkowska"), ("Krawczyk", "Krawczyk"),
            ("Piotrowski", "Piotrowska"), ("Grabowski", "Grabowska"), ("Pawłowski", "Pawłowska"), ("Michalski", "Michalska"),
            ("Zając", "Zając"), ("Król", "Król"), ("Wieczorek", "Wieczorek"), ("Jabłoński", "Jabłońska"), ("Wróbel", "Wróbel")]


def plan_accounts(farmers: int, empty: int, analysts: int, seed: int) -> list[dict]:
    """The accounts to have: [{login, display_name, owner_id, role, farm}], deterministic for a seed; logins and owners are unique."""
    rnd = random.Random(seed)
    combos = [(f"{first} {sm if male else sf}") for male, firsts in ((True, MALE), (False, FEMALE))
              for first in firsts for sm, sf in SURNAMES]
    rnd.shuffle(combos)
    out, seen = [], set()

    def add(name: str, role: str, farm: bool, local: str | None = None) -> None:
        base = local or slugify(name)
        login, owner, n = base, f"u-{base.replace('.', '-')}", 1
        while login in seen:
            n += 1
            login, owner = f"{base}{n}", f"u-{base.replace('.', '-')}{n}"
        seen.add(login)
        out.append({"login": login, "display_name": name, "owner_id": owner, "role": role, "farm": farm})

    if farmers > len(combos):
        raise SystemExit(f"at most {len(combos)} named farmers")
    for name in combos[:farmers]:
        add(name, "farmer", True)
    for i in range(1, empty + 1):
        add(f"Nowy Rolnik {i}", "farmer", False, f"nowy.rolnik{i}")
    for i in range(1, analysts + 1):
        add("Analityk" if i == 1 else f"Analityk {i}", "analyst", False, "analityk" if i == 1 else f"analityk{i}")
    return out


def external(owner: str, stored: str) -> str:
    """The id without the owner prefix (the ids of the API are `<owner>~<id>`; a sandbox copy used `<owner>-<id>`)."""
    for prefix in (f"{owner}~", f"{owner}-"):
        if stored.startswith(prefix):
            return stored[len(prefix):]
    return stored


def _copy(cur, schema: str, table: str, key: str, old: list[str], new: list[str], extra: dict | None = None, join_field=None) -> int:
    """INSERT .. SELECT the rows of `table` whose `key` is in `old`, with the key replaced by the matching id of `new`."""
    from psycopg import sql
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                "AND (column_default IS NULL OR column_default NOT LIKE 'nextval%%') ORDER BY ordinal_position", (schema, table))
    cols = [r[0] for r in cur.fetchall()]
    extra = extra or {}
    exprs = []
    for c in cols:
        if c == key:
            exprs.append(sql.SQL("m.n"))
        elif join_field and c == join_field[0]:
            exprs.append(sql.SQL("fm.n"))
        elif c in extra:
            exprs.append(sql.SQL(extra[c]))
        else:
            exprs.append(sql.SQL("t.") + sql.Identifier(c))
    joins = sql.SQL("JOIN unnest(%(old)s::text[], %(new)s::text[]) AS m(o, n) ON t.") + sql.Identifier(key) + sql.SQL(" = m.o ")
    params = {"old": old, "new": new, "owner": extra.get("_owner")}
    if join_field:
        joins += sql.SQL("JOIN unnest(%(fold)s::text[], %(fnew)s::text[]) AS fm(o, n) ON t.") + sql.Identifier(join_field[0]) + sql.SQL(" = fm.o ")
        params.update({"fold": join_field[1], "fnew": join_field[2]})
    cur.execute(sql.SQL("INSERT INTO {t} ({c}) SELECT {e} FROM {t2} t ").format(
        t=sql.Identifier(schema, table), c=sql.SQL(", ").join(map(sql.Identifier, cols)), e=sql.SQL(", ").join(exprs),
        t2=sql.Identifier(schema, table)) + joins, params)
    return cur.rowcount


def clone_farm(cur, template: str, owner: str) -> tuple[int, int]:
    """Copy every field of the example farm `template` to `owner` (fields, parcels, crop areas, sprays and the computed context and
    risk); returns (fields, crop areas). The new ids are `<owner>~<id as the example farm has it>`."""
    cur.execute("SELECT field_id FROM app.field WHERE owner_id = %s ORDER BY field_id", (template,))
    f_old = [r[0] for r in cur.fetchall()]
    f_new = [f"{owner}~{external(template, f)}" for f in f_old]
    cur.execute("SELECT crop_area_id FROM app.crop_area WHERE field_id = ANY(%s) ORDER BY crop_area_id", (f_old,))
    a_old = [r[0] for r in cur.fetchall()]
    a_new = [f"{owner}~{external(template, a)}" for a in a_old]
    if not f_old:
        return 0, 0
    _copy(cur, "app", "field", "field_id", f_old, f_new,
          {"owner_id": "%(owner)s", "created_at": "now()", "updated_at": "now()", "_owner": owner})
    _copy(cur, "app", "field_parcel", "field_id", f_old, f_new)
    if a_old:
        _copy(cur, "app", "crop_area", "crop_area_id", a_old, a_new, join_field=("field_id", f_old, f_new))
        for schema, table in (("app", "spray"), ("curated", "crop_area_crop_map"), ("curated", "field_context"),
                              ("curated", "risk_assessment")):
            _copy(cur, schema, table, "crop_area_id", a_old, a_new)
    return len(f_old), len(a_old)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--farmers", type=int, default=20, help="accounts with an own copy of an example farm")
    ap.add_argument("--empty", type=int, default=2, help="accounts without any field")
    ap.add_argument("--analysts", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--password", help="one password for every account of this plan (default: a random one for each)")
    ap.add_argument("--reset-passwords", action="store_true", help="new passwords (random, or --password) for all the accounts of this plan")
    ap.add_argument("--no-farms", action="store_true", help="accounts only, no farm copies")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "_loader" / "user_accounts.csv", help="where the passwords are written")
    ap.add_argument("--dsn", help="connection string (default: env LOAD_DB_DSN)")
    a = ap.parse_args(argv)
    dsn = a.dsn or os.environ.get("LOAD_DB_DSN")
    if not dsn:
        sys.exit("no connection string: set env LOAD_DB_DSN or pass --dsn")
    import psycopg
    plan = plan_accounts(a.farmers, a.empty, a.analysts, a.seed)
    known: dict[str, dict] = {}
    if a.out.exists():
        with open(a.out, newline="", encoding="utf-8") as fh:
            known = {r["login"]: r for r in csv.DictReader(fh)}
    created = reset = cloned_accounts = 0
    rows = []
    with psycopg.connect(dsn) as con, con.cursor() as cur:
        cur.execute("SELECT to_regclass('app.user_account')")
        if cur.fetchone()[0] is None:
            sys.exit("app.user_account does not exist: apply docker/migrations/010_user_accounts.sql first")
        cur.execute("SELECT owner_id FROM app.user_account")
        account_owners = {r[0] for r in cur.fetchall()} | {p["owner_id"] for p in plan}
        cur.execute("SELECT DISTINCT owner_id FROM app.field WHERE data_status = 'mock' AND owner_id NOT LIKE 'sbx-%%' ORDER BY owner_id")
        templates = [r[0] for r in cur.fetchall() if r[0] not in account_owners]
        turn = 0
        for p in plan:
            cur.execute("SELECT 1 FROM app.user_account WHERE login = %s", (p["login"],))
            exists = cur.fetchone() is not None
            password = None
            if not exists or a.reset_passwords:
                password = a.password or generate_password()
                cur.execute(
                    "INSERT INTO app.user_account (login, password_hash, owner_id, role, display_name) VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (login) DO UPDATE SET password_hash = EXCLUDED.password_hash, display_name = EXCLUDED.display_name, "
                    "role = EXCLUDED.role", (p["login"], hash_password(password), p["owner_id"], p["role"], p["display_name"]))
                created += 0 if exists else 1
                reset += 1 if exists else 0
            else:
                cur.execute("UPDATE app.user_account SET display_name = %s, role = %s WHERE login = %s",
                            (p["display_name"], p["role"], p["login"]))
            farm = ""
            if p["farm"] and not a.no_farms:
                cur.execute("SELECT count(*) FROM app.field WHERE owner_id = %s", (p["owner_id"],))
                if cur.fetchone()[0] == 0:
                    if not templates:
                        print("WARNING: no example farm to copy; the account has no fields", file=sys.stderr)
                    else:
                        farm = templates[turn % len(templates)]
                        turn += 1
                        clone_farm(cur, farm, p["owner_id"])
                        cloned_accounts += 1
            cur.execute("SELECT count(*) FROM app.field WHERE owner_id = %s", (p["owner_id"],))
            fields = cur.fetchone()[0]
            old = known.get(p["login"], {})
            rows.append({"login": p["login"], "password": password or old.get("password", ""), "display_name": p["display_name"],
                         "owner_id": p["owner_id"], "role": p["role"], "farm_copied_from": farm or old.get("farm_copied_from", ""),
                         "fields": fields})
        con.commit()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    os.chmod(a.out, 0o600)
    missing = sum(1 for r in rows if not r["password"])
    print(f"accounts: {len(rows)} in the plan, {created} created, {reset} with a new password, {cloned_accounts} got a farm copy "
          f"({len(templates)} example farms to copy from)")
    print(f"passwords: {a.out} (mode 600, outside git)" + (f"; {missing} accounts keep a password that is not in the file "
                                                             "(use --reset-passwords)" if missing else ""))
    for r in rows[:3]:
        print(f"  e.g. login {r['login']} ({r['display_name']}, {r['role']}, {r['fields']} fields)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
