"""Jednorazowy alert Telegram z danych, które już są w PostgreSQL.

Nie czeka na północ. Gdy public.field_calendar ma wiersze, wysyła ten sam
komunikat co cron (najbardziej ryzykowne pole, saletra amonowa). W przeciwnym
razie bierze największe pole z public.field_profile i opisuje jego glebę.

    python fake_telegram.py
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2

from env_config import load_env_file

ROOT = Path(__file__).parent


def _dsn() -> str:
    missing = [key for key in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD") if not os.environ.get(key)]
    if missing:
        raise SystemExit(f"Brak w .env: {', '.join(missing)}")
    return (
        f"host={os.environ['PGHOST']} port={os.environ['PGPORT']} "
        f"dbname={os.environ['PGDATABASE']} user={os.environ['PGUSER']} "
        f"password={os.environ['PGPASSWORD']}"
    )


def _table_count(cur, name: str) -> int:
    cur.execute("SELECT to_regclass(%s)", (f"public.{name}",))
    if cur.fetchone()[0] is None:
        return 0
    cur.execute(f"SELECT count(*) FROM public.{name}")
    return int(cur.fetchone()[0])


def _fmt(value, suffix: str = "", digits: int | None = None) -> str:
    if value is None:
        return "brak"
    if digits is not None:
        return f"{float(value):.{digits}f}{suffix}"
    return f"{value}{suffix}"


def _profile_message(cur, field_extent, lizmap_url: str) -> str | None:
    cur.execute(
        """
        SELECT field_id, area_ha, crop, texture, ph, sand_pct, silt_pct, clay_pct,
               permeability, water_retention
        FROM public.field_profile
        ORDER BY (crop IS NOT NULL) DESC, area_ha DESC NULLS LAST
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if row is None:
        return None
    field_id, area_ha, crop, texture, ph, sand, silt, clay, permeability, water_retention = row
    lines = [
        f"🌾 <b>Pole {field_id}</b> · {crop or 'uprawa nieznana'}"
        + (f" · {area_ha:.2f} ha" if area_ha is not None else ""),
        "",
        f"Tekstura: {_fmt(texture)}",
        f"Piasek / pył / ił: {_fmt(sand, '%', 0)} / {_fmt(silt, '%', 0)} / {_fmt(clay, '%', 0)}",
        f"pH: {_fmt(ph, digits=1)}",
        f"Przepuszczalność: {_fmt(permeability)}",
        f"Retencja wody: {_fmt(water_retention)}",
    ]
    extent = field_extent(cur, field_id)
    if extent and all(value is not None for value in extent):
        bbox = ",".join(f"{value:.0f}" for value in extent)
        lines += ["", f'<a href="{lizmap_url}&bbox={bbox}&crs=EPSG:3857">Otwórz pole na mapie</a>']
    return "\n".join(lines)


def _send(text: str, api) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(text)
        print("Ustaw TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID — wiadomość nie wysłana.")
        return
    api(token, "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
    print("Wysłano.")


def main() -> None:
    load_env_file(ROOT / ".env")
    from telegram_alerts import _api, _field_extent, _lizmap_url, sendTelegramAlert

    dsn = _dsn()
    print(
        f"łączę z PostgreSQL {os.environ['PGUSER']}@{os.environ['PGHOST']}:"
        f"{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        calendar_rows = _table_count(cur, "field_calendar")
        if calendar_rows:
            print(f"public.field_calendar: {calendar_rows} wierszy — wysyłam alert nawożenia")
            sendTelegramAlert(top=1, dsn=dsn)
            return
        print("public.field_calendar jest pusta — wysyłam profil gleby z field_profile")
        text = _profile_message(cur, _field_extent, _lizmap_url())
    if not text:
        raise SystemExit("Brak wierszy w public.field_profile. Najpierw uruchom dbseed.")
    _send(text, _api)


if __name__ == "__main__":
    main()
