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
    page_title="FieldGuard 33UXR — Prace polowe i pogoda",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

    :root {
        --bg: #F7F5F0;
        --card: #FFFFFF;
        --card-soft: #FBF9F5;
        --ink: #1F2924;
        --muted: #5A655F;
        --line: #E2DDD3;
        --green: #2E6F40;
        --green-bg: #EAF4EC;
        --green-line: #B7D8BE;
        --amber: #9A5B13;
        --amber-bg: #FDF4E7;
        --amber-line: #EED2A6;
        --red: #9E2A2B;
        --red-bg: #FDECEC;
        --red-line: #EBB8B8;
    }

    #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] {
        display: none !important;
    }
    header[data-testid="stHeader"] {
        background: transparent !important;
        height: 0 !important;
    }

    .stApp {
        background-color: var(--bg);
        color: var(--ink);
        font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
    }
    .block-container {
        padding-top: 1.4rem !important;
        padding-bottom: 2.5rem !important;
        max-width: 1320px !important;
    }

    .num {
        font-variant-numeric: tabular-nums;
    }

    /* Naglowek */
    .farm-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 18px 22px;
        margin-bottom: 14px;
    }
    .farm-title {
        font-size: 24px;
        font-weight: 800;
        color: var(--ink);
        margin: 0;
        letter-spacing: -0.015em;
    }
    .farm-sub {
        font-size: 14px;
        color: var(--muted);
        margin-top: 3px;
    }

    /* Glówny komunikat dnia (czy można pryskać / nawozić / siać) */
    .day-banner {
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 16px;
        border: 1px solid;
    }
    .banner-go {
        background: var(--green-bg);
        border-color: var(--green-line);
        color: var(--ink);
    }
    .banner-wait {
        background: var(--amber-bg);
        border-color: var(--amber-line);
        color: var(--ink);
    }
    .banner-heading {
        font-size: 17px;
        font-weight: 700;
        margin: 0 0 3px 0;
    }
    .banner-text {
        font-size: 14px;
        color: var(--muted);
        margin: 0;
    }
    .banner-chip {
        font-size: 13px;
        font-weight: 700;
        padding: 7px 14px;
        border-radius: 999px;
        white-space: nowrap;
    }
    .chip-go {
        background: var(--green);
        color: #FFFFFF;
    }
    .chip-wait {
        background: var(--amber);
        color: #FFFFFF;
    }

    /* 4 proste kafelki na górze */
    .stat-row {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        margin-bottom: 16px;
    }
    .stat-box {
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 16px 18px;
    }
    .stat-label {
        font-size: 13px;
        font-weight: 600;
        color: var(--muted);
    }
    .stat-val {
        font-size: 26px;
        font-weight: 800;
        color: var(--ink);
        margin: 4px 0 2px 0;
        font-variant-numeric: tabular-nums;
    }
    .stat-hint {
        font-size: 12px;
        color: var(--muted);
    }

    /* Karta sekcji */
    .soft-card {
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 18px 20px;
        margin-bottom: 16px;
    }
    .soft-card-title {
        font-size: 17px;
        font-weight: 700;
        color: var(--ink);
        margin: 0 0 4px 0;
    }
    .soft-card-sub {
        font-size: 13px;
        color: var(--muted);
        margin: 0 0 14px 0;
    }

    /* Wiersze dziennika pogodowego */
    .note-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 14px;
        background: var(--card-soft);
        border: 1px solid var(--line);
        border-radius: 10px;
        margin-bottom: 8px;
    }
    .note-time {
        font-size: 14px;
        font-weight: 700;
        color: var(--ink);
    }
    .note-meta {
        font-size: 13px;
        color: var(--muted);
        margin-top: 2px;
    }
    .pill {
        font-size: 12px;
        font-weight: 700;
        padding: 5px 12px;
        border-radius: 999px;
    }
    .pill-ok { background: var(--green-bg); color: var(--green); }
    .pill-warn { background: var(--amber-bg); color: var(--amber); }
    .pill-bad { background: var(--red-bg); color: var(--red); }

    /* Karta polecanej uprawy */
    .crop-result {
        background: var(--green-bg);
        border: 1px solid var(--green-line);
        border-radius: 12px;
        padding: 18px 22px;
        margin-top: 14px;
    }
    .crop-tag {
        font-size: 12px;
        font-weight: 700;
        color: var(--green);
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .crop-name {
        font-size: 21px;
        font-weight: 800;
        color: var(--ink);
        margin: 4px 0 6px 0;
    }
    .crop-desc {
        font-size: 14px;
        color: var(--ink);
        margin: 0;
        line-height: 1.5;
    }

    /* Zakladki */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: transparent;
        border-bottom: 1px solid var(--line);
        padding-bottom: 8px;
        margin-bottom: 16px;
    }
    .stTabs [data-baseweb="tab"] {
        background: var(--card) !important;
        border: 1px solid var(--line) !important;
        border-radius: 9px !important;
        padding: 8px 16px !important;
        font-size: 14px !important;
        font-weight: 600 !important;
        color: var(--muted) !important;
    }
    .stTabs [aria-selected="true"] {
        background: var(--green) !important;
        border-color: var(--green) !important;
        color: #FFFFFF !important;
    }
    .stTabs [data-baseweb="tab-highlight"] {
        display: none !important;
    }

    div.stButton > button[kind="primary"], div.stDownloadButton > button {
        background-color: var(--green) !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 9px !important;
        font-weight: 600 !important;
        padding: 0.5rem 1.1rem !important;
    }
    div.stButton > button[kind="secondary"] {
        background-color: var(--card) !important;
        color: var(--ink) !important;
        border: 1px solid var(--line) !important;
        border-radius: 9px !important;
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

if "weather_journal" not in st.session_state:
    st.session_state.weather_journal = [
        {"czas": "Dziś, 19:00", "temp": 18.2, "opad": 0.0, "wiatr_ms": 2.4, "ocena": "ok", "etykieta": "Można pryskać"},
        {"czas": "Dziś, 13:00", "temp": 22.5, "opad": 0.0, "wiatr_ms": 5.3, "ocena": "warn", "etykieta": "Za mocno wieje"},
        {"czas": "Wczoraj, 07:30", "temp": 16.5, "opad": 14.2, "wiatr_ms": 2.2, "ocena": "bad", "etykieta": "Po deszczu — poczekać"},
    ]
if "saved_crops" not in st.session_state:
    st.session_state.saved_crops = {}

st.markdown(
    """
    <div class="farm-header">
        <div>
            <h1 class="farm-title">FieldGuard 33UXR</h1>
            <div class="farm-sub">Spokojny podgląd pogody, prac na polach i doboru upraw dla gospodarstwa</div>
        </div>
        <div class="farm-sub" style="text-align:right;">
            Region: <strong>33UXR</strong> &middot; Dane satelitarne i glebowe
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_pola, tab_siew, tab_kalk, tab_zasady = st.tabs(
    [
        "Pola i pogoda",
        "Doradca siewu",
        "Kalkulator nawozów i oprysku",
        "Zasady zabiegów",
    ]
)

with tab_pola:
    c_time, c_sim, c_exp, c_rst = st.columns([3.0, 1.4, 1.0, 0.9])
    with c_time:
        selected_ts = st.select_slider(
            "Wybierz godzinę:",
            options=timestamps,
            value=timestamps[min(7, len(timestamps) - 1)],
            format_func=lambda x: pd.to_datetime(x).strftime("%d.%m.%Y, %H:%M"),
        )
    with c_sim:
        st.write("")
        what_if = st.toggle("Sprawdź inną pogodę", value=False)
    with c_exp:
        st.write("")
        export_payload = fields_df.head(50).to_json(orient="records", force_ascii=False, indent=2)
        st.download_button(
            "Pobierz JSON",
            data=export_payload,
            file_name="pola_33uxr.json",
            mime="application/json",
            use_container_width=True,
        )
    with c_rst:
        st.write("")
        if st.button("Wyczyść", use_container_width=True):
            st.session_state.saved_crops = {}
            st.toast("Przywrócono ustawienia początkowe.")

    if what_if:
        w1, w2, w3 = st.columns(3)
        sim_temp = w1.slider("Temperatura (°C)", -5.0, 38.0, 19.0, 0.5)
        sim_wind = w2.slider("Wiatr (m/s)", 0.0, 15.0, 2.5, 0.1)
        sim_precip = w3.slider("Deszcz w ciągu 24h (mm)", 0.0, 30.0, 8.0, 0.5)
    else:
        sim_temp, sim_wind, sim_precip = 19.0, 2.5, 0.0

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

    total_fields = len(result_df)
    total_area_ha = total_fields * 1.50
    avg_humidity = float(result_df["humidity_pct"].mean()) if not result_df.empty else 0.0
    ready_fields = int(result_df["decyzja"].isin(["PRYSKAJ TERAZ", "NAWOŹ", "ZASIEJ"]).sum())
    avg_temp = float(result_df["temp_c"].mean()) if not result_df.empty else 0.0
    avg_wind = float(result_df["wind_ms"].mean()) if not result_df.empty else 0.0
    avg_precip = float(result_df["precip_24h_mm"].mean()) if not result_df.empty else 0.0

    can_work = (avg_wind <= 4.0) and (avg_precip < 5.0)
    banner_cls = "banner-go" if can_work else "banner-wait"
    chip_cls = "chip-go" if can_work else "chip-wait"
    if can_work:
        b_head = "Dobre warunki do wyjazdu w pole"
        b_desc = (
            f"Wiatr wynosi średnio {avg_wind:.1f} m/s, opady w ostatnich 24h to {avg_precip:.1f} mm, "
            f"a temperatura {avg_temp:.1f} °C. Na {ready_fields} z {total_fields} obszarów widać gotowość do zabiegu."
        )
        b_chip = "Można działać"
    else:
        powod = "zbyt silny wiatr (powyżej 4 m/s)" if avg_wind > 4.0 else "opady deszczu (ryzyko zmycia)"
        b_head = "Lepiej wstrzymać oprysk"
        b_desc = (
            f"Powód: {powod}. Wiatr: {avg_wind:.1f} m/s, opad 24h: {avg_precip:.1f} mm, temperatura: {avg_temp:.1f} °C."
        )
        b_chip = "Warto poczekać"

    st.markdown(
        f"""
        <div class="day-banner {banner_cls}">
            <div>
                <div class="banner-heading">{b_head}</div>
                <p class="banner-text">{b_desc}</p>
            </div>
            <div class="banner-chip {chip_cls}">{b_chip}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="stat-row">
            <div class="stat-box">
                <div class="stat-label">Obszary na mapie</div>
                <div class="stat-val">{total_fields}</div>
                <div class="stat-hint">Jednostki w regionie 33UXR</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Łączny areał (szac.)</div>
                <div class="stat-val">{total_area_ha:,.1f} ha</div>
                <div class="stat-hint">Ok. 1.5 ha na pojedynczy sektor</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Gotowe do prac</div>
                <div class="stat-val" style="color:#2E6F40;">{ready_fields} z {total_fields}</div>
                <div class="stat-hint">Oprysk, nawożenie lub siew</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Wiatr i wilgotność</div>
                <div class="stat-val">{avg_wind:.1f} m/s</div>
                <div class="stat-hint">Wilgotność powietrza: {avg_humidity:.0f}%</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    COLOR_MAP = {
        "PRYSKAJ TERAZ": [46, 111, 64, 215],
        "NAWOŹ": [126, 87, 162, 205],
        "ZASIEJ": [43, 122, 138, 205],
        "ZBIERAJ": [59, 110, 165, 205],
        "MONITORUJ": [196, 138, 36, 205],
        "CZEKAJ": [178, 58, 58, 215],
    }
    result_df["color"] = result_df["decyzja"].map(lambda d: COLOR_MAP.get(d, [130, 138, 132, 180]))

    col_map, col_chart = st.columns([1.4, 1.0], gap="medium")

    with col_map:
        st.markdown(
            """
            <div class="soft-card" style="margin-bottom:8px; padding-bottom:12px;">
                <div class="soft-card-title">Mapa pól</div>
                <div class="soft-card-sub" style="margin-bottom:0;">Najedź na wybrany sektor, aby zobaczyć uprawę, pogodę i zalecenie</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if "polygon_json" in result_df.columns and not result_df.empty:
            import json

            result_df = result_df.copy()
            result_df["polygon"] = result_df["polygon_json"].map(json.loads)
            layer = pdk.Layer(
                "PolygonLayer",
                data=result_df,
                pickable=True,
                stroked=True,
                filled=True,
                extruded=False,
                get_polygon="polygon",
                get_fill_color="color",
                get_line_color=[45, 55, 48],
                line_width_min_pixels=1,
            )
            default_zoom = 11.2
        else:
            layer = pdk.Layer(
                "H3HexagonLayer",
                data=result_df,
                pickable=True,
                stroked=True,
                filled=True,
                extruded=False,
                get_hexagon="h3_index",
                get_fill_color="color",
                get_line_color=[45, 55, 48],
                line_width_min_pixels=1,
            )
            default_zoom = 8.5

        view_state = pdk.ViewState(
            latitude=float(result_df["lat"].mean()) if not result_df.empty else 50.18,
            longitude=float(result_df["lon"].mean()) if not result_df.empty else 20.35,
            zoom=default_zoom,
            pitch=0,
        )

        deck = pdk.Deck(
            map_style="light",
            layers=[layer],
            initial_view_state=view_state,
            tooltip={
                "html": "<div style='font-family:Plus Jakarta Sans,sans-serif;font-size:12px;line-height:1.5;'>"
                "<b>Uprawa:</b> {crop_name} (NDVI: {ndvi})<br/>"
                "<b>Zalecenie:</b> {decyzja} ({poziom_ryzyka})<br/>"
                "<b>Uwagi:</b> {komunikat}<br/>"
                "<b>Nawóz:</b> {zalecany_nawoz} | <b>Siew:</b> {rekomendowana_uprawa}<br/>"
                "<b>Gleba:</b> pH {soil_ph}, próchnica/SOC {soil_soc} g/kg ({soil_texture})<br/>"
                "<b>Pogoda:</b> wiatr {wind_ms} m/s, temp. {temp_c} °C, deszcz 24h {precip_24h_mm} mm"
                "</div>",
                "style": {
                    "backgroundColor": "#1F2924",
                    "color": "#FFFFFF",
                    "borderRadius": "8px",
                },
            },
        )
        st.pydeck_chart(deck, use_container_width=True)
        st.caption(
            "Kolory na mapie: zielony — można pryskać | fioletowy — nawozić | "
            "niebiesko-zielony — siać | niebieski — zbierać | żółty — obserwować | czerwony — poczekać."
        )

    with col_chart:
        st.markdown(
            """
            <div class="soft-card" style="margin-bottom:8px; padding-bottom:12px;">
                <div class="soft-card-title">Siła wiatru na przykładowych polach</div>
                <div class="soft-card-sub" style="margin-bottom:0;">Przerywana linia oznacza bezpieczny próg 4,0 m/s do oprysku</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        sample_fields = result_df.head(7).copy()
        sample_fields["nazwa"] = [f"Pole {i+1}" for i in range(len(sample_fields))]
        sample_fields["stan"] = sample_fields["wind_ms"].apply(
            lambda w: "Za mocno wieje" if w > 4.0 else "Spokojny wiatr"
        )
        fig_w = px.bar(
            sample_fields,
            x="nazwa",
            y="wind_ms",
            text="wind_ms",
            color="stan",
            color_discrete_map={"Spokojny wiatr": "#2E6F40", "Za mocno wieje": "#B23A3A"},
            labels={"nazwa": "", "wind_ms": "Wiatr (m/s)", "stan": ""},
        )
        fig_w.update_traces(texttemplate="%{text:.1f} m/s", textposition="outside")
        fig_w.add_hline(y=4.0, line_dash="dash", line_color="#9A5B13", annotation_text="Próg 4,0 m/s")
        fig_w.update_layout(
            font=dict(family="Plus Jakarta Sans, sans-serif", size=12, color="#1F2924"),
            plot_bgcolor="#FFFFFF",
            paper_bgcolor="#FFFFFF",
            showlegend=False,
            height=330,
            margin=dict(t=24, b=20, l=10, r=10),
            yaxis=dict(
                gridcolor="#EFECE6",
                range=[0, max(7.0, float(sample_fields["wind_ms"].max()) + 1.4) if not sample_fields.empty else 7.0],
            ),
        )
        st.plotly_chart(fig_w, use_container_width=True)

    st.write("")
    st.markdown(
        """
        <div class="soft-card" style="margin-bottom:10px; padding-bottom:12px;">
            <div class="soft-card-title">Notatnik pogodowy</div>
            <div class="soft-card-sub" style="margin-bottom:0;">Możesz zapisać własny odczyt z pola i szybko sprawdzić, czy warunki sprzyjają zabiegowi</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    j1, j2, j3, j4 = st.columns([1.2, 1.2, 1.2, 1.0])
    in_temp = j1.number_input("Temperatura (°C)", value=18.5, step=0.5, key="农_t")
    in_rain = j2.number_input("Deszcz (mm)", value=0.0, step=0.5, key="农_r")
    in_wind_kmh = j3.number_input("Wiatr (km/h)", value=11.0, step=1.0, key="农_w")
    with j4:
        st.write("")
        st.write("")
        if st.button("Dodaj wpis", type="primary", use_container_width=True):
            w_ms = in_wind_kmh / 3.6
            if in_rain >= 5.0:
                ocena, etykieta = "bad", "Po deszczu — poczekać"
            elif w_ms > 4.0:
                ocena, etykieta = "warn", "Za mocno wieje"
            else:
                ocena, etykieta = "ok", "Można pryskać"
            st.session_state.weather_journal.insert(
                0,
                {
                    "czas": f"Wpis ({pd.to_datetime(selected_ts).strftime('%H:%M')})",
                    "temp": in_temp,
                    "opad": in_rain,
                    "wiatr_ms": round(w_ms, 1),
                    "ocena": ocena,
                    "etykieta": etykieta,
                },
            )

    for entry in st.session_state.weather_journal[:5]:
        p_cls = "pill-ok" if entry["ocena"] == "ok" else ("pill-bad" if entry["ocena"] == "bad" else "pill-warn")
        st.markdown(
            f"""
            <div class="note-row">
                <div>
                    <div class="note-time">{entry['czas']}</div>
                    <div class="note-meta">Temperatura: <b>{entry['temp']} °C</b> &middot; Deszcz: <b>{entry['opad']} mm</b> &middot; Wiatr: <b>{round(entry['wiatr_ms']*3.6)} km/h</b> ({entry['wiatr_ms']} m/s)</div>
                </div>
                <div class="pill {p_cls}">{entry['etykieta']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")
    with st.expander("Pokaż pełną listę obszarów i zaleceń"):
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
        st.dataframe(result_df[display_cols], use_container_width=True, hide_index=True)

with tab_siew:
    st.markdown(
        """
        <div class="soft-card">
            <div class="soft-card-title">Doradca siewu — co najlepiej dopasować do gleby</div>
            <div class="soft-card-sub" style="margin-bottom:0;">Wybierz obszar z mapy albo ustaw ręcznie odczyn pH i rodzaj gleby, aby zobaczyć podpowiedź</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    mode = st.radio(
        "Skąd wziąć dane o glebie?",
        ["Z wybranego obszaru na mapie", "Wpiszę własne parametry"],
        horizontal=True,
    )

    if mode == "Z wybranego obszaru na mapie" and not result_df.empty:
        c1, c2 = st.columns(2)
        with c1:
            selected_h3 = st.selectbox(
                "Wybierz obszar:",
                options=result_df["h3_index"].tolist(),
                format_func=lambda h: (
                    f"Obszar {h} (obecnie: {result_df.loc[result_df['h3_index'] == h, 'crop_name'].values[0]})"
                ),
            )
        row_s = result_df[result_df["h3_index"] == selected_h3].iloc[0]
        with c2:
            st.text_input(
                "Rodzaj gleby i próchnica (SOC):",
                value=f"{row_s['soil_texture']} · SOC {row_s['soil_soc']:.1f} g/kg",
                disabled=True,
            )
        sc1, sc2 = st.columns(2)
        in_ph = sc1.slider("Odczyn gleby (pH):", 4.0, 8.0, float(row_s["soil_ph"]), 0.1)
        in_hum = sc2.slider("Wilgotność (%):", 10, 95, int(row_s["humidity_pct"]), 1)
        in_soc = float(row_s["soil_soc"])
        in_tex = str(row_s["soil_texture"])
        target_label = f"obszaru {selected_h3}"
    else:
        c1, c2 = st.columns(2)
        with c1:
            in_tex = st.selectbox(
                "Rodzaj gleby:",
                ["Loam", "Silt Loam", "Clay Loam", "Sandy Loam", "Sand"],
            )
        with c2:
            in_soc = st.slider("Zawartość próchnicy / SOC (g/kg):", 5.0, 35.0, 18.0, 0.5)
        sc1, sc2 = st.columns(2)
        in_ph = sc1.slider("Odczyn gleby (pH):", 4.0, 8.0, 6.6, 0.1)
        in_hum = sc2.slider("Wilgotność (%):", 10, 95, 68, 1)
        selected_h3 = "wlasne"
        target_label = "wybranych ustawień"

    rec_crop, rec_reason = recommend_crop_by_soil(in_ph, in_soc, in_tex, crop_dict_df=crop_dict_df)
    st.markdown(
        f"""
        <div class="crop-result">
            <div class="crop-tag">Podpowiedź dla {target_label}</div>
            <div class="crop-name">Najlepiej pasuje: {rec_crop}</div>
            <p class="crop-desc">{rec_reason}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    if st.button("Zapisz wybór uprawy", type="primary"):
        st.session_state.saved_crops[selected_h3] = rec_crop
        st.success(f"Zapisano uprawę: {rec_crop}.")

with tab_kalk:
    st.markdown(
        """
        <div class="soft-card">
            <div class="soft-card-title">Kalkulator nawozów i oprysku</div>
            <div class="soft-card-sub" style="margin-bottom:0;">Szybkie przeliczenie ilości preparatu i wody na wybrany areał</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    k1, k2, k3 = st.columns(3)
    area_ha = k1.number_input("Powierzchnia pola (ha):", min_value=0.1, max_value=5000.0, value=15.0, step=0.5)
    dose_ha = k2.number_input("Dawka na 1 ha (kg lub l):", min_value=0.05, max_value=2000.0, value=1.5, step=0.1)
    water_ha = k3.number_input("Woda na 1 ha przy oprysku (l):", min_value=0.0, max_value=600.0, value=200.0, step=10.0)

    st.markdown(
        f"""
        <div class="crop-result">
            <div class="crop-tag">Podsumowanie dla {area_ha:.1f} ha</div>
            <div class="crop-name">Potrzebujesz: {area_ha * dose_ha:,.2f} kg (lub l)</div>
            <p class="crop-desc">
                Przy dawce <b>{dose_ha:.2f} / ha</b>. Łącznie do opryskiwacza wejdzie około <b>{area_ha * water_ha:,.0f} l</b> wody.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

with tab_zasady:
    st.markdown(
        """
        <div class="soft-card">
            <div class="soft-card-title">Zasady podejmowania decyzji</div>
            <div class="soft-card-sub" style="margin-bottom:0;">Tabela reguł pogodowych, glebowych i zabiegowych używana przez aplikację</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.dataframe(rules_df, use_container_width=True, hide_index=True)