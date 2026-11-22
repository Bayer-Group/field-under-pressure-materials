"""
run_readonly_sql: free-form SELECTs for questions no typed tool covers (agent mode and MCP only).

Layers of protection (all must pass):
1. validation: exactly one statement, type SELECT (WITH … SELECT allowed), no forbidden keywords
   anywhere (also catches data-modifying CTEs, which sqlparse types as SELECT), no system
   schemas / pg_ functions, only allowlisted platform tables;
2. execution only through connections["readonly"] (a SELECT-only role, to be provided by the
   platform), inside a READ ONLY transaction with SET LOCAL statement_timeout, rolled back;
3. row cap: the query is wrapped as SELECT * FROM (…) q LIMIT n.

Disabled unless ASSISTANT_ENABLE_SQL=1 AND a "readonly" database is configured: today there is no
separate role, so the tool is off (see docs/archive/INTERFACE_PROPOSALS.md).
"""
from __future__ import annotations

import datetime as dt
import decimal
import os
import re

import sqlparse
from pydantic import BaseModel, Field

from .registry import ToolError, register

STATEMENT_TIMEOUT = "3s"
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|upsert|drop|alter|create|grant|revoke|copy|truncate|vacuum|analyze|"
    r"reindex|cluster|call|do|execute|prepare|deallocate|listen|notify|unlisten|set|reset|lock|comment|"
    r"security|into|refresh|import|load|discard|checkpoint|begin|commit|rollback|savepoint|"
    r"dblink\w*|lo_\w+|set_config|current_setting|nextval|setval|currval|txid_\w+|"
    r"\w*_to_xml\w*|xpath\w*|query_to_\w+|pg_\w*)\b|\bpg_\w*|information_schema|;", re.I)

# Platform tables the assistant may query (Django models in core); chat/auth/system tables excluded.
ALLOWED_MODELS = ["Clock", "WeatherGrid", "WeatherDaily", "WeatherForecastDaily", "WeatherHourly", "SoilCell",
                  "CropClass", "Field", "FieldCropYear", "Threat", "Risk"]


def allowed_tables() -> dict[str, object]:
    from django.apps import apps
    return {apps.get_model("core", m)._meta.db_table: apps.get_model("core", m) for m in ALLOWED_MODELS}


def schema_description(max_cols: int = 14) -> str:
    """Generated from the Django models: table, one-line description, columns (with units)."""
    lines = []
    for table, model in allowed_tables().items():
        doc = (model.__doc__ or "").strip().split("\n")[0]
        cols = []
        for f in model._meta.concrete_fields:
            unit = ""
            ht = f.help_text or ""
            if ht.startswith("[") and "]" in ht:
                unit = ht[1:ht.index("]")]
            cols.append(f"{f.column}{f' [{unit}]' if unit else ''}")
        more = f", … (+{len(cols) - max_cols})" if len(cols) > max_cols else ""
        lines.append(f"- {table}: {doc} Kolumny: {', '.join(cols[:max_cols])}{more}")
    return "\n".join(lines)


def sql_enabled() -> bool:
    from django.conf import settings
    return os.getenv("ASSISTANT_ENABLE_SQL", "0") == "1" and "readonly" in settings.DATABASES


def validate(query: str) -> str:
    """Return the cleaned query or raise ToolError (Polish message)."""
    if not query or not query.strip():
        raise ToolError("Puste zapytanie SQL.")
    cleaned = sqlparse.format(query, strip_comments=True).strip().rstrip(";").strip()
    statements = [s for s in sqlparse.parse(cleaned) if str(s).strip()]
    if len(statements) != 1:
        raise ToolError("Dozwolona jest dokładnie jedna instrukcja SQL.")
    if statements[0].get_type() != "SELECT":
        raise ToolError("Dozwolone są tylko zapytania SELECT (także WITH … SELECT).")
    m = FORBIDDEN.search(cleaned)
    if m:
        raise ToolError(f"Zapytanie zawiera niedozwolony element: „{m.group(0)}”.")
    if re.search(r"\b[a-z_][a-z0-9_]*\s*\.\s*[a-z_][a-z0-9_]*\s*\(", cleaned, re.I):
        raise ToolError("Wywołania funkcji z innych schematów są niedozwolone.")
    from django.db import connection
    existing = set(connection.introspection.table_names())
    allowed = set(allowed_tables())
    words = set(re.findall(r"[a-z_][a-z0-9_]*", cleaned.lower()))
    forbidden_tables = sorted((words & existing) - allowed)
    if forbidden_tables:
        raise ToolError(f"Tabele spoza listy dozwolonych: {forbidden_tables}. Dozwolone: {sorted(allowed)}.")
    if not (words & allowed):
        raise ToolError(f"Zapytanie musi czytać z dozwolonych tabel: {sorted(allowed)}.")
    return cleaned


def _jsonable(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


def execute(query: str, max_rows: int = 50, alias: str = "readonly") -> dict:
    """Validate and run in a read-only, time-limited transaction that is always rolled back."""
    from django.db import connections, transaction
    cleaned = validate(query)
    n = max(1, min(int(max_rows), 500))
    wrapped = f"SELECT * FROM ({cleaned}) AS q LIMIT {n + 1}"
    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cur:
                cur.execute("SET LOCAL transaction_read_only = on")
                cur.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
                cur.execute(wrapped)
                cols = [c.name for c in cur.description]
                rows = cur.fetchall()
            transaction.set_rollback(True, using=alias)
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ToolError(f"Błąd wykonania zapytania: {str(e).splitlines()[0]}") from None
    return {"columns": cols, "rows": [[_jsonable(v) for v in r] for r in rows[:n]], "truncated": len(rows) > n}


class SqlIn(BaseModel):
    query: str = Field(description="Jedno zapytanie SELECT po tabelach z opisu narzędzia.")
    max_rows: int = Field(50, ge=1, le=500)


def _description() -> str:
    base = ("Wykonuje jedno zapytanie SELECT (tylko odczyt, limit czasu 3 s, maks. wierszy) na danych "
            "platformy, gdy żadne inne narzędzie nie wystarcza. Daty w kolumnach `date` (lokalne). "
            "Ryzyko: core_risk.score 0–1. Nie odczytuj dat po dziś + 7 (core_clock.today).\nDozwolone tabele:\n")
    try:
        return base + schema_description()
    except Exception:  # noqa: BLE001 - apps not ready at import time in some contexts
        return base + ", ".join(ALLOWED_MODELS)


@register("run_readonly_sql", _description(), SqlIn, enabled=sql_enabled)
def run_readonly_sql(query: str, max_rows: int = 50) -> dict:
    return execute(query, max_rows)
