import json
import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

from silnik_regul import (
    FALLOW_LABEL,
    KNOWN_CROPS,
    apply_farm_profile,
    evaluate_fields,
    load_admin_hierarchy,
    load_agronomic_rules,
    load_farm_profile,
    load_optional_crop_recommendations,
    load_static_fields,
    load_weather_timeseries,
    recommend_crop_by_soil,
    recommend_fertilization,
    save_farm_profile,
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

    /* Glówny komunikat dnia */
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

    /* Karta polecanej uprawy / nawożenia */
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
        load_admin_hierarchy(),
    )


raw_fields_df, weather_df, rules_df, crop_dict_df, admin_hierarchy = get_base_data()
timestamps = sorted(weather_df["timestamp"].unique())

if "farm_profile" not in st.session_state:
    st.session_state.farm_profile = load_farm_profile()

if "weather_journal" not in st.session_state:
    st.session_state.weather_journal = [
        {"czas": "Dziś, 19:00", "temp": 18.2, "opad": 0.0, "wiatr_ms": 2.4, "ocena": "ok", "etykieta": "Można pryskać"},
        {"czas": "Dziś, 13:00", "temp": 22.5, "opad": 0.0, "wiatr_ms": 5.3, "ocena": "warn", "etykieta": "Za mocno wieje"},
        {"czas": "Wczoraj, 07:30", "temp": 16.5, "opad": 14.2, "wiatr_ms": 2.2, "ocena": "bad", "etykieta": "Po deszczu — poczekać"},
    ]
if "saved_crops" not in st.session_state:
    st.session_state.saved_crops = {}

farm_profile = st.session_state.farm_profile
saved_fields_dict = farm_profile.get("fields", {})
my_fields_count = len(saved_fields_dict)
eco_fields_count = sum(1 for v in saved_fields_dict.values() if bool(v.get("is_eco", False)))
farm_label = farm_profile.get("farm_name") or "Moje Gospodarstwo"
eco_active = bool(farm_profile.get("eco_mode", False))
mode_badge = "Rolnictwo EKO" if (eco_active or eco_fields_count > 0) else "Tryb konwencjonalny"
loc_summary = (
    f"{farm_profile.get('wojewodztwo', 'Małopolskie')} · "
    f"pow. {farm_profile.get('powiat', 'proszowicki')} · "
    f"gm. {farm_profile.get('gmina', 'Wszystkie gminy (33UXR)')}"
)

