"""
Powiadomienia Telegram dla rolnika: najlepsze okno nawożenia + ostrzeżenia na najbliższe dni,
na podstawie tabeli public.field_calendar (wypełnianej przez kw/load_postgis.py).

Jedyna publiczna funkcja: sendTelegramAlert.
Cron o północy jest w main.py (--telegram-cron) i woła sendTelegramAlert(top=3).

Jednorazowa konfiguracja (zmienne środowiskowe lub .env):
  TELEGRAM_BOT_TOKEN  — token z @BotFather
  TELEGRAM_CHAT_ID    — chat_id (sendTelegramAlert(get_chat_id=True) wypisze go po wiadomości do bota)
  HC_LIZMAP_URL       — opcjonalny publiczny adres Lizmapa
"""
from __future__ import annotations

import os

import psycopg2
import requests

__all__ = ["sendTelegramAlert"]

_DEFAULT_DSN = "host=localhost port=8093 dbname=geoai user=postgres password=postgres"
_LIZMAP_BASE = os.environ.get("HC_LIZMAP_URL", "http://localhost:8090").rstrip("/")
_LIZMAP_URL = f"{_LIZMAP_BASE}/index.php/view/map?repository=holycrop&project=satops_project"
_FERT_LABELS = {
    "saletra_amonowa": "Saletra amonowa",
    "mocznik_inhibitor": "Mocznik z inhibitorem",
    "rsm_32": "RSM 32",
    "saletrosan_26": "Saletrosan 26",
}
_STATUS_ICON = {"ZIELONY": "🟢", "ZOLTY": "🟡", "CZERWONY": "🔴"}
_WEEKDAYS = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]


def _api(token: str, method: str, **params) -> dict:
    resp = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=30)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method}: {data.get('description')}")
    return data["result"]


def _field_rows(cur, field_id: int, fertilizer: str):
    cur.execute(
        """SELECT c.day, c.status, c.fert_reasons, c.irrigation_risk, c.temp_mean_c, c.precip_24h_mm,
                  p.crop, p.area_ha
           FROM public.field_calendar c JOIN public.field_profile p USING (field_id)
           WHERE c.field_id = %s AND c.fertilizer = %s ORDER BY c.day""",
        (field_id, fertilizer),
    )
    return cur.fetchall()


def _field_extent(cur, field_id: int):
    cur.execute(
        "SELECT ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g) "
        "FROM (SELECT ST_Expand(geometry, 150) g FROM public.fields WHERE id = %s) s",
        (field_id,),
    )
    return cur.fetchone()


def _compose(cur, field_id: int, fertilizer: str) -> str | None:
    rows = _field_rows(cur, field_id, fertilizer)
    if not rows:
        return None
    crop, area_ha = rows[0][6], rows[0][7]
    best = next((r for r in rows if r[1] == "ZIELONY"), None)
    lines = [
        f"🌾 <b>Pole {field_id}</b> · {crop} · {area_ha:.2f} ha",
        f"Nawóz: {_FERT_LABELS.get(fertilizer, fertilizer)}",
        "",
    ]
    if best:
        d = best[0]
        lines.append(
            f"✅ <b>Najlepszy termin: {_WEEKDAYS[d.weekday()]} {d:%d.%m}</b> "
            f"({best[4]:.0f}°C, opad {best[5]:.1f} mm)"
        )
    else:
        lines.append("⛔ <b>Brak korzystnego terminu w najbliższych 7 dniach</b>")
    lines.append("")
    for day, status, reasons, irrigation, temp, precip, *_ in rows:
        first_reason = (reasons or "").split(" | ")[0]
        lines.append(
            f"{_STATUS_ICON.get(status, '⚪')} {_WEEKDAYS[day.weekday()]} {day:%d.%m} · "
            f"{temp:.0f}°C · {precip:.1f} mm" + (f" — {first_reason}" if status != "ZIELONY" else "")
        )
    if any(r[3] == "WYSOKIE" for r in rows):
        lines += ["", "💧 Uwaga: wysokie ryzyko niedoboru wody w strefie korzeniowej."]
    ext = _field_extent(cur, field_id)
    if ext:
        lines += ["", f'<a href="{_LIZMAP_URL}&bbox={",".join(f"{v:.0f}" for v in ext)}&crs=EPSG:3857">Otwórz pole na mapie</a>']
    return "\n".join(lines)


def _top_fields(cur, n: int, fertilizer: str) -> list[int]:
    cur.execute(
        """SELECT field_id FROM public.field_calendar WHERE fertilizer = %s
           GROUP BY field_id
           ORDER BY sum(CASE status WHEN 'CZERWONY' THEN 2 WHEN 'ZOLTY' THEN 1 ELSE 0 END) DESC, field_id
           LIMIT %s""",
        (fertilizer, n),
    )
    return [r[0] for r in cur.fetchall()]


def sendTelegramAlert(
    field_ids: list[int] | None = None,
    top: int = 0,
    fertilizer: str = "saletra_amonowa",
    dsn: str = _DEFAULT_DSN,
    dry_run: bool = False,
    get_chat_id: bool = False,
) -> None:
    """Wyślij alerty nawożenia na Telegram.

    Podaj ``field_ids`` albo ``top`` (liczba pól z największym ryzykiem).
    Cron w main.py woła tę funkcję z ``top=3``.
    """
    if fertilizer not in _FERT_LABELS:
        raise ValueError(f"Nieznany nawóz: {fertilizer}. Dozwolone: {', '.join(_FERT_LABELS)}")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if get_chat_id:
        if not token:
            print("Ustaw TELEGRAM_BOT_TOKEN")
            return
        for upd in _api(token, "getUpdates"):
            chat = (upd.get("message") or {}).get("chat", {})
            print(f"chat_id={chat.get('id')}  ({chat.get('first_name', '')} {chat.get('username', '')})")
        return

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        ids = list(field_ids or [])
        if top > 0:
            ids.extend(_top_fields(cur, top, fertilizer))
        if not ids:
            print("Podaj field_ids albo top > 0")
            return
        messages = [m for m in (_compose(cur, i, fertilizer) for i in ids) if m]

    if not messages:
        print("Brak danych w field_calendar dla podanych pól (pole < 3 ha albo nie uruchomiono load_postgis.py).")
        return
    for text in messages:
        if dry_run:
            print(text, "\n" + "-" * 40)
            continue
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            print("Ustaw TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID")
            return
        _api(token, "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
        print("Wysłano.")


if __name__ == "__main__":
    sendTelegramAlert()
