from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import pandas as pd
import streamlit as st

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _get_secret_or_env(key: str) -> str:
    try:
        if hasattr(st, "secrets") and key in st.secrets:
            val = str(st.secrets[key]).strip()
            if val:
                return val
    except Exception:
        pass
    return os.environ.get(key, "").strip()


def build_farm_context(
    result_df: pd.DataFrame,
    farm_profile: dict[str, Any] | None,
    selected_timestamp: Any,
    eco_mode: bool,
) -> str:
    """Buduje zwięzłe podsumowanie aktualnego stanu pól, pogody i trybu EKO dla asystenta."""
    profile = farm_profile or {}
    ts_label = str(selected_timestamp)
    try:
        ts_label = pd.to_datetime(selected_timestamp).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    if result_df is None or result_df.empty:
        return (
            f"Timestamp: {ts_label}\n"
            f"Farm: {profile.get('farm_name', 'My Farm')}\n"
            f"ECO mode: {eco_mode}\n"
            "Fields: none in current view."
        )

    decisions = (
        result_df["decyzja"].value_counts().head(6).to_dict()
        if "decyzja" in result_df.columns
        else {}
    )
    crops = (
        result_df["crop_name"].value_counts().head(6).to_dict()
        if "crop_name" in result_df.columns
        else {}
    )

    total_fields = len(result_df)
    total_ha = (
        float(pd.to_numeric(result_df["area_ha"], errors="coerce").fillna(1.5).sum())
        if "area_ha" in result_df.columns
        else total_fields * 1.5
    )

    def _mean_col(col: str, default: float = 0.0) -> float:
        if col not in result_df.columns:
            return default
        s = pd.to_numeric(result_df[col], errors="coerce").dropna()
        return float(s.mean()) if not s.empty else default

    avg_temp = _mean_col("temp_c", 0.0)
    avg_wind = _mean_col("wind_ms", 0.0)
    avg_rain = _mean_col("precip_24h_mm", 0.0)
    avg_ndvi = _mean_col("ndvi", 0.0)
    avg_ph = _mean_col("soil_ph", 0.0)

    eco_count = 0
    if "is_eco_field" in result_df.columns:
        eco_count = int(result_df["is_eco_field"].fillna(False).astype(bool).sum())

    hazards = []
    if "zagrozenie" in result_df.columns:
        h_series = result_df["zagrozenie"].dropna().astype(str)
        h_series = h_series[
            ~h_series.str.lower().isin({"", "brak", "none", "brak krytycznego zagrożenia"})
        ]
        hazards = h_series.value_counts().head(5).to_dict()

    sample_rows = []
    cols_for_sample = [
        c
        for c in ["field_uid", "crop_name", "decyzja", "zalecany_nawoz", "nawozy_eko", "soil_ph"]
        if c in result_df.columns
    ]
    if cols_for_sample:
        for _, r in result_df[cols_for_sample].head(6).iterrows():
            sample_rows.append({k: (None if pd.isna(v) else v) for k, v in r.items()})

    lines = [
        f"Timestamp: {ts_label}",
        (
            f"Farm: {profile.get('farm_name', 'My Farm')} | "
            f"Region: {profile.get('wojewodztwo', '')} / {profile.get('powiat', '')} / {profile.get('gmina', '')}"
        ),
        f"ECO mode active: {bool(eco_mode)} | ECO-flagged fields in view: {eco_count}",
        f"Visible fields: {total_fields} | Total area: {total_ha:.2f} ha",
        (
            f"Avg weather: temp={avg_temp:.1f} C, wind={avg_wind:.1f} m/s, "
            f"precip_24h={avg_rain:.1f} mm, avg_NDVI={avg_ndvi:.2f}, avg_pH={avg_ph:.2f}"
        ),
        f"Decisions breakdown: {json.dumps(decisions, ensure_ascii=False)}",
        f"Crops breakdown: {json.dumps(crops, ensure_ascii=False)}",
        f"Active hazards: {json.dumps(hazards, ensure_ascii=False)}",
        f"Sample fields (up to 6): {json.dumps(sample_rows, ensure_ascii=False)}",
    ]
    return "\n".join(lines)