st.markdown(
    f"""
    <div class="farm-header">
        <div>
            <h1 class="farm-title">FieldGuard 33UXR</h1>
            <div class="farm-sub">Spokojny podgląd pogody, prac na polach i doboru upraw dla gospodarstwa</div>
        </div>
        <div class="farm-sub" style="text-align:right;">
            <strong>{farm_label}</strong> ({my_fields_count} działek &middot; EKO: {eco_fields_count}) &middot; <strong>{mode_badge}</strong><br/>
            <span>{loc_summary}</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

fields_df = apply_farm_profile(raw_fields_df, farm_profile, crop_dict_df=crop_dict_df)

tab_pola, tab_gosp, tab_siew, tab_kalk, tab_eko_doc, tab_zasady = st.tabs(
    [
        "Pola i pogoda",
        "Moje Gospodarstwo",
        "Doradca siewu",
        "Kalkulator nawozów i oprysku",
        "Dokumentacja EKO i Audyt",
        "Zasady zabiegów",
    ]
)

with tab_pola:
    c_time, c_sim, c_eco, c_scope = st.columns([2.9, 1.3, 1.3, 1.3])
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
    with c_eco:
        st.write("")
        new_eco = st.toggle(
            "Tryb rolnictwa EKO",
            value=eco_active,
            help="Włącza nawożenie ekologiczne dla całego gospodarstwa (niezależnie od pojedynczych działek EKO).",
        )
        if new_eco != eco_active:
            farm_profile["eco_mode"] = new_eco
            save_farm_profile(farm_profile)
            st.rerun()
    with c_scope:
        st.write("")
        only_mine = st.toggle(
            "Tylko moje pola",
            value=bool(farm_profile.get("only_my_farm", False)),
            disabled=(my_fields_count == 0),
            help="Najpierw zaznacz swoje działki w zakładce Moje Gospodarstwo.",
        )
        if only_mine != bool(farm_profile.get("only_my_farm", False)):
            farm_profile["only_my_farm"] = only_mine
            save_farm_profile(farm_profile)
            st.rerun()

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
        eco_mode=eco_active,
    )

    total_fields = len(result_df)
    if "area_ha" in result_df.columns and not result_df.empty:
        total_area_ha = float(result_df["area_ha"].sum())
        area_label = "Łączny areał pól"
        area_hint = f"Średnio {float(result_df['area_ha'].mean()):.1f} ha na pojedyncze pole"
    else:
        total_area_ha = total_fields * 1.50
        area_label = "Łączny areał (szac.)"
        area_hint = "Ok. 1.5 ha na pojedynczy sektor"

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

    scope_hint = (
        "Wyłącznie pola Mojego Gospodarstwa"
        if (only_mine and my_fields_count > 0)
        else "Jednostki w regionie 33UXR"
    )
    st.markdown(
        f"""
        <div class="stat-row">
            <div class="stat-box">
                <div class="stat-label">Obszary na mapie</div>
                <div class="stat-val">{total_fields}</div>
                <div class="stat-hint">{scope_hint}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">{area_label}</div>
                <div class="stat-val">{total_area_ha:,.1f} ha</div>
                <div class="stat-hint">{area_hint}</div>
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
                <div class="soft-card-sub" style="margin-bottom:0;">Najedź na wybrane pole, aby zobaczyć uprawę, nawóz EKO, pogodę i zalecenie</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if "polygon_json" in result_df.columns and not result_df.empty:
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
            default_zoom = 11.4 if (only_mine and my_fields_count > 0) else 11.0
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
                "<b>Działka:</b> {field_uid} ({area_ha} ha)<br/>"
                "<b>Uprawa:</b> {crop_name} (NDVI: {ndvi})<br/>"
                "<b>Zalecenie:</b> {decyzja} ({poziom_ryzyka})<br/>"
                "<b>Uwagi:</b> {komunikat}<br/>"
                "<b>Nawóz:</b> {zalecany_nawoz} ({dawka_nawozu_kg_ha} kg/ha · {ilosc_nawozu_kg} kg) | <b>EKO:</b> {nawozy_eko}<br/>"
                "<b>Siew:</b> {rekomendowana_uprawa}<br/>"
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
        sample_fields["nazwa"] = sample_fields["field_uid"].tolist()
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
    in_temp = j1.number_input("Temperatura (°C)", value=18.5, step=0.5, key="journal_t")
    in_rain = j2.number_input("Deszcz (mm)", value=0.0, step=0.5, key="journal_r")
    in_wind_kmh = j3.number_input("Wiatr (km/h)", value=11.0, step=1.0, key="journal_w")
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
    display_cols = [
        col
        for col in [
            "field_uid",
            "is_eco_field",
            "h3_index",
            "rule_id",
            "crop_name",
            "ndvi",
            "decyzja",
            "poziom_ryzyka",
            "zalecany_nawoz",
            "nawozy_eko",
            "dawka_nawozu_kg_ha",
            "ilosc_nawozu_kg",
            "rekomendowana_uprawa",
            "komunikat",
        ]
        if col in result_df.columns
    ]
    st.dataframe(result_df[display_cols], use_container_width=True, hide_index=True)

with tab_gosp:
    st.markdown(
        """
        <div class="soft-card">
            <div class="soft-card-title">Konfiguracja Mojego Gospodarstwa</div>
            <div class="soft-card-sub" style="margin-bottom:0;">
                1. Wybierz lokalizację &nbsp;&rarr;&nbsp; 2. Zaznacz własne działki oraz opcję „Działka EKO” (do doboru nawozów i dokumentacji) &nbsp;&rarr;&nbsp;
                3. Zatwierdź uprawę albo wybierz „Brak uprawy / Pod zasiew”
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    g_col1, g_col2, g_col3, g_col4 = st.columns([1.3, 1.1, 1.1, 1.3])
    with g_col1:
        farm_name_input = st.text_input(
            "Nazwa gospodarstwa:",
            value=farm_profile.get("farm_name", "Moje Gospodarstwo"),
        )
    woj_options = list(admin_hierarchy.keys())
    default_woj = farm_profile.get("wojewodztwo", woj_options[0])
    if default_woj not in woj_options:
        default_woj = woj_options[0]
    with g_col2:
        sel_woj = st.selectbox("Województwo:", woj_options, index=woj_options.index(default_woj))

    pow_options = list(admin_hierarchy[sel_woj].keys())
    default_pow = farm_profile.get("powiat", pow_options[0])
    if default_pow not in pow_options:
        default_pow = pow_options[0]
    with g_col3:
        sel_pow = st.selectbox("Powiat:", pow_options, index=pow_options.index(default_pow))

    gmina_entries = admin_hierarchy[sel_woj][sel_pow]
    gmina_names = [g["gmina"] for g in gmina_entries]
    default_gmina = farm_profile.get("gmina", gmina_names[0])
    if default_gmina not in gmina_names:
        default_gmina = gmina_names[0]
    with g_col4:
        sel_gmina = st.selectbox("Gmina:", gmina_names, index=gmina_names.index(default_gmina))

    active_bbox = next(g["bbox"] for g in gmina_entries if g["gmina"] == sel_gmina)

    candidates_df = raw_fields_df[
        (raw_fields_df["lon"] >= active_bbox[0])
        & (raw_fields_df["lon"] <= active_bbox[2])
        & (raw_fields_df["lat"] >= active_bbox[1])
        & (raw_fields_df["lat"] <= active_bbox[3])
    ].copy()
    if candidates_df.empty:
        st.info("Dla wybranej gminy nie ma jeszcze dociętych poligonów w lokalnym kaflu — pokazuję wszystkie dostępne pola z 33UXR.")
        candidates_df = raw_fields_df.copy()

    saved_map = farm_profile.get("fields", {})

    editor_rows = []
    for r in candidates_df.itertuples(index=False):
        uid = r.field_uid
        is_mine = uid in saved_map
        is_eco_val = bool(saved_map[uid].get("is_eco", eco_active)) if is_mine else eco_active
        declared_crop = saved_map[uid]["crop_name"] if is_mine else str(r.crop_name)
        if declared_crop not in KNOWN_CROPS:
            declared_crop = str(r.crop_name)
        rec_crop, rec_why = recommend_crop_by_soil(
            r.soil_ph, r.soil_soc, r.soil_texture, crop_dict_df=crop_dict_df
        )
        area_val = float(getattr(r, "area_ha", 1.5))
        editor_rows.append(
            {
                "Moje pole": is_mine,
                "Działka EKO": is_eco_val,
                "Działka": uid,
                "Powierzchnia (ha)": round(area_val, 2),
                "Deklarowana uprawa": declared_crop,
                "Uprawa z satelity (CLMS)": str(r.crop_name),
                "Gleba (pH / tekstura)": f"pH {r.soil_ph:.1f} · {r.soil_texture}",
                "Podpowiedź siewu (dla ugorów)": f"{rec_crop} — {rec_why}",
            }
        )

    editor_df = pd.DataFrame(editor_rows)
    crop_choices = sorted(list(set(KNOWN_CROPS + candidates_df["crop_name"].dropna().astype(str).tolist())))

    map_prev_col, table_cfg_col = st.columns([1.0, 1.45], gap="medium")

    with map_prev_col:
        st.markdown("**Podgląd działek w wybranej gminie**")
        preview_df = candidates_df.copy()
        preview_df["is_selected"] = preview_df["field_uid"].isin(saved_map.keys())
        preview_df["is_eco_saved"] = preview_df["field_uid"].map(
            lambda u: bool(saved_map.get(u, {}).get("is_eco", False))
        )

        def _prev_color(row_s):
            if row_s["is_selected"] and row_s["is_eco_saved"]:
                return [46, 111, 64, 235]
            if row_s["is_selected"]:
                return [59, 110, 165, 220]
            return [180, 176, 168, 120]

        preview_df["prev_color"] = preview_df.apply(_prev_color, axis=1)
        if "polygon_json" in preview_df.columns and not preview_df.empty:
            preview_df["polygon"] = preview_df["polygon_json"].map(json.loads)
            prev_layer = pdk.Layer(
                "PolygonLayer",
                data=preview_df,
                pickable=True,
                stroked=True,
                filled=True,
                get_polygon="polygon",
                get_fill_color="prev_color",
                get_line_color=[31, 41, 36],
                line_width_min_pixels=1,
            )
            prev_zoom = 11.4
        else:
            prev_layer = pdk.Layer(
                "H3HexagonLayer",
                data=preview_df,
                pickable=True,
                stroked=True,
                filled=True,
                get_hexagon="h3_index",
                get_fill_color="prev_color",
                get_line_color=[31, 41, 36],
                line_width_min_pixels=1,
            )
            prev_zoom = 9.0

        prev_deck = pdk.Deck(
            map_style="light",
            layers=[prev_layer],
            initial_view_state=pdk.ViewState(
                latitude=float(preview_df["lat"].mean()),
                longitude=float(preview_df["lon"].mean()),
                zoom=prev_zoom,
            ),
            tooltip={
                "html": "<b>{field_uid}</b> ({area_ha} ha)<br/>Uprawa CLMS: {crop_name}<br/>pH: {soil_ph} · {soil_texture}",
                "style": {"backgroundColor": "#1F2924", "color": "#FFFFFF", "borderRadius": "8px"},
            },
        )
        st.pydeck_chart(prev_deck, use_container_width=True)
        st.caption("Zielony — działki zapisane jako EKO | Niebieski — pozostałe zapisane działki | Szary — nieprzypisane.")

    with table_cfg_col:
        st.markdown("**Zaznacz swoje działki, status EKO i przypisz uprawy**")
        edited_df = st.data_editor(
            editor_df,
            use_container_width=True,
            hide_index=True,
            height=360,
            column_config={
                "Moje pole": st.column_config.CheckboxColumn("Moje pole", default=False),
                "Działka EKO": st.column_config.CheckboxColumn(
                    "Działka EKO",
                    default=False,
                    help="Oznacza działkę jako ekologiczną (do doboru nawozów EKO i wyboru działek do dokumentacji).",
                ),
                "Działka": st.column_config.TextColumn("Działka", disabled=True),
                "Powierzchnia (ha)": st.column_config.NumberColumn("Pow. (ha)", disabled=True, format="%.2f"),
                "Deklarowana uprawa": st.column_config.SelectboxColumn(
                    "Deklarowana uprawa",
                    options=crop_choices,
                    required=True,
                    help="Wybierz uprawę albo ustaw 'Brak uprawy / Pod zasiew', aby otrzymać rekomendację z gleby.",
                ),
                "Uprawa z satelity (CLMS)": st.column_config.TextColumn("CLMS", disabled=True),
                "Gleba (pH / tekstura)": st.column_config.TextColumn("Gleba", disabled=True),
                "Podpowiedź siewu (dla ugorów)": st.column_config.TextColumn("Podpowiedź siewu", disabled=True),
            },
            key="farm_fields_editor",
        )

    selected_rows = edited_df[edited_df["Moje pole"] == True]
    eco_selected_rows = selected_rows[selected_rows["Działka EKO"] == True]
    sel_ha = float(selected_rows["Powierzchnia (ha)"].sum()) if not selected_rows.empty else 0.0
    eco_ha = float(eco_selected_rows["Powierzchnia (ha)"].sum()) if not eco_selected_rows.empty else 0.0
    fallow_rows = selected_rows[selected_rows["Deklarowana uprawa"] == FALLOW_LABEL]

    b_save, b_filter, b_clear = st.columns([1.4, 1.5, 1.0])
    with b_save:
        if st.button("Zapisz profil gospodarstwa", type="primary", use_container_width=True):
            new_fields_map = {}
            for _, row in selected_rows.iterrows():
                new_fields_map[row["Działka"]] = {
                    "crop_name": row["Deklarowana uprawa"],
                    "area_ha": float(row["Powierzchnia (ha)"]),
                    "is_eco": bool(row["Działka EKO"]),
                }
            updated_profile = {
                "farm_name": farm_name_input.strip() or "Moje Gospodarstwo",
                "wojewodztwo": sel_woj,
                "powiat": sel_pow,
                "gmina": sel_gmina,
                "only_my_farm": True if new_fields_map else False,
                "eco_mode": eco_active,
                "fields": new_fields_map,
            }
            st.session_state.farm_profile = updated_profile
            save_farm_profile(updated_profile)
            st.toast(
                f"Zapisano profil ({len(new_fields_map)} działek, {sel_ha:.2f} ha; EKO: {len(eco_selected_rows)} działek, {eco_ha:.2f} ha)."
            )
            st.rerun()

    with b_filter:
        st.markdown(
            f"<div style='padding-top:8px; font-size:13px; color:#5A655F;'>"
            f"Zaznaczono: <b>{len(selected_rows)} działek</b> ({sel_ha:.2f} ha) &middot; "
            f"EKO: <b>{len(eco_selected_rows)}</b> ({eco_ha:.2f} ha)</div>",
            unsafe_allow_html=True,
        )

    with b_clear:
        if st.button("Wyczyść wybór", use_container_width=True):
            cleared = {
                "farm_name": farm_name_input.strip() or "Moje Gospodarstwo",
                "wojewodztwo": sel_woj,
                "powiat": sel_pow,
                "gmina": sel_gmina,
                "only_my_farm": False,
                "eco_mode": eco_active,
                "fields": {},
            }
            st.session_state.farm_profile = cleared
            save_farm_profile(cleared)
            st.rerun()

    if not fallow_rows.empty:
        st.markdown(
            """
            <div class="soft-card" style="margin-top:14px; margin-bottom:8px; padding-bottom:12px;">
                <div class="soft-card-title">Rekomendacje siewu dla Twoich pól nieobsianych</div>
                <div class="soft-card-sub" style="margin-bottom:0;">
                    Dla działek oznaczonych jako „Brak uprawy / Pod zasiew” dobrano gatunek na podstawie pH, próchnicy (SOC) i uziarnienia gleby
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        for _, fr in fallow_rows.iterrows():
            uid = fr["Działka"]
            raw_row = candidates_df[candidates_df["field_uid"] == uid].iloc[0]
            rec_c, rec_r = recommend_crop_by_soil(
                raw_row["soil_ph"], raw_row["soil_soc"], raw_row["soil_texture"], crop_dict_df=crop_dict_df
            )
            eco_tag = " · EKO" if bool(fr["Działka EKO"]) else ""
            st.markdown(
                f"""
                <div class="crop-result" style="margin-top:8px; padding:14px 18px;">
                    <div class="crop-tag">Działka {uid}{eco_tag} &middot; {float(fr['Powierzchnia (ha)']):.2f} ha &middot; {fr['Gleba (pH / tekstura)']}</div>
                    <div class="crop-name" style="font-size:18px;">Zalecany zasiew: {rec_c}</div>
                    <p class="crop-desc">{rec_r}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

with tab_siew:
    st.markdown(
        """
        <div class="soft-card">
            <div class="soft-card-title">Doradca siewu — co najlepiej dopasować do gleby</div>
            <div class="soft-card-sub" style="margin-bottom:0;">Wybierz działkę z mapy albo ustaw ręcznie odczyn pH i rodzaj gleby, aby zobaczyć podpowiedź</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    mode = st.radio(
        "Skąd wziąć dane o glebie?",
        ["Z wybranej działki na mapie", "Wpiszę własne parametry"],
        horizontal=True,
    )

    if mode == "Z wybranej działki na mapie" and not result_df.empty:
        c1, c2 = st.columns(2)
        with c1:
            selected_uid = st.selectbox(
                "Wybierz działkę:",
                options=result_df["field_uid"].tolist(),
                format_func=lambda u: (
                    f"{u} (obecnie: {result_df.loc[result_df['field_uid'] == u, 'crop_name'].values[0]})"
                ),
            )
        row_s = result_df[result_df["field_uid"] == selected_uid].iloc[0]
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
        target_label = f"działki {selected_uid}"
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
        selected_uid = "wlasne"
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
        st.session_state.saved_crops[selected_uid] = rec_crop
        st.success(f"Zapisano uprawę: {rec_crop}.")

with tab_kalk:
    st.markdown(
        """
        <div class="soft-card">
            <div class="soft-card-title">Kalkulator nawozów i oprysku</div>
            <div class="soft-card-sub" style="margin-bottom:0;">Dobór nawozu (w tym status EKO), przeliczenie ilości na pole oraz wody do oprysku</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    default_calc_area = (
        float(result_df["area_ha"].sum())
        if ("area_ha" in result_df.columns and only_mine and my_fields_count > 0)
        else 15.0
    )
    default_calc_crop = (
        str(result_df["crop_name"].iloc[0])
        if (not result_df.empty and only_mine and my_fields_count > 0)
        else "Pszenica ozima"
    )
    default_calc_ph = float(result_df["soil_ph"].mean()) if not result_df.empty else 6.2
    default_calc_soc = float(result_df["soil_soc"].mean()) if not result_df.empty else 16.0
    default_calc_tex = str(result_df["soil_texture"].mode().iloc[0]) if not result_df.empty else "Loam"

    k1, k2, k3, k4 = st.columns(4)
    area_ha = k1.number_input("Powierzchnia pola (ha):", min_value=0.1, max_value=5000.0, value=max(0.1, round(default_calc_area, 2)), step=0.5)
    calc_crop = k2.selectbox("Uprawa:", [c for c in KNOWN_CROPS if c != FALLOW_LABEL], index=0 if default_calc_crop not in KNOWN_CROPS else [c for c in KNOWN_CROPS if c != FALLOW_LABEL].index(default_calc_crop) if default_calc_crop != FALLOW_LABEL else 0)
    dose_ha = k3.number_input("Dawka na 1 ha (kg lub l):", min_value=0.05, max_value=2000.0, value=180.0, step=10.0)
    water_ha = k4.number_input("Woda na 1 ha przy oprysku (l):", min_value=0.0, max_value=600.0, value=200.0, step=10.0)

    fert_auto = recommend_fertilization(
        soil_ph=default_calc_ph,
        soil_soc=default_calc_soc,
        soil_texture=default_calc_tex,
        crop_name=calc_crop,
        area_ha=area_ha,
        temp_c=avg_temp,
        precip_24h_mm=avg_precip,
        rule_dose_kg_ha=dose_ha,
        eco_mode=eco_active,
    )

    st.markdown(
        f"""
        <div class="crop-result">
            <div class="crop-tag">Podsumowanie dla {area_ha:.1f} ha &middot; Status EKO: {fert_auto['nawozy_eko']}</div>
            <div class="crop-name">Zalecany nawóz: {fert_auto['zalecany_nawoz']} ({area_ha * dose_ha:,.1f} kg / l łącznie)</div>
            <p class="crop-desc">
                Dawka zadana: <b>{dose_ha:,.1f} / ha</b> &middot; Szacunek glebowy: <b>{fert_auto['dawka_nawozu_kg_ha']:,.0f} kg/ha</b> ({fert_auto['ilosc_nawozu_kg']:,.0f} kg na pole).
                Łącznie do opryskiwacza wejdzie około <b>{area_ha * water_ha:,.0f} l</b> wody.<br/>
                <em>{fert_auto['uzasadnienie_nawozenia']}</em>
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

with tab_eko_doc:
    from eko_dokumentacja import render_eko_documentation_tab

    render_eko_documentation_tab(
        result_df=result_df,
        selected_timestamp=selected_ts,
        location_label=f"{sel_woj}, pow. {sel_pow}, gm. {sel_gmina}",
    )