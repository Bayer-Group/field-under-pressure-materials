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

st.set_page_config(page_title="FieldGuard 33UXR — Asystent Decyzji Polowych", layout="wide")


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

st.title("FieldGuard 33UXR — Interaktywny Asystent Decyzji Polowych i Doradca Siewny")

with st.sidebar:
    st.header("Sterowanie czasem")
    selected_ts = st.select_slider(
        "Oś czasu (krok co 1h)",
        options=timestamps,
        value=timestamps[min(7, len(timestamps) - 1)],
        format_func=lambda x: pd.to_datetime(x).strftime("%Y-%m-%d %H:%M"),
    )

    st.divider()
    st.header("Tryb Symulacji „What-If”")
    what_if = st.toggle("Włącz ręczną pogodę (What-If)", value=False)
    sim_temp = st.slider("Temperatura (°C)", -5.0, 38.0, 19.0, 0.5, disabled=not what_if)
    sim_wind = st.slider("Wiatr (m/s)", 0.0, 15.0, 2.5, 0.1, disabled=not what_if)
    sim_precip = st.slider("Opad 24h (mm)", 0.0, 30.0, 0.0, 0.5, disabled=not what_if)

    st.divider()
    st.header("Filtry widoku")
    all_crops = sorted(fields_df["crop_name"].dropna().unique().tolist())
    selected_crops = st.multiselect("Uprawa", options=all_crops, default=all_crops)

    st.divider()
    st.markdown("**Legenda statusów (v2.0):**")
    st.markdown(
        "🟢 `PRYSKAJ TERAZ` | 🟣 `NAWOŹ` | 🩵 `ZASIEJ`  \n"
        "🔵 `ZBIERAJ` | 🟡 `MONITORUJ` | 🔴 `CZEKAJ`"
    )

if what_if:
    st.warning(
        f"⚠️ **TRYB SYMULACJI „WHAT-IF” AKTYWNY** — nadpisano odczyty pogodowe "
        f"(Temp: {sim_temp:.1f} °C | Wiatr: {sim_wind:.1f} m/s | Opad 24h: {sim_precip:.1f} mm)"
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

if selected_crops:
    result_df = result_df[result_df["crop_name"].isin(selected_crops)].copy()

COLOR_MAP = {
    "PRYSKAJ TERAZ": [34, 197, 94, 195],   # Zielony
    "NAWOŹ": [168, 85, 247, 195],          # Fioletowy
    "ZASIEJ": [6, 182, 212, 195],          # Turkusowy
    "ZBIERAJ": [59, 130, 246, 195],        # Niebieski
    "MONITORUJ": [234, 179, 8, 190],       # Żółty
    "CZEKAJ": [239, 68, 68, 205],          # Czerwony
}
result_df["color"] = result_df["decyzja"].map(lambda d: COLOR_MAP.get(d, [156, 163, 175, 180]))

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Pola (H3 L10)", len(result_df))
c2.metric("PRYSKAJ TERAZ", sum(result_df["decyzja"] == "PRYSKAJ TERAZ"))
c3.metric("NAWOŹ", sum(result_df["decyzja"] == "NAWOŹ"))
c4.metric("ZASIEJ", sum(result_df["decyzja"] == "ZASIEJ"))
c5.metric("CZEKAJ", sum(result_df["decyzja"] == "CZEKAJ"))
c6.metric("Śr. wiatr [m/s]", f"{result_df['wind_ms'].mean():.1f}" if not result_df.empty else "-")

tab_map, tab_soil = st.tabs(["🗺️ Mapa decyzji i pogoda", "🌱 Doradca siewu (SoilGrids)"])

with tab_map:
    col_map, col_chart = st.columns([1.4, 1.0])

    with col_map:
        st.subheader("Mapa decyzji polowych (Kafel 33UXR)")
        layer = pdk.Layer(
            "H3HexagonLayer",
            data=result_df,
            pickable=True,
            stroked=True,
            filled=True,
            extruded=False,
            get_hexagon="h3_index",
            get_fill_color="color",
            get_line_color=[40, 40, 40],
            line_width_min_pixels=1,
        )
        view_state = pdk.ViewState(
            latitude=float(result_df["lat"].mean()) if not result_df.empty else 50.06,
            longitude=float(result_df["lon"].mean()) if not result_df.empty else 19.94,
            zoom=8.5,
            pitch=0,
        )
        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            tooltip={
                "html": "<b>H3:</b> {h3_index} | <b>Reguła:</b> {rule_id}<br/>"
                "<b>Uprawa:</b> {crop_name} (NDVI: {ndvi})<br/>"
                "<b>Decyzja:</b> {decyzja} | <b>Ryzyko:</b> {poziom_ryzyka}<br/>"
                "<b>Komunikat:</b> {komunikat}<br/>"
                "<b>Nawóz:</b> {zalecany_nawoz} | <b>Siew:</b> {rekomendowana_uprawa}<br/>"
                "<b>Gleba:</b> pH {soil_ph}, SOC {soil_soc} g/kg ({soil_texture})<br/>"
                "<b>Pogoda:</b> Wiatr {wind_ms} m/s, Temp {temp_c} °C, Opad 24h {precip_24h_mm} mm"
            },
        )
        st.pydeck_chart(deck, use_container_width=True)

    with col_chart:
        st.subheader("Przebieg warunków wiatrowych (okno zabiegowe)")
        hourly_summary = (
            weather_df.groupby("timestamp", as_index=False)[["wind_ms", "temp_c", "humidity_pct"]]
            .mean()
        )
        fig = px.line(
            hourly_summary,
            x="timestamp",
            y=["wind_ms", "temp_c"],
            labels={"value": "Wartość", "timestamp": "Czas", "variable": "Parametr"},
        )
        fig.add_hline(y=4.0, line_dash="dash", line_color="red", annotation_text="Próg wiatru 4 m/s")
        fig.add_vline(
            x=pd.to_datetime(selected_ts).timestamp() * 1000,
            line_dash="dot",
            line_color="green",
            annotation_text="Wybrana godzina",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Szczegółowa tabela decyzji dla pól")
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
        "wind_ms",
        "temp_c",
        "precip_24h_mm",
    ]
    st.dataframe(result_df[display_cols], use_container_width=True, hide_index=True)