def _offline_fallback_reply(
    prompt: str,
    result_df: pd.DataFrame,
    farm_profile: dict[str, Any] | None,
    selected_timestamp: Any,
    eco_mode: bool,
    is_en: bool,
    reason: str | None = None,
) -> str:
    """Awaryjna odpowiedź bez zewnętrznego API — oparta bezpośrednio na danych z aplikacji."""
    t = lambda pl, en: en if is_en else pl
    profile = farm_profile or {}
    farm_name = profile.get("farm_name") or t("Twoje gospodarstwo", "Your farm")

    if result_df is None or result_df.empty:
        return t(
            f"**Farmhand (tryb lokalny / podgląd danych):** Dla **{farm_name}** w bieżącym widoku nie ma jeszcze żadnych pól.",
            f"**Farmhand (local data summary):** There are no fields in the current view for **{farm_name}**.",
        )

    total = len(result_df)
    wind = (
        float(pd.to_numeric(result_df["wind_ms"], errors="coerce").dropna().mean())
        if "wind_ms" in result_df.columns and not pd.to_numeric(result_df["wind_ms"], errors="coerce").dropna().empty
        else None
    )
    rain = (
        float(pd.to_numeric(result_df["precip_24h_mm"], errors="coerce").dropna().mean())
        if "precip_24h_mm" in result_df.columns and not pd.to_numeric(result_df["precip_24h_mm"], errors="coerce").dropna().empty
        else None
    )
    temp = (
        float(pd.to_numeric(result_df["temp_c"], errors="coerce").dropna().mean())
        if "temp_c" in result_df.columns and not pd.to_numeric(result_df["temp_c"], errors="coerce").dropna().empty
        else None
    )
    decisions = (
        result_df["decyzja"].value_counts().head(4).to_dict()
        if "decyzja" in result_df.columns
        else {}
    )

    wind_txt = f"{wind:.1f} m/s" if wind is not None else t("brak danych", "n/a")
    rain_txt = f"{rain:.1f} mm" if rain is not None else t("brak danych", "n/a")
    temp_txt = f"{temp:.1f}°C" if temp is not None else t("brak danych", "n/a")

    spray_ok = (wind is None or wind <= 4.5) and (rain is None or rain < 1.0)
    spray_verdict = t(
        "Warunki wiatrowo-opadowe wyglądają na ogół sprzyjająco do precyzyjnych zabiegów (sprawdź jednak etykietę środka i konkretne pole).",
        "Wind and precipitation averages look broadly favorable for field operations (always verify product label and field-level conditions).",
    ) if spray_ok else t(
        "Zachowaj ostrożność przy opryskach/aplikacjach — podwyższony wiatr lub opad w ciągu 24h może ograniczać okno zabiegowe.",
        "Exercise caution with spraying/application — elevated wind or 24h rainfall may narrow the application window.",
    )

    dec_lines = "\n".join(f"- **{k}**: {v}" for k, v in decisions.items()) if decisions else f"- {t('Brak kolumny decyzji', 'No decision column')}"
    note = ""
    if reason:
        note = "\n\n> " + t(
            f"Tryb awaryjny bez połączenia z chmurą ({reason}). Po ustawieniu `GEMINI_API_KEY` lub `OPENAI_API_KEY` Farmhand odpowiada pełnym modelem LLM.",
            f"Fallback mode without cloud LLM ({reason}). Set `GEMINI_API_KEY` or `OPENAI_API_KEY` to enable full LLM responses.",
        )

    return (
        f"**Farmhand** — {t('podsumowanie dla', 'summary for')} **{farm_name}** "
        f"({t('tryb EKO', 'ECO mode')}: **{'ON' if eco_mode else 'OFF'}**)\n\n"
        f"- {t('Liczba pól w widoku', 'Fields in view')}: **{total}**\n"
        f"- {t('Średnia pogoda', 'Average weather')}: {t('temp.', 'temp.')} **{temp_txt}**, "
        f"{t('wiatr', 'wind')} **{wind_txt}**, {t('opad 24h', '24h rain')} **{rain_txt}**\n"
        f"- {t('Decyzje', 'Decisions')}:\n{dec_lines}\n\n"
        f"{spray_verdict}{note}"
    )


def _call_gemini(
    api_key: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    model: str = DEFAULT_GEMINI_MODEL,
) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    contents = []
    for m in messages[-8:]:
        role = "user" if m.get("role") == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.35, "maxOutputTokens": 700},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Empty Gemini response")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise RuntimeError("No text in Gemini response")
    return text


