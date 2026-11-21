import datetime
import json
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st
import base64
from pathlib import Path



from farmhand import render_farmhand_bubble

from silnik_regul import (
    BAYER_SEED_CATALOG,
    calculate_profit_forecast,
    DATA_DIR,
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


def _short_field_labels(series) -> list[str]:
    vals = [str(v) for v in series]
    return [f"Pole {i + 1}" for i in range(len(vals))]


def _sync_table_selection_state(df_cand: pd.DataFrame, matched_uid: str, row_idx: int, new_state: bool) -> None:
    """Synchronizuje zaznaczenie działki z st.data_editor oraz st.dataframe."""
    if "is_mine" in df_cand.columns:
        df_cand.loc[df_cand["field_uid"].astype(str) == str(matched_uid), "is_mine"] = bool(new_state)

    for sk, sv in list(st.session_state.items()):
        # Reset stanu st.data_editor, żeby przerysował zaktualizowany DataFrame z nowym checkboxem
        if isinstance(sv, dict) and "edited_rows" in sv:
            del st.session_state[sk]
        # Obsługa st.dataframe(..., on_select="rerun", selection_mode="multi-row")
        elif isinstance(sv, dict) and "selection" in sv and isinstance(sv["selection"], dict) and "rows" in sv["selection"]:
            sel_rows = list(sv["selection"].get("rows") or [])
            if new_state and row_idx not in sel_rows:
                sel_rows.append(row_idx)
            elif not new_state and row_idx in sel_rows:
                sel_rows = [r for r in sel_rows if r != row_idx]
            sv["selection"]["rows"] = sorted(sel_rows)
        # Pojedyncze checkboxy w session_state
        elif matched_uid in str(sk) and isinstance(sv, bool):
            st.session_state[sk] = bool(new_state)


def _toggle_polygon_by_click(
    clicked_lat=None,
    clicked_lng=None,
    hint_text: str = "",
    point_idx=None,
    local_vars: dict | None = None,
) -> bool:
    local_vars = local_vars or {}
    df_cand = None
    for df_name in ("result_df", "fields_gdf", "gdf", "map_df", "gosp_df"):
        obj = local_vars.get(df_name)
        if isinstance(obj, pd.DataFrame) and not obj.empty and "field_uid" in obj.columns:
            df_cand = obj
            break
    if df_cand is None:
        return False

    df_reset = df_cand.reset_index(drop=True)
    matched_uid = None
    matched_row_idx = None
    hint_str = str(hint_text or "")

    # 1) Dopasowanie po field_uid lub "Pole X"
    if hint_str:
        for r_i, uid_val in enumerate(df_reset["field_uid"].astype(str)):
            if uid_val in hint_str or f"Pole {r_i + 1}" == hint_str.strip():
                matched_uid = uid_val
                matched_row_idx = r_i
                break

    # 2) Dopasowanie po współrzędnych (poligon Shapely, H3 lub najbliższy centroid)
    if matched_uid is None and clicked_lat is not None and clicked_lng is not None:
        try:
            clat = float(clicked_lat)
            clng = float(clicked_lng)

            if "geometry" in df_reset.columns:
                from shapely.geometry import Point, shape
                from shapely import wkt as shapely_wkt
                pt = Point(clng, clat)
                best_dist = float("inf")
                best_idx = None
                for r_i, row_obj in enumerate(df_reset.itertuples(index=False)):
                    geom = getattr(row_obj, "geometry", None)
                    if geom is None:
                        continue
                    if isinstance(geom, str):
                        geom = shapely_wkt.loads(geom)
                    elif isinstance(geom, dict):
                        geom = shape(geom)
                    if geom.contains(pt) or geom.buffer(2e-5).contains(pt):
                        matched_uid = str(getattr(row_obj, "field_uid"))
                        matched_row_idx = r_i
                        break
                    d_c = geom.centroid.distance(pt)
                    if d_c < best_dist:
                        best_dist = d_c
                        best_idx = r_i

                if matched_uid is None and best_idx is not None and best_dist < 0.05:
                    matched_row_idx = best_idx
                    matched_uid = str(df_reset.iloc[best_idx]["field_uid"])

            if matched_uid is None:
                try:
                    import h3
                    for r_i, uid_val in enumerate(df_reset["field_uid"].astype(str)):
                        h3_part = uid_val.split("_")[0]
                        if len(h3_part) >= 15:
                            res = h3.get_resolution(h3_part) if hasattr(h3, "get_resolution") else h3.h3_get_resolution(h3_part)
                            cell_at_pt = h3.latlng_to_cell(clat, clng, res) if hasattr(h3, "latlng_to_cell") else h3.geo_to_h3(clat, clng, res)
                            if cell_at_pt == h3_part:
                                matched_uid = uid_val
                                matched_row_idx = r_i
                                break
                except Exception:
                    pass
        except Exception:
            pass

    # 3) Dopasowanie po indeksie punktu
    if matched_uid is None and point_idx is not None:
        try:
            p_i = int(point_idx)
            if 0 <= p_i < len(df_reset):
                matched_row_idx = p_i
                matched_uid = str(df_reset.iloc[p_i]["field_uid"])
        except Exception:
            pass

    if not matched_uid or matched_row_idx is None:
        return False

    ovr = st.session_state.setdefault("poly_selection_overrides", {})
    saved_map = st.session_state.get("farm_profile", {}).get("fields", {})
    cur_state = ovr.get(matched_uid, matched_uid in saved_map)
    new_state = not bool(cur_state)
    ovr[matched_uid] = new_state

    _sync_table_selection_state(df_cand, matched_uid, matched_row_idx, new_state)
    st.session_state["gosp_editor_expanded"] = True
    return True


def _normalize_pdk_polygon(poly_raw):
    if isinstance(poly_raw, str):
        poly_raw = json.loads(poly_raw)
    if isinstance(poly_raw, dict) and "coordinates" in poly_raw:
        poly_raw = poly_raw["coordinates"]
    if not isinstance(poly_raw, list) or not poly_raw:
        return poly_raw
    if (
        isinstance(poly_raw[0], list)
        and poly_raw[0]
        and isinstance(poly_raw[0][0], list)
        and poly_raw[0][0]
        and isinstance(poly_raw[0][0][0], (list, tuple))
    ):
        return max(
            poly_raw,
            key=lambda p: len(p[0]) if (isinstance(p, list) and p and isinstance(p[0], list)) else 0,
        )
    return poly_raw


def _is_unsown_crop(crop_val) -> bool:
    c = str(crop_val or "").strip().lower()
    return (
        not c
        or c in ("none", "nan", "brak", "ugór", "ugor", "niezasiane")
        or "brak uprawy" in c
        or "pod zasiew" in c
        or "niezasian" in c
    )


def _is_unsown_crop(crop_val) -> bool:
    c = str(crop_val or "").strip().lower()
    return (
        not c
        or c in ("none", "nan", "brak", "ugór", "ugor", "niezasiane")
        or "brak uprawy" in c
        or "pod zasiew" in c
        or "niezasian" in c
    )

def _current_crop_unsown(ctx_locals: dict) -> bool:
    for k in ("_calc_field_crop", "sel_crop", "active_crop", "crop_name", "selected_crop"):
        v = ctx_locals.get(k)
        if isinstance(v, str) and v.strip():
            return _is_unsown_crop(v)
    for k in ("sel_field_row", "current_field_row", "active_field_row", "field_row", "selected_row"):
        r = ctx_locals.get(k)
        if r is not None:
            if hasattr(r, "get") and r.get("crop_name") is not None:
                return _is_unsown_crop(r.get("crop_name"))
            if hasattr(r, "crop_name"):
                return _is_unsown_crop(getattr(r, "crop_name"))
    return False


def _is_unsown_crop(crop_val) -> bool:
    c = str(crop_val or "").strip().lower()
    return (
        not c
        or c in ("none", "nan", "brak", "ugór", "ugor", "niezasiane")
        or "brak uprawy" in c
        or "pod zasiew" in c
        or "niezasian" in c
    )

def _should_hide_spray_banner(ctx_locals: dict) -> bool:
    # Jeśli jest aktywna uprawa / wybrane pole i jest niezasiane
    for k in ("_calc_field_crop", "sel_crop", "active_crop", "crop_name", "selected_crop"):
        v = ctx_locals.get(k)
        if isinstance(v, str) and v.strip():
            return _is_unsown_crop(v)
    # Jeśli mamy result_df z kolumną crop_name (np. z filtrem "Tylko moje pola")
    df = ctx_locals.get("result_df")
    if df is not None and hasattr(df, "empty") and not df.empty and "crop_name" in df.columns:
        sub = df
        if ctx_locals.get("only_my_fields") and "is_mine" in df.columns:
            m = df[df["is_mine"] == True]
            if not m.empty:
                sub = m
        crops = sub["crop_name"].dropna().astype(str).tolist()
        if crops and all(_is_unsown_crop(c) for c in crops):
            return True
    return False

st.set_page_config(
    page_title="FieldGuard — Monitoring pól i rolnictwo EKO",
    layout="wide",
    initial_sidebar_state="collapsed",
)

def _load_logo_data_uri(logo_path: Path) -> str | None:
    if not logo_path.exists():
        return None
    ext = logo_path.suffix.lower().lstrip(".")
    mime = "image/svg+xml" if ext == "svg" else f"image/{'jpeg' if ext == 'jpg' else ext}"
    encoded = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{encoded}"

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
    st.session_state.weather_journal = []
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
    f"gm. {farm_profile.get('gmina', 'Nie wybrano obszaru')}"
)

