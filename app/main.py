import json
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

from silnik_regul import (
    evaluate_fields,
    load_agronomic_rules,
    load_optional_crop_recommendations,
    load_static_fields,
    load_weather_timeseries,
    recommend_crop_by_soil,
)

st.set_page_config(
    page_title="Dashboard farmIT — Zarządzanie Polami",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Pełny CSS odwzorowujący projekt UX (farmIT | FieldGuard 33UXR)
st.markdown(
    """
    <style>
    /* Globalne tło i typografia */
    .stApp {
        background-color: #F4F6F9;
        color: #1E293B;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    .block-container {
        padding-top: 1.5rem !important;
        max-width: 1280px !important;
    }

    /* Nagłówek główny z logo farmIT i zieloną pigułką FieldGuard 33UXR */
    .top-brand-wrap {
        display: flex;
        align-items: center;
        gap: 14px;
        margin-bottom: 14px;
    }
    .logo-circle {
        width: 46px;
        height: 46px;
        background: linear-gradient(135deg, #FEF3C7 0%, #DCFCE7 100%);
        border: 1px solid #BBF7D0;
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
    }
    .brand-name {
        font-size: 24px;
        font-weight: 800;
        color: #0F172A;
        line-height: 1.1;
    }
    .pill-badge {
        background-color: #DCFCE7;
        color: #15803D;
        font-size: 12px;
        font-weight: 700;
        padding: 3px 10px;
        border-radius: 999px;
        margin-left: 8px;
        vertical-align: middle;
    }
    .brand-subtitle {
        font-size: 13px;
        color: #64748B;
        margin-top: 2px;
    }

    /* Pasek zakładek (Tabs) jak pigułki z makiety */
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        background-color: transparent;
        border-bottom: none;
        margin-bottom: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 8px 18px;
        font-weight: 600;
        font-size: 14px;
        color: #334155;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    .stTabs [aria-selected="true"] {
        background-color: #F1F5F9 !important;
        border: 1.5px solid #0F172A !important;
        color: #0F172A !important;
        font-weight: 700 !important;
    }

    /* Karty KPI 2x2 z ikoną po prawej stronie */
    .kpi-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 18px 22px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
        margin-bottom: 14px;
    }
    .kpi-label {
        font-size: 11px;
        font-weight: 700;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .kpi-value {
        font-size: 26px;
        font-weight: 800;
        color: #0F172A;
        margin: 4px 0 2px 0;
    }
    .kpi-sub {
        font-size: 12px;
        font-weight: 600;
    }
    .kpi-icon-box {
        width: 42px;
        height: 42px;
        border-radius: 11px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
    }

    /* Biała sekcja kartowa (Section Card) */
    .section-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 16px;
        padding: 20px 24px;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
        margin-bottom: 18px;
    }
    .section-title {
        font-size: 18px;
        font-weight: 700;
        color: #0F172A;
        margin: 0;
    }
    .section-sub {
        font-size: 13px;
        color: #64748B;
        margin-top: 2px;
        margin-bottom: 14px;
    }

    /* Małe kafelki pogodowe (Temperatura / Wiatr / Opad / Wilgotność) */
    .weather-mini-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 14px 16px;
    }
    .weather-mini-label {
        font-size: 12px;
        color: #64748B;
        font-weight: 600;
    }
    .weather-mini-val {
        font-size: 22px;
        font-weight: 800;
        color: #0F172A;
        margin-top: 4px;
    }
    .weather-mini-hint {
        font-size: 11px;
        color: #94A3B8;
        margin-top: 2px;
    }

    /* Wiersze Dziennika Stacji Pogodowej */
    .log-row {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 12px 18px;
        margin-bottom: 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .log-time {
        font-weight: 700;
        font-size: 14px;
        color: #0F172A;
    }
    .log-details {
        font-size: 13px;
        color: #475569;
        margin-top: 2px;
    }
    .status-pill-warn {
        background: #FEF3C7;
        color: #B45309;
        font-weight: 700;
        font-size: 12px;
        padding: 6px 12px;
        border-radius: 8px;
    }
    .status-pill-ok {
        background: #DCFCE7;
        color: #15803D;
        font-weight: 700;
        font-size: 12px;
        padding: 6px 12px;
        border-radius: 8px;
    }
    .status-pill-bad {
        background: #FEE2E2;
        color: #B91C1C;
        font-weight: 700;
        font-size: 12px;
        padding: 6px 12px;
        border-radius: 8px;
    }

    /* Zielony baner nagłówkowy Doradcy Siewu + karta Najlepsze Dopasowanie */
    .advisor-banner {
        background: #F0FDF4;
        border: 1px solid #BBF7D0;
        border-radius: 14px;
        padding: 18px 22px;
        margin-bottom: 16px;
    }
    .best-match-box {
        background: #ECFDF5;
        border: 1.5px solid #6EE7B7;
        border-radius: 14px;
        padding: 20px 24px;
        margin-top: 16px;
    }
    .best-match-header {
        font-size: 12px;
        font-weight: 800;
        color: #15803D;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .mode-chip {
        background: #FFFFFF;
        border: 1px solid #A7F3D0;
        color: #065F46;
        font-size: 11px;
        font-weight: 600;
        padding: 2px 10px;
        border-radius: 999px;
        margin-left: 8px;
    }
    .best-match-crop {
        font-size: 20px;
        font-weight: 800;
        color: #0F172A;
        margin: 6px 0;
    }
    .best-match-reason {
        font-size: 13px;
        color: #334155;
        margin: 0;
    }

    /* Styl zielonych przycisków głównych */
    div.stButton > button[kind="primary"], div.stDownloadButton > button {
        background-color: #166534 !important;
        color: #FFFFFF !important;
        border-radius: 10px !important;
        border: none !important;
        font-weight: 600 !important;
        padding: 0.5rem 1.2rem !important;
    }
    div.stButton > button[kind="secondary"] {
        background-color: #FFFFFF !important;
        color: #1E293B !important;
        border: 1px solid #CBD5E1 !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def get_base_data():
    return (
        load_static_fields(),
        load_weather_timeseries(),
        load_agronomic_rules(),
        load_optional_crop_recommendations(),
    )


fields_df, weather_df, rules_df, crop_dict_df = get_base_data()
timestamps = sorted(weather_df["timestamp"].unique())

# Inicjalizacja stanu sesji dla dziennika odczytów i zapisanych wyborów upraw
if "weather_journal" not in st.session_state:
    st.session_state.weather_journal = [
        {"czas": "Dziś, 19:00 (Okno wieczorne)", "temp": 18.2, "opad": 0.0, "wiatr_ms": 2.4, "ocena": "ok", "etykieta": "PRYSKAJ TERAZ — optymalne warunki"},
        {"czas": "Dziś, 13:00 (Szczyt dzienny)", "temp": 22.5, "opad": 0.0, "wiatr_ms": 5.3, "ocena": "warn", "etykieta": "Zbyt silny wiatr na oprysk (> 4 m/s)"},
        {"czas": "Wczoraj, 07:30", "temp": 16.5, "opad": 14.2, "wiatr_ms": 2.2, "ocena": "bad", "etykieta": "Opad — wstrzymać oprysk"},
    ]
if "saved_crops" not in st.session_state:
    st.session_state.saved_crops = {}

# Górny nagłówek farmIT | FieldGuard 33UXR
st.markdown(
    """
    <div class="top-brand-wrap">
        <div class="logo-circle">🌾</div>
        <div>
            <div class="brand-name">farmIT <span class="pill-badge">FieldGuard 33UXR</span></div>
            <div class="brand-subtitle">FieldGuard 33UXR • Inteligentne zarządzanie polami i pogodą</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Pasek nawigacyjny 4 zakładek (zgodnie z makietą Osoby 4)
tab_pola, tab_siew, tab_kalk, tab_zasady = st.tabs(
    [
        "🗂️ Pola i Pogoda",
        "🧭 Polecanie Upraw",
        "🧪 Kalkulator Nawozów i Pestycydów",
        "📜 Zasady Agro i 33UXR",
    ]
)

with tab_pola:
    # Pasek narzędzi: Eksport JSON / Dane startowe / Symulacja What-If
    b_col1, b_col2, b_col3, b_col4 = st.columns([1.1, 1.1, 1.4, 2.4])
    with b_col1:
        export_payload = fields_df.head(50).to_json(orient="records", force_ascii=False, indent=2)
        st.download_button(
            "⬇️ Eksportuj JSON",
            data=export_payload,
            file_name="fieldguard_33uxr_ewidencja.json",
            mime="application/json",
            use_container_width=True,
        )
    with b_col2:
        if st.button("🔄 Dane startowe", use_container_width=True):
            st.session_state.saved_crops = {}
            st.toast("Przywrócono domyślne dane startowe kafla 33UXR!")
    with b_col3:
        what_if = st.toggle("🎛️ Tryb Symulacji „What-If”", value=False)

    if what_if:
        w1, w2, w3 = st.columns(3)
        sim_temp = w1.slider("Symulacja: Temperatura (°C)", -5.0, 38.0, 19.0, 0.5)
        sim_wind = w2.slider("Symulacja: Wiatr (m/s)", 0.0, 15.0, 2.5, 0.1)
        sim_precip = w3.slider("Symulacja: Opad 24h (mm)", 0.0, 30.0, 8.0, 0.5)
    else:
        sim_temp, sim_wind, sim_precip = 19.0, 2.5, 0.0

    # Wybór godziny na osi czasu
    selected_ts = st.select_slider(
        "🕒 Oś czasu prognozy godzinowej (krok co 1h):",
        options=timestamps,
        value=timestamps[min(7, len(timestamps) - 1)],
        format_func=lambda x: pd.to_datetime(x).strftime("%Y-%m-%d %H:%M"),
    )

    result_df = evaluate_fields(
        fields_df=fields_df,
        weather_df=weather_df,
        rules_df=rules_df,
        selected_timestamp=selected_ts,
        what_if=what_if,
        override_temp_c=sim_temp,
        override_wind_ms=sim_wind,
        override_precip_24h_mm=sim_precip,
        crop_dict_df=crop_dict_df,
    )

    # Siatka 2x2 kart KPI dokładnie jak na zrzucie 1 z Google Sites
    total_fields = len(result_df)
    total_area_ha = total_fields * 1.50  # 1 heksagon H3 L10 ~ 1.5 ha
    avg_humidity = float(result_df["humidity_pct"].mean()) if not result_df.empty else 0.0
    ready_fields = sum(result_df["decyzja"].isin(["PRYSKAJ TERAZ", "NAWOŹ", "ZASIEJ"]))

    kpi_r1_c1, kpi_r1_c2 = st.columns(2)
    with kpi_r1_c1:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div>
                    <div class="kpi-label">LICZBA PÓL (H3 L10)</div>
                    <div class="kpi-value">{total_fields} pól</div>
                    <div class="kpi-sub" style="color:#64748B;">Ewidencja gospodarstwa (kafel 33UXR)</div>
                </div>
                <div class="kpi-icon-box" style="background:#EEF2FF; color:#4F46E5;">🗺️</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with kpi_r1_c2:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div>
                    <div class="kpi-label">ŁĄCZNY AREAŁ</div>
                    <div class="kpi-value">{total_area_ha:,.2f} ha</div>
                    <div class="kpi-sub" style="color:#15803D;">Powierzchnia uprawna</div>
                </div>
                <div class="kpi-icon-box" style="background:#DCFCE7; color:#15803D;">📐</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    kpi_r2_c1, kpi_r2_c2 = st.columns(2)
    with kpi_r2_c1:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div>
                    <div class="kpi-label">ŚR. WILGOTNOŚĆ POWIETRZA</div>
                    <div class="kpi-value">{avg_humidity:.0f}%</div>
                    <div class="kpi-sub" style="color:#15803D;">{"Optymalne uwilgotnienie do zabiegu" if avg_humidity >= 60 else "Podwyższona suchość powietrza"}</div>
                </div>
                <div class="kpi-icon-box" style="background:#DBEAFE; color:#2563EB;">💧</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with kpi_r2_c2:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div>
                    <div class="kpi-label">POLA GOTOWE DO PRACY</div>
                    <div class="kpi-value">{ready_fields} z {total_fields}</div>
                    <div class="kpi-sub" style="color:#15803D;">PRYSKAJ TERAZ / NAWOŹ / ZASIEJ</div>
                </div>
                <div class="kpi-icon-box" style="background:#DCFCE7; color:#15803D;">✅</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Karta: Pogoda i Okno Zabiegowe (4 mini-kafelki + wykres słupkowy + mapa H3)
    avg_temp = float(result_df["temp_c"].mean()) if not result_df.empty else 0.0
    avg_wind = float(result_df["wind_ms"].mean()) if not result_df.empty else 0.0
    avg_precip = float(result_df["precip_24h_mm"].mean()) if not result_df.empty else 0.0
    wind_kmh = avg_wind * 3.6

    st.markdown(
        f"""
        <div class="section-card">
            <div class="section-title">🟢 Pogoda i Okno Zabiegowe (Oś Czasu + Mapa H3)</div>
            <div class="section-sub">Warunki dla kafla Sentinel-2 33UXR (Małopolska: Kraków / Tarnów / Nowy Sącz) • Godzina: {pd.to_datetime(selected_ts).strftime('%Y-%m-%d %H:%M')}</div>
            <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap: 12px;">
                <div class="weather-mini-card">
                    <div class="weather-mini-label">Temperatura</div>
                    <div class="weather-mini-val">{avg_temp:.1f} °C</div>
                    <div class="weather-mini-hint">Zakres zabiegowy: 10–25 °C</div>
                </div>
                <div class="weather-mini-card">
                    <div class="weather-mini-label">Wiatr (próg 4 m/s)</div>
                    <div class="weather-mini-val" style="color:{'#DC2626' if avg_wind > 4.0 else '#15803D'};">{avg_wind:.1f} m/s</div>
                    <div class="weather-mini-hint">{wind_kmh:.1f} km/h</div>
                </div>
                <div class="weather-mini-card">
                    <div class="weather-mini-label">Opad (24h / aktualny)</div>
                    <div class="weather-mini-val" style="color:{'#DC2626' if avg_precip >= 5.0 else '#2563EB'};">{avg_precip:.1f} mm</div>
                    <div class="weather-mini-hint">Blokada zmycia od 5.0 mm</div>
                </div>
                <div class="weather-mini-card">
                    <div class="weather-mini-label">Wilgotność pow.</div>
                    <div class="weather-mini-val">{avg_humidity:.0f}%</div>
                    <div class="weather-mini-hint">Minimum dla oprysku: 60%</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_map, col_bar = st.columns([1.3, 1.0])
    COLOR_MAP = {
        "PRYSKAJ TERAZ": [22, 163, 74, 200],
        "NAWOŹ": [147, 51, 234, 200],
        "ZASIEJ": [8, 145, 178, 200],
        "ZBIERAJ": [37, 99, 235, 200],
        "MONITORUJ": [202, 138, 4, 195],
        "CZEKAJ": [220, 38, 38, 210],
    }
    result_df["color"] = result_df["decyzja"].map(lambda d: COLOR_MAP.get(d, [100, 116, 139, 180]))

    with col_map:
        st.markdown("**Mapa heksagonalna decyzji polowych (H3 Level 10)**")
        layer = pdk.Layer(
            "H3HexagonLayer",
            data=result_df,
            pickable=True,
            stroked=True,
            filled=True,
            extruded=False,
            get_hexagon="h3_index",
            get_fill_color="color",
            get_line_color=[30, 41, 59],
            line_width_min_pixels=1,
        )
        view_state = pdk.ViewState(
            latitude=float(result_df["lat"].mean()) if not result_df.empty else 50.06,
            longitude=float(result_df["lon"].mean()) if not result_df.empty else 19.94,
            zoom=8.5,
            pitch=0,
        )
        deck = pdk.Deck(
            map_style="light",
            layers=[layer],
            initial_view_state=view_state,
            tooltip={
                "html": "<b>H3:</b> {h3_index} | <b>Reguła:</b> {rule_id}<br/>"
                "<b>Uprawa:</b> {crop_name} (NDVI: {ndvi})<br/>"
                "<b>Decyzja:</b> {decyzja} | <b>Ryzyko:</b> {poziom_ryzyka}<br/>"
                "<b>Komunikat:</b> {komunikat}<br/>"
                "<b>Nawóz:</b> {zalecany_nawoz} | <b>Siew:</b> {rekomendowana_uprawa}<br/>"
                "<b>Gleba:</b> pH {soil_ph}, SOC {soil_soc} g/kg ({soil_texture})<br/>"
                "<b>Pogoda:</b> Wiatr {wind_ms} m/s, Temp {temp_c} °C, Opad {precip_24h_mm} mm"
            },
        )
        st.pydeck_chart(deck, use_container_width=True)

    with col_bar:
        st.markdown("**Prędkość wiatru na polach vs próg 4.0 m/s (jak na makiecie)**")
        sample_fields = result_df.head(8).copy()
        sample_fields["etykieta_pola"] = [f"Pole #{i+1} ({c[:8]})" for i, c in enumerate(sample_fields["crop_name"])]
        sample_fields["status_wiatru"] = sample_fields["wind_ms"].apply(
            lambda w: "Przekroczony (> 4 m/s)" if w > 4.0 else "Bezpieczny (<= 4 m/s)"
        )
        fig_wind = px.bar(
            sample_fields,
            x="etykieta_pola",
            y="wind_ms",
            text="wind_ms",
            color="status_wiatru",
            color_discrete_map={
                "Bezpieczny (<= 4 m/s)": "#2563EB",
                "Przekroczony (> 4 m/s)": "#EF4444",
            },
            labels={"etykieta_pola": "", "wind_ms": "Wiatr [m/s]", "status_wiatru": ""},
        )
        fig_wind.update_traces(texttemplate="%{text:.1f}", textposition="outside")
        fig_wind.add_hline(y=4.0, line_dash="dash", line_color="#DC2626")
        fig_wind.update_layout(
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="#FFFFFF",
            showlegend=False,
            margin=dict(t=25, b=20, l=10, r=10),
            yaxis_range=[0, max(7.0, float(sample_fields["wind_ms"].max()) + 1.5)],
        )
        st.plotly_chart(fig_wind, use_container_width=True)

    # Karta: Dziennik stacji pogodowej (dokładnie jak na zrzucie 2 z Google Sites)
    st.markdown(
        """
        <div class="section-card">
            <div class="section-title">Dziennik stacji pogodowej</div>
            <div class="section-sub">Historia odczytów i szybka ocena warunków do oprysku</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    j1, j2, j3, j4 = st.columns([1.2, 1.2, 1.2, 1.1])
    in_temp = j1.number_input("Temp °C", value=18.5, step=0.5, label_visibility="collapsed", key="j_temp")
    in_rain = j2.number_input("Opad mm", value=0.0, step=0.5, label_visibility="collapsed", key="j_rain")
    in_wind_kmh = j3.number_input("Wiatr km/h", value=11.0, step=1.0, label_visibility="collapsed", key="j_wind")
    with j4:
        if st.button("+ Zapisz odczyt", type="primary", use_container_width=True):
            w_ms = in_wind_kmh / 3.6
            if in_rain >= 5.0:
                ocena, etykieta = "bad", "Opad — wstrzymać oprysk"
            elif w_ms > 4.0:
                ocena, etykieta = "warn", "Zbyt silny wiatr na oprysk"
            else:
                ocena, etykieta = "ok", "Warunki optymalne do zabiegu"
            st.session_state.weather_journal.insert(
                0,
                {
                    "czas": f"Nowy odczyt ({pd.to_datetime(selected_ts).strftime('%H:%M')})",
                    "temp": in_temp,
                    "opad": in_rain,
                    "wiatr_ms": round(w_ms, 1),
                    "ocena": ocena,
                    "etykieta": etykieta,
                },
            )

    for entry in st.session_state.weather_journal[:5]:
        pill_class = (
            "status-pill-ok"
            if entry["ocena"] == "ok"
            else ("status-pill-bad" if entry["ocena"] == "bad" else "status-pill-warn")
        )
        st.markdown(
            f"""
            <div class="log-row">
                <div>
                    <div class="log-time">{entry['czas']}</div>
                    <div class="log-details">Temp: <b>{entry['temp']}°C</b> • Opad: <b>{entry['opad']} mm</b> • Wiatr: <b>{round(entry['wiatr_ms']*3.6)} km/h</b> ({entry['wiatr_ms']} m/s)</div>
                </div>
                <div class="{pill_class}">{entry['etykieta']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("📋 Rozwiń pełną tabelę ewidencji pól i reguł (CSV / Parquet)"):
        display_cols = [
            "h3_index",
            "rule_id",
            "crop_name",
            "ndvi",
            "decyzja",
            "poziom_ryzyka",
            "zalecany_nawoz",
            "rekomendowana_uprawa",
            "komunikat",
        ]
        st.dataframe(result_df[display_cols], use_container_width=True, hide_index=True