def _call_openai(
    api_key: str,
    system_prompt: str,
    messages: list[dict[str, str]],
    model: str = DEFAULT_OPENAI_MODEL,
) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    chat_msgs = [{"role": "system", "content": system_prompt}]
    for m in messages[-8:]:
        role = "user" if m.get("role") == "user" else "assistant"
        chat_msgs.append({"role": role, "content": m.get("content", "")})

    payload = {
        "model": model,
        "messages": chat_msgs,
        "temperature": 0.35,
        "max_tokens": 700,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Empty OpenAI response")
    content = ((choices[0].get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError("No text in OpenAI response")
    return content


def _generate_farmhand_reply(
    prompt: str,
    messages: list[dict[str, str]],
    context_str: str,
    result_df: pd.DataFrame,
    farm_profile: dict[str, Any] | None,
    selected_timestamp: Any,
    eco_mode: bool,
    is_en: bool,
) -> str:
    t = lambda pl, en: en if is_en else pl
    lang_instruction = (
        "Respond concisely and clearly in English."
        if is_en
        else "Odpowiadaj zwięźle, konkretnie i po polsku."
    )
    system_prompt = (
        "You are Farmhand, an agronomic & precision-farming AI assistant inside the farmIT web app. "
        "Base your answers strictly on the provided live application telemetry/state and standard agronomic good practices. "
        "Never invent field IDs or measurements not present in the context. "
        "If spraying or fertilizer compliance is asked, note weather/label/regulation verification clearly.\n"
        f"{lang_instruction}\n\n"
        f"CURRENT APPLICATION STATE:\n{context_str}"
    )

    gemini_key = _get_secret_or_env("GEMINI_API_KEY")
    openai_key = _get_secret_or_env("OPENAI_API_KEY")

    last_err: str | None = None
    if gemini_key:
        try:
            return _call_gemini(gemini_key, system_prompt, messages)
        except urllib.error.HTTPError as exc:
            last_err = f"Gemini HTTP {exc.code}"
        except Exception as exc:
            last_err = f"Gemini error: {type(exc).__name__}"

    if openai_key:
        try:
            return _call_openai(openai_key, system_prompt, messages)
        except urllib.error.HTTPError as exc:
            last_err = f"OpenAI HTTP {exc.code}"
        except Exception as exc:
            last_err = f"OpenAI error: {type(exc).__name__}"

    reason = last_err or t("brak klucza API", "no API key set")
    return _offline_fallback_reply(
        prompt=prompt,
        result_df=result_df,
        farm_profile=farm_profile,
        selected_timestamp=selected_timestamp,
        eco_mode=eco_mode,
        is_en=is_en,
        reason=reason,
    )


def render_farmhand_bubble(
    result_df: pd.DataFrame,
    farm_profile: dict[str, Any] | None = None,
    selected_timestamp: Any = None,
    eco_mode: bool = False,
) -> None:
    """Renderuje pływający dymek w prawym dolnym rogu otwierający czat z Farmhandem."""
    is_en = st.session_state.get("lang", "pl") == "en"
    t = lambda pl, en: en if is_en else pl

    if "farmhand_messages" not in st.session_state:
        st.session_state.farmhand_messages = []

    st.markdown(
        """
        <style>
        div[data-testid="stPopover"] {
            position: fixed !important;
            bottom: 22px !important;
            right: 22px !important;
            z-index: 999 !important;
            width: auto !important;
        }
        div[data-testid="stPopover"] > div > button {
            border-radius: 999px !important;
            padding: 0.65rem 1.15rem !important;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22) !important;
            font-weight: 600 !important;
        }
        div[data-testid="stPopoverBody"] {
            width: min(410px, calc(100vw - 32px)) !important;
            max-height: 75vh !important;
            overflow-y: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    bubble_label = t("🌾 Farmhand", "🌾 Farmhand")
    with st.popover(bubble_label):
        st.markdown(f"**🌾 Farmhand** — {t('Asystent polowy AI', 'AI Field Assistant')}")
        st.caption(
            t(
                "Kliknij szybkie pytanie lub wpisz własne o bieżące pola i pogodę.",
                "Pick a quick prompt or ask about current fields and weather.",
            )
        )

        quick_q = t("Oceń warunki do zabiegów teraz", "Assess field operation conditions now")
        if st.button(quick_q, key="farmhand_bubble_quick", use_container_width=True):
            st.session_state.farmhand_messages.append({"role": "user", "content": quick_q})
            context_str = build_farm_context(result_df, farm_profile, selected_timestamp, eco_mode)
            reply = _generate_farmhand_reply(
                prompt=quick_q,
                messages=st.session_state.farmhand_messages,
                context_str=context_str,
                result_df=result_df,
                farm_profile=farm_profile,
                selected_timestamp=selected_timestamp,
                eco_mode=eco_mode,
                is_en=is_en,
            )
            st.session_state.farmhand_messages.append({"role": "assistant", "content": reply})

        for msg in st.session_state.farmhand_messages[-6:]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_q = st.text_input(
            t("Twoje pytanie", "Your question"),
            placeholder=t("np. Czy wiatr pozwala na oprysk?", "e.g. Does wind allow spraying?"),
            key="farmhand_bubble_input",
            label_visibility="collapsed",
        )
        if st.button(t("Wyślij", "Send"), key="farmhand_bubble_send", use_container_width=True) and user_q.strip():
            q_clean = user_q.strip()
            st.session_state.farmhand_messages.append({"role": "user", "content": q_clean})
            context_str = build_farm_context(result_df, farm_profile, selected_timestamp, eco_mode)
            reply = _generate_farmhand_reply(
                prompt=q_clean,
                messages=st.session_state.farmhand_messages,
                context_str=context_str,
                result_df=result_df,
                farm_profile=farm_profile,
                selected_timestamp=selected_timestamp,
                eco_mode=eco_mode,
                is_en=is_en,
            )
            st.session_state.farmhand_messages.append({"role": "assistant", "content": reply})
            st.rerun()