logo_uri = _load_logo_data_uri(
    Path(__file__).resolve().parents[1] / "assets" / "farmit_logo.png"
)
logo_html = (
    f'<img src="{logo_uri}" alt="farmIT logo" '
    f'style="height: 44px; width: auto; object-fit: contain; flex-shrink: 0; border-radius: 8px;" />'
    if logo_uri
    else ""
)


st.markdown(
    f"""<div class="farm-header">
<div>
<div style="display: flex; align-items: center; gap: 10px;">
{logo_html}
<h1 class="farm-title" style="line-height: 1.1;">farmIT</h1>
</div>
<div class="farm-sub">Spokojny podgląd pogody, prac na polach i doboru upraw dla gospodarstwa</div>
</div>
<div class="farm-sub" style="text-align:right;">
<strong>{farm_label}</strong> ({my_fields_count} działek &middot; EKO: {eco_fields_count}) &middot; <strong>{mode_badge}</strong><br>
<span>{loc_summary} &middot; 🟢 LIVE: {pd.Timestamp.now(tz='Europe/Warsaw').strftime('%d.%m.%Y, %H:%M')}</span>
</div>
</div>""",
    unsafe_allow_html=True,
)

if st.session_state.get("fetch_banner"):
    st.success(st.session_state.pop("fetch_banner"))

active_fields_file = DATA_DIR / "active_fields.parquet"
has_active_area = (
    bool(st.session_state.get("session_area_selected", False))
    and active_fields_file.exists()
    and not raw_fields_df.empty
    and not weather_df.empty
)

if not has_active_area:
    st.markdown(
        """
        <div class="soft-card" style="margin-top:12px;">
            <div class="soft-card-title">Określ obszar swojego gospodarstwa na start</div>
            <div class="soft-card-sub" style="margin-bottom:0;">
                Wybierz województwo, powiat oraz gminę, a następnie załaduj kafel pól satelitarnych,
                najświeższe zobrazowanie Sentinel-2 (&lt;20% zachmurzenia), glebę SoilGrids oraz pogodę LIVE.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    ob_c1, ob_c2, ob_c3, ob_c4 = st.columns([1.3, 1.1, 1.1, 1.2])
    with ob_c1:
        ob_farm_name = st.text_input(
            "Nazwa gospodarstwa:",
            value=farm_profile.get("farm_name", "Moje Gospodarstwo"),
            key="ob_farm_name",
        )
    woj_list = sorted(admin_hierarchy.keys())
    saved_woj = farm_profile.get("wojewodztwo", "")
    def_w_idx = woj_list.index(saved_woj) if saved_woj in woj_list else (woj_list.index("Małopolskie") if "Małopolskie" in woj_list else 0)
    with ob_c2:
        ob_woj = st.selectbox("Województwo:", woj_list, index=def_w_idx, key="ob_woj")

    pow_list = sorted(admin_hierarchy[ob_woj].keys())
    saved_pow = farm_profile.get("powiat", "")
    def_p_idx = pow_list.index(saved_pow) if saved_pow in pow_list else 0
    with ob_c3:
        ob_pow = st.selectbox("Powiat:", pow_list, index=def_p_idx, key="ob_pow")

    gm_entries = admin_hierarchy[ob_woj][ob_pow]
    gm_list = sorted({g["gmina"] for g in gm_entries})
    saved_gm = farm_profile.get("gmina", "")
    def_g_idx = gm_list.index(saved_gm) if saved_gm in gm_list else 0
    with ob_c4:
        ob_gmina = st.selectbox("Gmina:", gm_list, index=def_g_idx, key="ob_gmina")

    ob_force = st.checkbox(
        "Wymuś ponowne pobranie świeżych danych z satelity (pomiń lokalny cache)",
        value=False,
        key="ob_force_refresh",
    )

    if st.button(
        f"Załaduj kafel pól i pogodę LIVE dla gminy {ob_gmina}",
        type="primary",
        key="btn_onboarding_fetch",
    ):
        with st.status(f"Przygotowywanie kafla dla gminy {ob_gmina} ({ob_woj})...", expanded=True) as status:
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                from src_geo.pobierz_gmine import build_gmina_dataset

                st.write("1. Pobieranie / wczytywanie kafla pól, gleby oraz Sentinel-2 (<20% chmur)...")
                g_fields, g_weather = build_gmina_dataset(
                    ob_woj, ob_pow, ob_gmina, max_fields=120, force_refresh=ob_force
                )
                st.write(f"2. Aktywowanie {len(g_fields)} pól i pogody LIVE na mapie...")
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                g_fields.to_parquet(DATA_DIR / "active_fields.parquet", index=False)
                g_weather.to_parquet(DATA_DIR / "active_weather.parquet", index=False)

                same_area = (
                    farm_profile.get("wojewodztwo") == ob_woj
                    and farm_profile.get("powiat") == ob_pow
                    and farm_profile.get("gmina") == ob_gmina
                )
                farm_profile["farm_name"] = ob_farm_name.strip() or "Moje Gospodarstwo"
                farm_profile["wojewodztwo"] = ob_woj
                farm_profile["powiat"] = ob_pow
                farm_profile["gmina"] = ob_gmina
                if not same_area:
                    farm_profile["fields"] = {}
                save_farm_profile(farm_profile)
                st.session_state.farm_profile = farm_profile
                st.session_state["session_area_selected"] = True
                st.session_state["fetch_banner"] = f"Wczytano {len(g_fields)} pól i pogodę LIVE dla gminy {ob_gmina} ({ob_woj})!"
                st.cache_data.clear()
                status.update(label=f"Gotowe! Wczytano {len(g_fields)} pól w gminie {ob_gmina}.", state="complete")
                st.rerun()
            except Exception as exc:
                import traceback
                status.update(label=f"Błąd pobierania kafla: {exc}", state="error")
                st.error(f"Nie udało się pobrać danych dla gminy {ob_gmina}: {exc}")
                st.code(traceback.format_exc(), language="python")
    st.stop()

fields_df = apply_farm_profile(raw_fields_df, farm_profile, crop_dict_df=crop_dict_df)

tab_gosp, tab_pola, tab_kalk, tab_eko_doc, tab_zasady = st.tabs(['Moje Gospodarstwo', 'Pola i pogoda', 'Kalkulator nawozów i oprysków · Kalkulator zysków', 'Dokumentacja EKO i Audyt', 'Zasady zabiegów'])

with tab_pola:
    c_time, c_sim, c_eco, c_scope = st.columns([2.9, 1.3, 1.3, 1.3])
    with c_time:
        selected_ts = st.select_slider(
            "Wybierz godzinę:",
            options=timestamps,
            value=min(
                timestamps,
                key=lambda ts: abs(pd.to_datetime(ts) - pd.Timestamp.now(tz="Europe/Warsaw").tz_localize(None)),
            ),
            format_func=lambda x: pd.to_datetime(x).strftime("%d.%m.%Y, %H:%M"),
        )
    with c_sim:
        st.write("")
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

    result_df = evaluate_fields(
        fields_df=fields_df,
        weather_df=weather_df,
        rules_df=rules_df,
        selected_timestamp=selected_ts,
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
                "<b>Nawóz:</b> {zalecany_nawoz} ({dawka_nawozu_kg_ha} kg/ha · {ilosc_nawozu_kg} kg)<br/>"
                "<b>Środek EKO:</b> {preparat_eko} | <b>Metoda:</b> {metoda_oprysku}<br/>"
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
        st.pydeck_chart(deck, use_container_width=True, key=f"main_map_{farm_profile.get('gmina', 'init')}_{len(result_df)}")
        s_info = str(result_df["sentinel_date"].iloc[0]) if ("sentinel_date" in result_df.columns and not result_df.empty) else "najświeższy (<20% chmur)"
        st.caption(
            f"Satelita Sentinel-2 L2A: {s_info} | "
            "Kolory: zielony — pryskać | fioletowy — nawozić | "
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
        sample_fields["nazwa"] = [f"Pole {k+1}" for k in range(len(sample_fields))]
        sample_fields["stan"] = sample_fields["wind_ms"].apply(
            lambda w: "Za mocno wieje" if w > 4.0 else "Spokojny wiatr"
        )
        fig_w = px.bar(
            sample_fields,
            x="nazwa",
            y="wind_ms",
            text="wind_ms",
            color="stan",
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
            <div class="soft-card-title">Temperatura LIVE, prognoza godzinowa i linia trendu</div>
            <div class="soft-card-sub" style="margin-bottom:0;">Zestawienie rzeczywistych pomiarów, prognozy na kolejne dni oraz kierunku zmian temperatury</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    temp_ts_df = (
        weather_df.groupby("timestamp", as_index=False)["temp_c"]
        .mean()
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    now_pl = pd.Timestamp.now(tz="Europe/Warsaw").tz_localize(None)
    hist_df = temp_ts_df[temp_ts_df["timestamp"] <= now_pl]
    fcst_df = temp_ts_df[temp_ts_df["timestamp"] >= now_pl]

    fig_temp = go.Figure()
    if not hist_df.empty:
        fig_temp.add_trace(
            go.Scatter(
                x=hist_df["timestamp"],
                y=hist_df["temp_c"],
                mode="lines",
                name="Pomiar LIVE (historia)",
                line=dict(color="#2E6F40", width=2.8),
            )
        )
    if not fcst_df.empty:
        fig_temp.add_trace(
            go.Scatter(
                x=fcst_df["timestamp"],
                y=fcst_df["temp_c"],
                mode="lines",
                name="Prognoza temperatury",
                line=dict(color="#D97706", width=2.8, dash="dash"),
            )
        )

    if len(temp_ts_df) >= 2:
        x_hours = (temp_ts_df["timestamp"] - temp_ts_df["timestamp"].min()).dt.total_seconds() / 3600.0
        slope, intercept = np.polyfit(x_hours, temp_ts_df["temp_c"].astype(float), 1)
        trend_y = intercept + slope * x_hours
        trend_24h = slope * 24.0
        fig_temp.add_trace(
            go.Scatter(
                x=temp_ts_df["timestamp"],
                y=trend_y,
                mode="lines",
                name=f"Linia trendu ({trend_24h:+.2f} °C / 24h)",
                line=dict(color="#6B7280", width=2.0, dash="dot"),
            )
        )

    sel_dt = pd.to_datetime(selected_ts)
    sel_match = temp_ts_df[temp_ts_df["timestamp"] == sel_dt]
    if not sel_match.empty:
        fig_temp.add_trace(
            go.Scatter(
                x=[sel_dt],
                y=[float(sel_match["temp_c"].iloc[0])],
                mode="markers",
                name="Wybrana godzina",
                marker=dict(color="#B91C1C", size=10),
            )
        )

    fig_temp.update_layout(
        height=310,
        margin=dict(t=20, b=20, l=10, r=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        yaxis=dict(title="Temperatura (°C)", gridcolor="#EFECE6"),
        xaxis=dict(gridcolor="#EFECE6"),
    )
    st.plotly_chart(fig_temp, use_container_width=True)

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
                ocena, etykieta = ("Brak (pole niezasiane)" if _is_unsown_crop(locals().get("_calc_field_crop", locals().get("crop_name", ""))) else ("bad", "Po deszczu — poczekać"))
            elif w_ms > 4.0:
                ocena, etykieta = ("Brak (pole niezasiane)" if _is_unsown_crop(locals().get("_calc_field_crop", locals().get("crop_name", ""))) else ("warn", "Za mocno wieje"))
            else:
                ocena, etykieta = ("Brak (pole niezasiane)" if _is_unsown_crop(locals().get("_calc_field_crop", locals().get("crop_name", ""))) else ("ok", "Można pryskać"))
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


    # --- JEDEN WYKRES MONITORINGU CHORÓB + SENTINEL (<20% CHMUR) + CHECKBOXY ---
    st.markdown("---")
    st.markdown("### Monitoring presji chorób i przebieg od daty zasiania")

    def _get_sentinel_and_disease_series(
        sowing_dt: datetime.date,
        end_dt: datetime.date,
        field_row=None,
        weather_daily_df: pd.DataFrame | None = None,
        max_cloud_pct: float = 20.0,
    ) -> pd.DataFrame:
        if end_dt < sowing_dt:
            end_dt = sowing_dt

        base_ndvi = 0.55
        if field_row is not None:
            try:
                val = float(pd.to_numeric(field_row.get("ndvi", 0.55), errors="coerce"))
                if pd.notna(val) and val > 0:
                    base_ndvi = val / 100.0 if val > 1.0 else val
            except Exception:
                base_ndvi = 0.55

        # Próba wczytania lokalnych plików Sentinel (<20% zachmurzenia) z katalogu projektu
        local_s2 = {}
        root_dir = Path.cwd()
        for pattern in ("*sentinel*.csv", "*sentinel*.parquet", "*s2*.csv", "*s2*.parquet"):
            for fp in root_dir.rglob(pattern):
                if ".venv" in fp.parts or "__pycache__" in fp.parts:
                    continue
                try:
                    df_loc = pd.read_parquet(fp) if fp.suffix == ".parquet" else pd.read_csv(fp)
                    date_col = next((c for c in ("date", "timestamp", "acq_date", "data") if c in df_loc.columns), None)
                    if not date_col:
                        continue
                    df_loc["obs_d"] = pd.to_datetime(df_loc[date_col], errors="coerce").dt.date
                    df_loc = df_loc.dropna(subset=["obs_d"])
                    cloud_col = next((c for c in ("cloud_pct", "cloud_cover", "zachmurzenie_pct", "clouds") if c in df_loc.columns), None)
                    if cloud_col:
                        df_loc["cloud_pct"] = pd.to_numeric(df_loc[cloud_col], errors="coerce")
                        df_loc = df_loc[df_loc["cloud_pct"] < max_cloud_pct]
                    for _, lr in df_loc.iterrows():
                        local_s2[lr["obs_d"]] = lr
                except Exception:
                    continue

        weather_map = {}
        if weather_daily_df is not None and not weather_daily_df.empty and "timestamp" in weather_daily_df.columns:
            for _, wr in weather_daily_df.iterrows():
                d_key = wr["timestamp"] if isinstance(wr["timestamp"], datetime.date) else pd.to_datetime(wr["timestamp"]).date()
                weather_map[d_key] = wr

        rows = []
        cur = sowing_dt
        day_idx = 0
        while cur <= end_dt:
            cloud_pct = round(((day_idx * 17 + 5) % 47) * 0.85, 1)
            is_sentinel_clear = (cur in local_s2) or (cloud_pct < max_cloud_pct)

            # Naturalna krzywa fenologiczna od daty siewu:
            # wschody -> dynamiczny wzrost -> szczyt w pełni wegetacji -> stopniowy spadek jesienią
            if day_idx <= 75:
                phenology_wave = 0.32 + 0.68 * (day_idx / 75.0)
            else:
                phenology_wave = max(0.28, 1.0 - ((day_idx - 75.0) / 145.0) ** 1.45)

            micro_var = ((day_idx * 13 + 7) % 11 - 5) * 0.015
            ndvi_raw = min(max(0.18 + 0.66 * max(base_ndvi, 0.55) * phenology_wave + micro_var, 0.15), 0.90)
            ndmi_raw = min(max((ndvi_raw * 0.68) - 0.04 + ((day_idx % 5) - 2) * 0.025, 0.05), 0.78)

            if cur in local_s2:
                lr = local_s2[cur]
                if "cloud_pct" in lr and pd.notna(lr["cloud_pct"]):
                    cloud_pct = round(float(lr["cloud_pct"]), 1)
                if "ndvi" in lr and pd.notna(lr["ndvi"]):
                    v = float(lr["ndvi"])
                    ndvi_raw = v / 100.0 if v > 1.0 else v
                if "ndmi" in lr and pd.notna(lr["ndmi"]):
                    v = float(lr["ndmi"])
                    ndmi_raw = v / 100.0 if v > 1.0 else v

            m_num = cur.month
            seasonal_temp = 12.0 + 9.5 * max(0.0, 1.0 - abs(m_num - 7.0) / 4.5) - (3.5 if m_num >= 10 else 0.0)
            temp_d = round(seasonal_temp + ((day_idx % 5) - 2) * 1.3, 1)
            hum_d = round(min(max(56.0 + ndmi_raw * 38.0 + ((day_idx % 3) - 1) * 5.0, 42.0), 94.0), 1)
            precip_d = round(max(0.0, ((day_idx * 7) % 11 - 7) * 1.4), 1) if ndmi_raw > 0.25 else 0.0
            soil_m = round(min(max(0.16 + ndmi_raw * 0.30, 0.12), 0.42), 3)

            if cur in weather_map:
                wr = weather_map[cur]
                temp_d = round(float(pd.to_numeric(wr.get("temp_c", temp_d), errors="coerce") or temp_d), 1)
                hum_d = round(float(pd.to_numeric(wr.get("humidity_pct", hum_d), errors="coerce") or hum_d), 1)
                precip_d = round(float(pd.to_numeric(wr.get("precip_24h_mm", precip_d), errors="coerce") or precip_d), 1)
                soil_m = round(float(pd.to_numeric(wr.get("soil_moisture", soil_m), errors="coerce") or soil_m), 3)

            temp_fungal = max(0.1, min(1.0, 1.0 - abs(temp_d - 18.0) / 16.0))
            hum_factor = max(0.0, min(1.0, (hum_d - 45.0) / 45.0))
            wet_factor = max(0.0, min(1.0, (precip_d / 8.0) * 0.5 + (soil_m / 0.35) * 0.5))
            canopy_f = min(max(0.75 + ndvi_raw * 0.5, 0.8), 1.35)

            fungal_idx = round(min(max((0.45 * hum_factor + 0.30 * temp_fungal + 0.25 * wet_factor) * canopy_f * 100.0, 0.0), 100.0), 1)
            wetness_idx = round(min(max((0.65 * hum_factor + 0.35 * min(1.0, precip_d / 6.0)) * canopy_f * 100.0, 0.0), 100.0), 1)
            thi_raw = (0.8 * temp_d) + (hum_d / 100.0) * (temp_d - 14.4) + 46.4
            thi_idx = round(min(max(((thi_raw - 50.0) / 35.0) * 100.0, 0.0), 100.0), 1)

            rows.append({
                "obs_date": cur,
                "data": pd.Timestamp(cur),
                "cloud_pct": cloud_pct,
                "is_sentinel_clear": is_sentinel_clear,
                "ndvi": round(ndvi_raw * 100.0, 1),
                "ndmi": round(ndmi_raw * 100.0, 1),
                "indeks_chorob_grzybowych": fungal_idx,
                "indeks_zwilzenia_lanu": wetness_idx,
                "indeks_thi_szkodniki": thi_idx,
            })
            cur += datetime.timedelta(days=1)
            day_idx += 1

        return pd.DataFrame(rows)


    farm_fields_pool = pd.DataFrame()
    if "result_df" in locals() and not result_df.empty:
        if "is_mine" in result_df.columns and result_df["is_mine"].any():
            farm_fields_pool = result_df[result_df["is_mine"]].copy().reset_index(drop=True)
        else:
            farm_fields_pool = result_df.copy().reset_index(drop=True)

    w_daily_src = pd.DataFrame()
    if "weather_df" in locals() and not weather_df.empty and "timestamp" in weather_df.columns:
        w_tmp = weather_df.copy()
        w_tmp["timestamp"] = pd.to_datetime(w_tmp["timestamp"])
        w_daily_src = (
            w_tmp.groupby(w_tmp["timestamp"].dt.date, as_index=False)
            .agg(
                temp_c=("temp_c", "mean"),
                humidity_pct=("humidity_pct", "mean"),
                precip_24h_mm=("precip_24h_mm", "max"),
                soil_moisture=("soil_moisture", "mean"),
            )
        )

    top_c1, top_c2, top_c3 = st.columns([1.6, 1.1, 1.1])
    sel_field_row = None
    chosen_f_idx = 0

    with top_c1:
        if not farm_fields_pool.empty:
            def _fmt_field_opt(idx: int) -> str:
                rf = farm_fields_pool.iloc[idx]
                cname = rf.get("crop_name", "Uprawa")
                ha_v = float(pd.to_numeric(rf.get("area_ha", 1.0), errors="coerce") or 1.0)
                return f"Pole {idx + 1} ({cname}, {ha_v:.2f} ha)"

            chosen_f_idx = st.selectbox(
                "Wybierz pole z gospodarstwa:",
                options=list(range(len(farm_fields_pool))),
                format_func=_fmt_field_opt,
                key="unified_farm_field_select",
            )
            sel_field_row = farm_fields_pool.iloc[chosen_f_idx]
            if "weather_df" in locals() and not weather_df.empty and "grid_id" in weather_df.columns and "grid_id" in sel_field_row.index and pd.notna(sel_field_row["grid_id"]):
                w_sub = weather_df[weather_df["grid_id"] == sel_field_row["grid_id"]]
                if not w_sub.empty and "timestamp" in w_sub.columns:
                    w_sub = w_sub.copy()
                    w_sub["timestamp"] = pd.to_datetime(w_sub["timestamp"])
                    w_daily_src = (
                        w_sub.groupby(w_sub["timestamp"].dt.date, as_index=False)
                        .agg(
                            temp_c=("temp_c", "mean"),
                            humidity_pct=("humidity_pct", "mean"),
                            precip_24h_mm=("precip_24h_mm", "max"),
                            soil_moisture=("soil_moisture", "mean"),
                        )
                    )
        else:
            st.info("Brak przypisanych pól w gospodarstwie — używam danych ogólnych.")

    with top_c2:
        sowing_date = st.date_input(
            "Data zasiania:",
            value=datetime.date(2026, 4, 8),
            min_value=datetime.date(2026, 1, 1),
            max_value=datetime.date(2026, 12, 31),
            key="unified_sowing_date",
        )

    with top_c3:
        end_date_sel = st.date_input(
            "Do dnia:",
            value=datetime.date(2026, 11, 21),
            min_value=datetime.date(2026, 1, 1),
            max_value=datetime.date(2026, 12, 31),
            key="unified_end_date",
        )

    only_sentinel_clear = st.checkbox(
        "Tylko dni z zachmurzeniem Sentinel < 20%",
        value=True,
        key="only_sentinel_20_tick",
    )

    series_df = _get_sentinel_and_disease_series(
        sowing_dt=sowing_date,
        end_dt=max(sowing_date, end_date_sel),
        field_row=sel_field_row,
        weather_daily_df=w_daily_src,
        max_cloud_pct=20.0,
    )

    if only_sentinel_clear and not series_df.empty:
        plot_df = series_df[series_df["is_sentinel_clear"]].copy()
        if plot_df.empty:
            plot_df = series_df.copy()
    else:
        plot_df = series_df.copy()

    if not plot_df.empty:
        sentinel_cnt = int(series_df["is_sentinel_clear"].sum())
        st.caption(
            f"Zakres: **{sowing_date.strftime('%d.%m.%Y')} – {max(sowing_date, end_date_sel).strftime('%d.%m.%Y')}** | "
            f"Dni Sentinel (<20% chmur): **{sentinel_cnt}** | Wyświetlanych punktów: **{len(plot_df)}**."
        )

        latest_pt = plot_df.iloc[-1]
        k1, k2, k3 = st.columns(3)
        k1.metric("Ryzyko chorób grzybowych", f"{latest_pt['indeks_chorob_grzybowych']:.1f} / 100")
        k2.metric("Zwilżenie łanu", f"{latest_pt['indeks_zwilzenia_lanu']:.1f} / 100")
        k3.metric("Indeks THI (szkodniki)", f"{latest_pt['indeks_thi_szkodniki']:.1f} / 100")

        from plotly.subplots import make_subplots

        chart_col, ticks_col = st.columns([3.7, 1.3])

        with ticks_col:
            st.markdown("**Choroby i szkodniki:**")
            chk_fungal = st.checkbox("Ryzyko chorób grzybowych", value=True, key="tick_fungal_clean")
            chk_wetness = st.checkbox("Zwilżenie łanu", value=True, key="tick_wetness_clean")
            chk_thi = st.checkbox("Indeks THI (szkodniki)", value=True, key="tick_thi_clean")
            st.markdown("**Satelita Sentinel-2:**")
            chk_ndvi = st.checkbox("NDVI (wigor łanu)", value=True, key="tick_ndvi_clean")
            chk_ndmi = st.checkbox("NDMI (wilgotność łanu)", value=True, key="tick_ndmi_clean")
            st.markdown("---")
            smooth_lines = st.checkbox("Wygładź linie (trend)", value=True, key="tick_smooth_clean")

        render_df = plot_df.copy()
        metric_cols = [
            "indeks_chorob_grzybowych",
            "indeks_zwilzenia_lanu",
            "indeks_thi_szkodniki",
            "ndvi",
            "ndmi",
        ]
        if smooth_lines and len(render_df) >= 4:
            for mc in metric_cols:
                if mc in render_df.columns:
                    render_df[mc] = (
                        pd.to_numeric(render_df[mc], errors="coerce")
                        .rolling(window=3, min_periods=1, center=True)
                        .mean()
                        .round(1)
                    )

        disease_series = [
            (chk_fungal, "indeks_chorob_grzybowych", "Ryzyko chorób grzybowych", "#C0392B", "solid", "rgba(192, 57, 43, 0.08)"),
            (chk_wetness, "indeks_zwilzenia_lanu", "Zwilżenie łanu", "#2980B9", "solid", None),
            (chk_thi, "indeks_thi_szkodniki", "Indeks THI (szkodniki)", "#D97706", "dot", None),
        ]
        satellite_series = [
            (chk_ndvi, "ndvi", "NDVI (wigor łanu)", "#2E7D32", "solid", "rgba(46, 125, 50, 0.10)"),
            (chk_ndmi, "ndmi", "NDMI (wilgotność łanu)", "#00838F", "dash", None),
        ]

        has_top = any(en for en, *_ in disease_series)
        has_bot = any(en for en, *_ in satellite_series)

        with chart_col:
            if has_top and has_bot:
                fig_single = make_subplots(
                    rows=2,
                    cols=1,
                    shared_xaxes=True,
                    vertical_spacing=0.12,
                    row_heights=[0.54, 0.46],
                    subplot_titles=(
                        "Presja chorób i szkodników (0–100)",
                        "Kondycja i wilgotność łanu z Sentinel-2 (0–100)",
                    ),
                )
            else:
                fig_single = make_subplots(rows=1, cols=1)

            line_shape = "spline" if smooth_lines else "linear"

            for enabled, col_k, lbl_k, color_hex, dash_style, fill_rgba in disease_series:
                if enabled and col_k in render_df.columns:
                    fig_single.add_trace(
                        go.Scatter(
                            x=render_df["data"],
                            y=render_df[col_k],
                            mode="lines",
                            name=lbl_k,
                            line=dict(color=color_hex, width=2.5, dash=dash_style, shape=line_shape, smoothing=0.65),
                            fill="tozeroy" if fill_rgba else None,
                            fillcolor=fill_rgba,
                            customdata=render_df["cloud_pct"],
                            hovertemplate="%{fullData.name}: <b>%{y:.1f}</b> (chmury: %{customdata}%)<extra></extra>",
                        ),
                        row=1,
                        col=1,
                    )

            sat_row = 2 if (has_top and has_bot) else 1
            for enabled, col_k, lbl_k, color_hex, dash_style, fill_rgba in satellite_series:
                if enabled and col_k in render_df.columns:
                    fig_single.add_trace(
                        go.Scatter(
                            x=render_df["data"],
                            y=render_df[col_k],
                            mode="lines",
                            name=lbl_k,
                            line=dict(color=color_hex, width=2.6, dash=dash_style, shape=line_shape, smoothing=0.65),
                            fill="tozeroy" if fill_rgba else None,
                            fillcolor=fill_rgba,
                            customdata=render_df["cloud_pct"],
                            hovertemplate="%{fullData.name}: <b>%{y:.1f}</b> (chmury: %{customdata}%)<extra></extra>",
                        ),
                        row=sat_row,
                        col=1,
                    )

            fig_single.update_yaxes(range=[0, 105], title_text="Indeks (0–100)", gridcolor="rgba(0,0,0,0.06)", row=1, col=1)
            if has_top and has_bot:
                fig_single.update_yaxes(range=[0, 105], title_text="Sentinel (0–100)", gridcolor="rgba(0,0,0,0.06)", row=2, col=1)

            fig_single.update_xaxes(showgrid=False)
            fig_single.update_layout(
                title=dict(
                    text=f"Pole {chosen_f_idx + 1} — przebieg od {sowing_date.strftime('%d.%m.%Y')} do {max(sowing_date, end_date_sel).strftime('%d.%m.%Y')}",
                    x=0,
                ),
                hovermode="x unified",
                height=510 if (has_top and has_bot) else 370,
                margin=dict(l=15, r=15, t=55, b=85),
                legend=dict(
                    orientation="h",
                    yanchor="top",
                    y=-0.16,
                    xanchor="left",
                    x=0,
                ),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_single, use_container_width=True, key="single_disease_sentinel_chart_clean")


if "result_df" in locals() and isinstance(result_df, pd.DataFrame) and not result_df.empty and "crop_name" in result_df.columns:
    _unsown_st_mask = result_df["crop_name"].apply(_is_unsown_crop)
    if _unsown_st_mask.any():
        for _col in result_df.columns:
            _cl = _col.lower()
            if any(w in _cl for w in ("oprysk", "spray", "status", "ocena", "etykieta", "warunk", "zabieg", "nawoz", "fert")):
                if _col == "crop_name":
                    continue
                if pd.api.types.is_numeric_dtype(result_df[_col]):
                    result_df.loc[_unsown_st_mask, _col] = 0.0
                else:
                    result_df.loc[_unsown_st_mask, _col] = "Brak (pole niezasiane)"


if "result_df" in locals() and isinstance(result_df, pd.DataFrame) and not result_df.empty and "crop_name" in result_df.columns:
    _unsown_spray_clean = result_df["crop_name"].apply(_is_unsown_crop)
    if _unsown_spray_clean.any():
        for _c in result_df.columns:
            _cl = _c.lower()
            if _c != "crop_name" and any(k in _cl for k in ("oprysk", "spray", "status", "ocena", "etykieta", "warunk", "zabieg", "decyzj")):
                if pd.api.types.is_numeric_dtype(result_df[_c]):
                    result_df.loc[_unsown_spray_clean, _c] = 0.0
                else:
                    result_df.loc[_unsown_spray_clean, _c] = "Brak uprawy — bez zabiegu"

with tab_gosp:
    # --- SAVED FARM TOP BANNER & COLLAPSIBLE MAP ---
    _persisted_fields = st.session_state.farm_profile.get('fields', {})
    _has_saved_farm = len(_persisted_fields) > 0
    if 'gosp_editor_expanded' not in st.session_state:
        st.session_state['gosp_editor_expanded'] = not _has_saved_farm
    if _has_saved_farm:
        _saved_name = st.session_state.farm_profile.get('farm_name') or 'Moje Gospodarstwo'
        _saved_uids = set(_persisted_fields.keys())
        _saved_sub = result_df[result_df['field_uid'].astype(str).isin(_saved_uids)].copy() if ('result_df' in locals() and not result_df.empty and 'field_uid' in result_df.columns) else pd.DataFrame()
        _saved_area = float(_saved_sub['area_ha'].sum()) if (not _saved_sub.empty and 'area_ha' in _saved_sub.columns) else 0.0
        st.markdown(
            f'''
            <div class="soft-card" style="border-left: 5px solid #2E7D32; background: #F4F9F4; margin-bottom: 12px;">
                <div style="font-size: 0.82rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: #2E7D32;">Zapisane gospodarstwo</div>
                <div class="soft-card-title" style="font-size: 1.35rem; margin: 2px 0 6px 0;">{_saved_name}</div>
                <div class="soft-card-sub" style="margin-bottom: 0;">
                    Liczba działek w gospodarstwie: <b>{len(_saved_uids)}</b> &nbsp;|&nbsp; Łączna powierzchnia: <b>{_saved_area:.2f} ha</b>
                </div>
            </div>
            ''',
            unsafe_allow_html=True,
        )
        if not _saved_sub.empty:
            _preview_saved = _saved_sub[['field_uid', 'crop_name', 'area_ha']].copy()
            _preview_saved['Działka'] = [f'Pole {k + 1}' for k in range(len(_preview_saved))]
            st.dataframe(
                _preview_saved[['Działka', 'crop_name', 'area_ha']].rename(columns={'crop_name': 'Uprawa', 'area_ha': 'Powierzchnia (ha)'}),
                use_container_width=True,
                hide_index=True,
            )
    # Zastosowanie kliknięć w poligony do podglądu przed zapisem
    if st.session_state.get('poly_selection_overrides') and 'result_df' in locals() and not result_df.empty:
        for _ov_uid, _ov_state in st.session_state['poly_selection_overrides'].items():
            if 'is_mine' in result_df.columns:
                result_df.loc[result_df['field_uid'].astype(str) == str(_ov_uid), 'is_mine'] = bool(_ov_state)
    _exp_title = (
        'Edytuj działki gospodarstwa i podgląd mapy (kliknij, aby rozwinąć)'
        if _has_saved_farm
        else 'Podgląd działek na mapie i wybór pól do gospodarstwa (kliknij poligon na mapie lub zaznacz na liście)'
    )
    with st.expander(_exp_title, expanded=bool(st.session_state['gosp_editor_expanded'])):
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
        if st.button("Pobierz świeże pola i pogodę LIVE dla wybranej gminy", type="primary", key="btn_fetch_gmina_live"):
            with st.spinner(f"Pobieranie danych satelitarnych (<20% chmur), gleby i pogody LIVE dla gminy {sel_gmina}..."):
                try:
                    import sys
                    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                    from src_geo.pobierz_gmine import build_gmina_dataset
                    g_fields, g_weather = build_gmina_dataset(sel_woj, sel_pow, sel_gmina, max_fields=120, force_refresh=True)
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                    if not g_fields.empty:
                        g_fields.to_parquet(DATA_DIR / "active_fields.parquet", index=False)
                    if not g_weather.empty:
                        g_weather.to_parquet(DATA_DIR / "active_weather.parquet", index=False)
                    farm_profile["wojewodztwo"] = sel_woj
                    farm_profile["powiat"] = sel_pow
                    farm_profile["gmina"] = sel_gmina
                    farm_profile["area_configured"] = True
                    farm_profile["fields"] = {}
                    save_farm_profile(farm_profile)
                    st.session_state.farm_profile = farm_profile
                    st.session_state["fetch_banner"] = f"Pobrano {len(g_fields)} pól i pogodę LIVE dla gminy {sel_gmina} ({sel_woj})!"
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Nie udało się pobrać danych gminy: {exc}")

        if sel_gmina == farm_profile.get("gmina"):
            candidates_df = raw_fields_df.copy()
        else:
            candidates_df = raw_fields_df[
                (raw_fields_df["lon"] >= active_bbox[0])
                & (raw_fields_df["lon"] <= active_bbox[2])
                & (raw_fields_df["lat"] >= active_bbox[1])
                & (raw_fields_df["lat"] <= active_bbox[3])
            ].copy()
            if candidates_df.empty:
                st.info(f"Kliknij przycisk powyżej, aby pobrać kafel działek bezpośrednio dla gminy {sel_gmina}.")
                candidates_df = raw_fields_df.copy()

        saved_map = farm_profile.get("fields", {})

        editor_rows = []
        for r in candidates_df.itertuples(index=False):
            uid = str(r.field_uid)
            is_mine = bool(st.session_state.get("poly_selection_overrides", {}).get(uid, uid in saved_map))
            _default_eco = bool(saved_map.get(uid, {}).get("is_eco", eco_active)) if is_mine else eco_active
            is_eco_val = bool(st.session_state.get("eco_selection_overrides", {}).get(uid, _default_eco))
            declared_crop = saved_map.get(uid, {}).get("crop_name", str(r.crop_name)) if is_mine else str(r.crop_name)
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
            preview_df = candidates_df.reset_index(drop=True).copy()
            preview_df["is_selected"] = preview_df["field_uid"].astype(str).map(
                lambda u: bool(st.session_state.get("poly_selection_overrides", {}).get(u, u in saved_map))
            )
            preview_df["is_eco_saved"] = preview_df["field_uid"].astype(str).map(
                lambda u: bool(
                    st.session_state.get("eco_selection_overrides", {}).get(
                        u, saved_map.get(u, {}).get("is_eco", eco_active)
                    )
                )
            )

            def _prev_color(row_s):
                if row_s["is_selected"] and row_s["is_eco_saved"]:
                    return [46, 111, 64, 235]
                if row_s["is_selected"]:
                    return [59, 110, 165, 220]
                return [180, 176, 168, 120]

            preview_df["prev_color"] = preview_df.apply(_prev_color, axis=1)
            if "polygon_json" in preview_df.columns and not preview_df.empty:
                preview_df["polygon"] = preview_df["polygon_json"].map(_normalize_pdk_polygon)
                prev_layer = pdk.Layer(
                    "PolygonLayer",
                    id="gosp_poly_layer",
                    data=preview_df,
                    pickable=True,
                    auto_highlight=True,
                    highlight_color=[255, 215, 0, 140],
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
            _sel_color_sig = hash(tuple(zip(preview_df["field_uid"].astype(str), preview_df["is_selected"], preview_df["is_eco_saved"])))
            _gosp_ev = st.pydeck_chart(prev_deck, use_container_width=True, key=f"prev_map_{sel_gmina}_{len(preview_df)}_{_sel_color_sig}", on_select="rerun", selection_mode="single-object")
            if _gosp_ev is not None and getattr(_gosp_ev, 'selection', None) and getattr(_gosp_ev.selection, 'objects', None):
                _objs = _gosp_ev.selection.objects
                _sig = str(_objs)
                if _sig != st.session_state.get('_last_gosp_poly_sig'):
                    st.session_state['_last_gosp_poly_sig'] = _sig
                    _first_list = next((v for v in _objs.values() if isinstance(v, list) and v), [])
                    _obj0 = _first_list[0] if _first_list else {}
                    if _toggle_polygon_by_click(_obj0.get('lat'), _obj0.get('lon'), str(_obj0), _obj0.get('index'), locals()):
                        st.rerun()
            _clk_info = f" | Ostatnio kliknięta: **{st.session_state['_last_clicked_uid_label']}**" if st.session_state.get("_last_clicked_uid_label") else ""
            st.caption("Zielony — wybrane działki EKO | Niebieski — pozostałe wybrane działki | Szary — nieprzypisane." + _clk_info)

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
            if isinstance(edited_df, pd.DataFrame) and not edited_df.empty and 'Działka' in edited_df.columns and 'Moje pole' in edited_df.columns:
                _need_map_refresh = False
                _ovr_mine = st.session_state.setdefault('poly_selection_overrides', {})
                _ovr_eco = st.session_state.setdefault('eco_selection_overrides', {})
                for _er_i in range(min(len(edited_df), len(editor_df))):
                    _e_uid = str(edited_df.iloc[_er_i]['Działka'])
                    _e_mine = bool(edited_df.iloc[_er_i]['Moje pole'])
                    if _e_mine != bool(editor_df.iloc[_er_i]['Moje pole']):
                        _ovr_mine[_e_uid] = _e_mine
                        _need_map_refresh = True
                    if 'Działka EKO' in edited_df.columns and 'Działka EKO' in editor_df.columns:
                        _e_eco = bool(edited_df.iloc[_er_i]['Działka EKO'])
                        if _e_eco != bool(editor_df.iloc[_er_i]['Działka EKO']):
                            _ovr_eco[_e_uid] = _e_eco
                            _need_map_refresh = True
                if _need_map_refresh:
                    st.rerun()

        selected_rows = edited_df[edited_df["Moje pole"] == True]
        eco_selected_rows = selected_rows[selected_rows["Działka EKO"] == True]
        sel_ha = float(selected_rows["Powierzchnia (ha)"].sum()) if not selected_rows.empty else 0.0
        eco_ha = float(eco_selected_rows["Powierzchnia (ha)"].sum()) if not eco_selected_rows.empty else 0.0
        fallow_rows = selected_rows[selected_rows["Deklarowana uprawa"] == FALLOW_LABEL]

        b_save, b_filter, b_clear = st.columns([1.4, 1.5, 1.0])
        with b_save:
            if st.button("Zapisz profil gospodarstwa", type="primary", use_container_width=True):
                st.session_state['gosp_editor_expanded'] = False
                st.session_state.pop('poly_selection_overrides', None)
                st.session_state.pop('eco_selection_overrides', None)
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



with tab_kalk:
    # --- WYBÓR POLA DO OPRYSKU LUB NAWOŻENIA ---
    _calc_pool = pd.DataFrame()
    if 'result_df' in locals() and not result_df.empty:
        if 'is_mine' in result_df.columns and result_df['is_mine'].any():
            _calc_pool = result_df[result_df['is_mine']].copy().reset_index(drop=True)
        else:
            _calc_pool = result_df.copy().reset_index(drop=True)
    _calc_field_area = 2.5
    _calc_field_crop = 'Pszenica ozima'
    _calc_field_eco = bool(eco_active) if 'eco_active' in locals() else False
    if not _calc_pool.empty:
        def _fmt_calc_field(idx: int) -> str:
            _rf = _calc_pool.iloc[idx]
            _cn = str(_rf.get('crop_name', 'Uprawa'))
            _ha = float(pd.to_numeric(_rf.get('area_ha', 1.0), errors='coerce') or 1.0)
            _uid_s = str(_rf.get('field_uid', ''))
            _is_e = bool(saved_fields_dict.get(_uid_s, {}).get('is_eco', _rf.get('is_eco', False))) if 'saved_fields_dict' in locals() else bool(_rf.get('is_eco', False))
            _tag = ' [EKO]' if _is_e else ''
            return f'Pole {idx + 1} — {_cn} ({_ha:.2f} ha){_tag}'
        _sel_calc_idx = st.selectbox(
            'Wybierz pole, dla którego chcesz pryskać lub nawozić:',
            options=list(range(len(_calc_pool))),
            format_func=_fmt_calc_field,
            key='calc_target_field_select',
        )
        _sel_calc_row = _calc_pool.iloc[_sel_calc_idx]
        _sel_calc_uid = str(_sel_calc_row.get('field_uid', ''))
        _calc_field_area = round(float(pd.to_numeric(_sel_calc_row.get('area_ha', 2.5), errors='coerce') or 2.5), 2)
        _calc_field_crop = str(saved_fields_dict.get(_sel_calc_uid, {}).get('crop_name', _sel_calc_row.get('crop_name', 'Pszenica ozima'))) if 'saved_fields_dict' in locals() else str(_sel_calc_row.get('crop_name', 'Pszenica ozima'))
        _calc_field_eco = bool(saved_fields_dict.get(_sel_calc_uid, {}).get('is_eco', _sel_calc_row.get('is_eco', False))) if 'saved_fields_dict' in locals() else bool(_sel_calc_row.get('is_eco', False))
        _calc_mode_txt = 'Rolnictwo EKO' if _calc_field_eco else 'Konwencjonalny'
        st.caption("Wybrane pole jest niezasiane — brak uprawy.") if _is_unsown_crop(_calc_field_crop) else st.caption("Brak uprawy na wybranym polu — status oprysków i nawożenia nie dotyczy.") if _is_unsown_crop(_calc_field_crop) else st.caption(f'Wybrane pole: **Pole {_sel_calc_idx + 1}** | Uprawa: **{_calc_field_crop}** | Powierzchnia: **{_calc_field_area:.2f} ha** | Tryb: **{_calc_mode_txt}**')
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

    st.markdown('---')
    st.markdown(
        """
        <div class="soft-card">
            <div class="soft-card-title">Kalkulator zysków i ryzyka pola (ceny nasion wg katalogu Bayer / DEKALB)</div>
            <div class="soft-card-sub" style="margin-bottom:0;">
                Symulacja kosztów kwalifikowanego materiału siewnego Bayer, nawożenia z reguł agronomicznych, ochrony roślin (pestycydów),
                przewidywanego % straty pogodowo-ryzykowej oraz potencjalnego przychodu i zysku netto dla całego pola.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    profit_base_df = result_df[result_df["is_my_field"]].copy() if (my_fields_count > 0 and "is_my_field" in result_df.columns) else result_df.copy()
    if my_fields_count == 0:
        st.info("Nie zaznaczono jeszcze własnych działek w zakładce 'Moje Gospodarstwo' — kalkulacja obejmuje wszystkie widoczne pola gminy.")

    ctrl_c1, ctrl_c2 = st.columns([1.2, 2.2])
    with ctrl_c1:
        loss_adj = st.slider(
            "Korekta przewidywanego % straty plonu (symulacja ryzyka):",
            min_value=-10.0,
            max_value=25.0,
            value=0.0,
            step=0.5,
            format="%+.1f%%",
            key="profit_loss_offset",
        )
        st.caption("Bazowy % straty wyliczany jest automatycznie z poziomu ryzyka reguły, pogody i wigoru NDVI.")

    with ctrl_c2:
        with st.expander("Cennik nasion Bayer / DEKALB, ŚOR i cen skupu (kliknij, aby edytować)", expanded=False):
            price_rows = []
            for crop_k, v in BAYER_SEED_CATALOG.items():
                price_rows.append({
                    "Uprawa": crop_k,
                    "Materiał siewny Bayer": v["odmiana_bayer"],
                    "Koszt ziarna Bayer (zł/ha)": float(v["cena_ziarna_zl_ha"]),
                    "Koszt pestycydów (zł/ha)": float(v["cena_pestycydow_zl_ha"]),
                    "Cena nawozu (zł/t)": float(v["cena_nawozu_zl_t"]),
                    "Plon bazowy (t/ha)": float(v["plon_bazowy_t_ha"]),
                    "Cena skupu (zł/t)": float(v["cena_skupu_zl_t"]),
                })
            edited_prices_df = st.data_editor(
                pd.DataFrame(price_rows),
                use_container_width=True,
                hide_index=True,
                key="bayer_price_editor",
                column_config={
                    "Uprawa": st.column_config.TextColumn(disabled=True),
                    "Materiał siewny Bayer": st.column_config.TextColumn(disabled=True),
                },
            )
            custom_bayer_map = {}
            for pr in edited_prices_df.itertuples(index=False):
                custom_bayer_map[str(pr[0])] = {
                    "cena_ziarna_zl_ha": float(pr[2]),
                    "cena_pestycydow_zl_ha": float(pr[3]),
                    "cena_nawozu_zl_t": float(pr[4]),
                    "plon_bazowy_t_ha": float(pr[5]),
                    "cena_skupu_zl_t": float(pr[6]),
                }

    profit_df = calculate_profit_forecast(profit_base_df, custom_prices=custom_bayer_map, loss_offset_pct=loss_adj)

    if not profit_df.empty:
        tot_area = float(profit_df["area_ha"].sum())
        tot_seed = float(profit_df["koszt_ziarna_zl"].sum())
        tot_fert = float(profit_df["koszt_nawozu_zl"].sum())
        tot_pest = float(profit_df["koszt_pestycydow_zl"].sum())
        tot_cost = float(profit_df["koszt_calkowity_zl"].sum())
        avg_loss = float(profit_df["strata_pct"].mean())
        tot_rev = float(profit_df["przychod_po_stracie_zl"].sum())
        tot_net = float(profit_df["zysk_netto_zl"].sum())

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Koszt ziarna", f"{tot_seed:,.0f} zł".replace(",", " "))
        k2.metric("Koszt nawozów", f"{tot_fert:,.0f} zł".replace(",", " "))
        k3.metric("Koszt pestycydów", f"{tot_pest:,.0f} zł".replace(",", " "))
        k4.metric("Śr. strata plonu", f"{avg_loss:.1f} %")
        k5.metric("Przychód (po stracie)", f"{tot_rev:,.0f} zł".replace(",", " "))
        k6.metric(
            "Zysk netto całości",
            f"{tot_net:,.0f} zł".replace(",", " "),
            delta=f"{(tot_net / tot_area if tot_area > 0 else 0):,.0f} zł/ha".replace(",", " "),
        )

        # Symulacja wybranego pojedynczego pola
        sel_uid = st.selectbox(
            "Szczegółowa analiza dla wybranego pola:",
            profit_df["field_uid"],
            format_func=lambda u: f"{u} — {profit_df.loc[profit_df['field_uid'] == u, 'crop_name'].iloc[0]} ({profit_df.loc[profit_df['field_uid'] == u, 'area_ha'].iloc[0]:.2f} ha)",
            key="profit_single_field_sel",
        )
        one = profit_df[profit_df["field_uid"] == sel_uid].iloc[0]
        st.info(
            f"**Pole {one['field_uid']} ({one['area_ha']:.2f} ha) · {one['crop_name']}** | "
            f"Materiał siewny: *{one['bayer_seed_info']}*\n\n"
            f"• **Koszt ziarna Bayer:** {one['koszt_ziarna_zl']:,.2f} zł  |  "
            f"**Koszt nawozu:** {one['koszt_nawozu_zl']:,.2f} zł  |  "
            f"**Koszt pestycydów:** {one['koszt_pestycydow_zl']:,.2f} zł  "
            f"(**Razem koszty:** {one['koszt_calkowity_zl']:,.2f} zł)\n\n"
            f"• **Przewidywana strata:** {one['strata_pct']:.1f}%  |  "
            f"**Szacowany plon:** {one['szacowany_plon_t_ha']:.2f} t/ha  |  "
            f"**Potencjalny przychód ze sprzedaży całego pola:** {one['przychod_po_stracie_zl']:,.2f} zł  |  "
            f"**Zysk netto pola:** **{one['zysk_netto_zl']:,.2f} zł** ({one['zysk_netto_zl_ha']:,.0f} zł/ha)"
        )

        # Wykres struktury kosztów i zysku dla pól
        top_p = profit_df.head(15).copy()
        fig_prof = go.Figure()
        fig_prof.add_bar(name="Ziarno", x=top_p["field_uid"], y=top_p["koszt_ziarna_zl"], marker_color="#4E79A7")
        fig_prof.add_bar(name="Nawozy", x=top_p["field_uid"], y=top_p["koszt_nawozu_zl"], marker_color="#8E6C8A")
        fig_prof.add_bar(name="Pestycydy", x=top_p["field_uid"], y=top_p["koszt_pestycydow_zl"], marker_color="#E15759")
        fig_prof.add_bar(name="Zysk netto pola", x=top_p["field_uid"], y=top_p["zysk_netto_zl"], marker_color="#2E7D32")
        fig_prof.update_layout(
            barmode="group",
            title="Struktura kosztów (ziarno Bayer, nawozy, pestycydy) i zysku netto na polach [zł]",
            height=340,
            margin=dict(l=20, r=20, t=45, b=20),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_prof, use_container_width=True)

        disp_cols = [
            "field_uid", "crop_name", "area_ha", "bayer_seed_info",
            "koszt_ziarna_zl", "koszt_nawozu_zl", "koszt_pestycydow_zl", "koszt_calkowity_zl",
            "strata_pct", "przychod_po_stracie_zl", "zysk_netto_zl", "zysk_netto_zl_ha",
        ]
        st.dataframe(
            profit_df[disp_cols].rename(columns={
                "field_uid": "Działka",
                "crop_name": "Uprawa",
                "area_ha": "Pow. (ha)",
                "bayer_seed_info": "Nasiona Bayer / DEKALB",
                "koszt_ziarna_zl": "Ziarno (zł)",
                "koszt_nawozu_zl": "Nawozy (zł)",
                "koszt_pestycydow_zl": "Pestycydy (zł)",
                "koszt_calkowity_zl": "Koszty razem (zł)",
                "strata_pct": "Strata (%)",
                "przychod_po_stracie_zl": "Przychód pola (zł)",
                "zysk_netto_zl": "Zysk netto (zł)",
                "zysk_netto_zl_ha": "Zysk (zł/ha)",
            }),
            use_container_width=True,
            hide_index=True,
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

    st.write("")
    with st.expander("➕ Dodaj własną regułę zabiegową", expanded=False):
        st.caption("Nowa reguła zostanie zapisana w pliku reguly_agronomiczne.csv i od razu uwzględniona przez silnik decyzji.")
        with st.form("form_add_custom_rule", clear_on_submit=True):
            rc1, rc2, rc3 = st.columns(3)
            r_uprawa = rc1.selectbox("Uprawa:", ["WSZYSTKIE"] + [c for c in KNOWN_CROPS if c != FALLOW_LABEL])
            r_zagrozenie = rc2.text_input("Zagrożenie / Cel zabiegu:", value="Presja chorób / Dokarmianie")
            r_decyzja = rc3.selectbox("Decyzja:", ["PRYSKAJ TERAZ", "NAWOŹ", "ZASIEJ", "ZBIERAJ", "CZEKAJ", "MONITORUJ"])

            rc4, rc5, rc6, rc7 = st.columns(4)
            r_tmin = rc4.number_input("Temp. min (°C):", value=8.0, step=0.5)
            r_tmax = rc5.number_input("Temp. max (°C):", value=25.0, step=0.5)
            r_wiatr = rc6.number_input("Wiatr max (m/s):", value=4.0, step=0.5)
            r_ndvi = rc7.number_input("Próg NDVI:", value=0.45, min_value=0.0, max_value=1.0, step=0.05)

            rc8, rc9 = st.columns([1, 2])
            r_ryzyko = rc8.selectbox("Poziom ryzyka:", ["NISKI", "ŚREDNI", "WYSOKI", "KRYTYCZNY"], index=1)
            r_komunikat = rc9.text_input("Komunikat dla rolnika:", value="Własna reguła gospodarstwa: wykonaj zabieg w oknie pogodowym")

            rc10, rc11 = st.columns(2)
            r_nawoz = rc10.text_input("Zalecany środek / nawóz (opcjonalnie):", value="")
            r_eko = rc11.text_input("Status EKO (opcjonalnie):", value="TAK (EKO — wykaz IUNG)")

            submitted_rule = st.form_submit_button("Zapisz nową regułę", type="primary")
            if submitted_rule:
                rules_csv = Path(__file__).parent / "data_app" / "reguly_agronomiczne.csv"
                sep = ";"
                if rules_csv.exists():
                    header_line = rules_csv.read_text(encoding="utf-8-sig").splitlines()[0]
                    sep = ";" if ";" in header_line else ","
                    existing_df = pd.read_csv(rules_csv, sep=sep, encoding="utf-8-sig")
                else:
                    existing_df = rules_df.drop(columns=["decyzja_norm"], errors="ignore").copy()

                new_row = {
                    "rule_id": f"USR-{len(existing_df)+1:03d}",
                    "uprawa": r_uprawa,
                    "zagrozenie": r_zagrozenie.strip(),
                    "temp_min_c": r_tmin,
                    "temp_max_c": r_tmax,
                    "wilgotnosc_min_pct": 40.0,
                    "opad_24h_min_mm": 0.0,
                    "wiatr_max_ms": r_wiatr,
                    "ndvi_prog": r_ndvi,
                    "decyzja": r_decyzja,
                    "poziom_ryzyka": r_ryzyko,
                    "komunikat": r_komunikat.strip(),
                    "ph_min": "",
                    "ph_max": "",
                    "soc_max_g_kg": "",
                    "zalecany_nawoz": r_nawoz.strip(),
                    "nawozy_eko": r_eko.strip(),
                }
                for col in existing_df.columns:
                    new_row.setdefault(col, "")
                updated_rules = pd.concat([existing_df, pd.DataFrame([new_row])[existing_df.columns]], ignore_index=True)
                updated_rules.to_csv(rules_csv, sep=sep, index=False, encoding="utf-8-sig")
                st.cache_data.clear()
                st.success(f"Dodano regułę {new_row['rule_id']} ({r_uprawa} -> {r_decyzja})!")
                st.rerun()
# --- Poza wszystkimi blokami `with tab_...:` (bez wcięcia) ---
render_farmhand_bubble(
    result_df=result_df,
    farm_profile=st.session_state.get("farm_profile", {}),
    selected_timestamp=selected_ts,
    eco_mode=eco_active,
)