with tab_soil:
    st.subheader("Rekomendacja doboru uprawy do siewu na podstawie gleby (SoilGrids v2)")
    col_calc, col_summary = st.columns([1.0, 1.3])

    with col_calc:
        st.markdown("#### Szybki kalkulator stanowiska")
        in_ph = st.slider("Odczyn gleby (soil_ph)", 4.5, 8.0, 6.4, 0.1)
        in_soc = st.slider("Węgiel organiczny SOC [g/kg]", 5.0, 35.0, 17.5, 0.5)
        in_tex = st.selectbox(
            "Klasa uziarnienia USDA (soil_texture)",
            ["Loam", "Silt Loam", "Clay Loam", "Sandy Loam", "Sand"],
        )
        rec_crop, rec_reason = recommend_crop_by_soil(in_ph, in_soc, in_tex, crop_dict_df=crop_dict_df)
        st.success(f"**Rekomendowana uprawa do siewu:** {rec_crop}")
        st.info(f"**Uzasadnienie glebowe:** {rec_reason}")

    with col_summary:
        st.markdown("#### Rozkład rekomendacji siewu dla pól w kaflu 33UXR")
        crop_counts = result_df["rekomendowana_uprawa"].value_counts().reset_index()
        crop_counts.columns = ["Rekomendowana uprawa", "Liczba heksagonów H3"]
        fig_soil = px.bar(
            crop_counts,
            x="Rekomendowana uprawa",
            y="Liczba heksagonów H3",
            color="Rekomendowana uprawa",
        )
        st.plotly_chart(fig_soil, use_container_width=True)

    st.dataframe(
        result_df[
            [
                "h3_index",
                "crop_name",
                "ndvi",
                "soil_ph",
                "soil_soc",
                "soil_texture",
                "rekomendowana_uprawa",
                "uzasadnienie_glebowe",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )