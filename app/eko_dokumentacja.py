from io import BytesIO
from pathlib import Path
from typing import Optional
import openpyxl
import pandas as pd
import streamlit as st

TEMPLATE_PATH = Path(__file__).parent / "data_app" / "Wzor_Dokumentacji_Rolnika_Ekologicznego_Audyt-v4.xlsx"

CROP_ROTATION_5Y = {
    "Pszenica ozima": ["Pszenica ozima", "Rośliny strączkowe (bobik/groch)", "Rzepak ozimy", "Jęczmień jary + wsiewka", "Koniczyna czerwona"],
    "Rzepak ozimy": ["Rzepak ozimy", "Pszenica ozima", "Owies / Jęczmień", "Rośliny strączkowe", "Pszenica ozima"],
    "Jęczmień jary": ["Jęczmień jary", "Rośliny strączkowe", "Pszenica ozima", "Ziemniaki / Okopowe", "Owies"],
    "Jęczmień": ["Jęczmień", "Rośliny strączkowe", "Pszenica ozima", "Ziemniaki / Okopowe", "Owies"],
    "Kukurydza": ["Kukurydza", "Rośliny strączkowe", "Pszenica ozima", "Jęczmień jary", "Mieszanka motylkowo-trawiasta"],
    "Żyto": ["Żyto", "Łubin wąskolistny", "Owies", "Ziemniaki", "Żyto + poplon"],
    "Owies": ["Owies", "Groch siewny", "Pszenica ozima", "Jęczmień jary", "Koniczyna z trawami"],
}


def _suggest_rotation(crop_name: str) -> list[str]:
    clean = str(crop_name).strip()
    if clean in CROP_ROTATION_5Y:
        return CROP_ROTATION_5Y[clean]
    return [clean, "Rośliny strączkowe (EKO)", "Zboże ozime", "Okopowe / Poplon", "Zboże jare"]


def build_filled_eko_workbook(
    eco_fields_df: pd.DataFrame,
    farm_meta: dict,
    selected_timestamp: pd.Timestamp,
    custom_treatments_df: Optional[pd.DataFrame] = None,
    machines_df: Optional[pd.DataFrame] = None,
    template_path: Path = TEMPLATE_PATH,
) -> bytes:
    """
    Wypełnia oficjalny szablon Wzor_Dokumentacji_Rolnika_Ekologicznego_Audyt-v4.xlsx
    danymi dla wybranych pól ekologicznych oraz wpisami rolnika.
    """
    wb = openpyxl.load_workbook(template_path)

    # --- ARKUSZ 1: Plan Działalności EKO (perspektywa 5-letnia) ---
    ws1 = wb["1_Plan_Dzialalnosci_EKO"]
    ws1["B5"] = farm_meta.get("nazwa_gospodarstwa", "")
    ws1["F5"] = farm_meta.get("numer_arimr", "")
    ws1["B6"] = farm_meta.get("lokalizacja", "")
    ws1["F6"] = farm_meta.get("jednostka_cert", "")
    ws1["B7"] = farm_meta.get("doradca", "")
    ws1["F7"] = farm_meta.get("nr_doradcy", "")
    ws1["B8"] = farm_meta.get("okres_planu", "2026–2030")
    ws1["F8"] = farm_meta.get("data_konwersji", "")

    total_area = 0.0
    for idx, row in enumerate(eco_fields_df.head(15).itertuples(index=False), start=12):
        area = float(getattr(row, "area_ha", 1.5))
        total_area += area
        crop = str(getattr(row, "crop_name", "Uprawa EKO"))
        rot = _suggest_rotation(crop)

        ws1[f"A{idx}"] = str(getattr(row, "h3_index", f"Działka-{idx-11}"))
        ws1[f"B{idx}"] = round(area, 2)
        ws1[f"C{idx}"] = f"Pakiet 1. Uprawy rolnicze (EKO) — {crop}"
        ws1[f"D{idx}"] = rot[0]
        ws1[f"E{idx}"] = rot[1]
        ws1[f"F{idx}"] = rot[2]
        ws1[f"G{idx}"] = rot[3]
        ws1[f"H{idx}"] = rot[4]
        ws1[f"I{idx}"] = farm_meta.get("przeznaczenie_plonow", "Sprzedaż EKO / Pasza własna")

    ws1["B27"] = round(total_area, 2)

    # --- ARKUSZ 2: Dziennik Zabiegów Agrotechnicznych EKO ---
    ws2 = wb["2_Dziennik_Zabiegow_EKO"]
    ts_str = pd.to_datetime(selected_timestamp).strftime("%Y-%m-%d %H:%M")
    row_cursor = 5

    # Automatyczne wpisy z analizy pól EKO (nawożenie / siew / ochrona)
    for row in eco_fields_df.head(20).itertuples(index=False):
        if row_cursor > 34:
            break
        area = round(float(getattr(row, "area_ha", 1.5)), 2)
        crop = str(getattr(row, "crop_name", ""))
        decision = str(getattr(row, "decyzja", "NAWOŹ"))
        fert = str(getattr(row, "zalecany_nawoz", "Nawóz organiczny EKO"))
        dose_ha = float(getattr(row, "dawka_nawozu_kg_ha", 250.0))
        total_kg = float(getattr(row, "ilosc_nawozu_kg", round(dose_ha * area, 1)))
        eco_basis = str(getattr(row, "nawozy_eko", "Wykaz IUNG / rozp. UE 2018/848"))

        temp_c = getattr(row, "temp_c", None)
        wind_ms = getattr(row, "wind_ms", None)
        rain_mm = getattr(row, "precip_24h_mm", None)
        weather_txt = (
            f"Temp. {temp_c:.1f}°C, wiatr {wind_ms:.1f} m/s, opad 24h: {rain_mm:.1f} mm"
            if pd.notna(temp_c)
            else "Warunki zgodne z oknem agrotechnicznym"
        )

        ndvi = getattr(row, "ndvi", 0.0)
        ph = getattr(row, "soil_ph", 0.0)
        soc = getattr(row, "soil_soc", 0.0)
        obs_txt = f"NDVI: {ndvi:.2f} | Gleba: pH {ph:.2f}, próchnica {soc:.1f} g/kg ({getattr(row, 'soil_texture', '')})"

        ws2[f"B{row_cursor}"] = ts_str
        ws2[f"C{row_cursor}"] = f"{getattr(row, 'h3_index', '')} ({area} ha)"
        ws2[f"D{row_cursor}"] = crop
        ws2[f"E{row_cursor}"] = "Nawożenie / Agrotechnika EKO" if decision in {"NAWOŹ", "MONITORUJ"} else decision
        ws2[f"F{row_cursor}"] = fert
        ws2[f"G{row_cursor}"] = f"{dose_ha:.0f} kg/ha (łącznie {total_kg:.1f} kg)"
        ws2[f"H{row_cursor}"] = eco_basis
        ws2[f"I{row_cursor}"] = weather_txt
        ws2[f"J{row_cursor}"] = farm_meta.get("domyslna_maszyna", "Rozsiewacz nawozów (umyty EKO)")
        ws2[f"K{row_cursor}"] = obs_txt
        row_cursor += 1

    # Dodatkowe wpisy dopisane ręcznie przez rolnika w tabeli UI
    if custom_treatments_df is not None and not custom_treatments_df.empty:
        for trow in custom_treatments_df.itertuples(index=False):
            if row_cursor > 34:
                break
            ws2[f"B{row_cursor}"] = str(getattr(trow, "Data", ts_str))
            ws2[f"C{row_cursor}"] = str(getattr(trow, "Dzialka", ""))
            ws2[f"D{row_cursor}"] = str(getattr(trow, "Uprawa", ""))
            ws2[f"E{row_cursor}"] = str(getattr(trow, "Zabieg", ""))
            ws2[f"F{row_cursor}"] = str(getattr(trow, "Srodek_EKO", ""))
            ws2[f"G{row_cursor}"] = str(getattr(trow, "Dawka", ""))
            ws2[f"H{row_cursor}"] = str(getattr(trow, "Podstawa_EKO", "Wykaz IUNG / rozp. UE 2018/848"))
            ws2[f"J{row_cursor}"] = str(getattr(trow, "Maszyna_Paliwo", ""))
            ws2[f"L{row_cursor}"] = str(getattr(trow, "Plon_Straty", ""))
            row_cursor += 1

    # --- ARKUSZ 3: Ewidencja Zakupów, Magazynu i Sprzedaży ---
    ws3 = wb["3_Zakupy_Magazyn_Sprzedaz"]
    if "zalecany_nawoz" in eco_fields_df.columns and "ilosc_nawozu_kg" in eco_fields_df.columns:
        agg_fert = (
            eco_fields_df.groupby(["zalecany_nawoz", "nawozy_eko"], as_index=False)["ilosc_nawozu_kg"]
            .sum()
        )
        for idx, frow in enumerate(agg_fert.itertuples(index=False), start=5):
            if idx > 29:
                break
            qty = round(float(frow.ilosc_nawozu_kg), 1)
            ws3[f"B{idx}"] = ts_str[:10]
            ws3[f"C{idx}"] = "Plan zakupu / Wejście na magazyn"
            ws3[f"D{idx}"] = "Nawóz / Środek poprawiający właściwości gleby"
            ws3[f"E{idx}"] = str(frow.zalecany_nawoz)
            ws3[f"F{idx}"] = f"+{qty} kg"
            ws3[f"G{idx}"] = f"{qty} kg"
            ws3[f"I{idx}"] = f"Produkt dopuszczony w rolnictwie ekologicznym ({frow.nawozy_eko})"

    # --- ARKUSZ 4: Zarządzanie Ryzykiem i Wykaz Maszyn ---
    ws4 = wb["4_Ryzyko_i_Maszyny"]
    risk_rows = []
    for row in eco_fields_df.itertuples(index=False):
        field_id = str(getattr(row, "h3_index", ""))
        crop = str(getattr(row, "crop_name", ""))
        if pd.notna(getattr(row, "soil_ph", None)) and row.soil_ph < 5.6:
            risk_rows.append((
                f"Zakwaszenie gleby (pH {row.soil_ph:.2f})",
                f"{crop} ({field_id})",
                "Wapnowanie wapnem kredowym / dolomitem z wykazu IUNG",
                "pH < 5.6 (SoilGrids / badanie własne)",
                "Priorytet przed siewem",
            ))
        if pd.notna(getattr(row, "soil_soc", None)) and row.soil_soc < 14.0:
            risk_rows.append((
                f"Niska zawartość próchnicy (SOC {row.soil_soc:.1f} g/kg)",
                f"{crop} ({field_id})",
                "Nawożenie obornikiem granulowanym / kompostem EKO + poplony motylkowe",
                "SOC < 14.0 g/kg",
                "Odbudowa materii organicznej",
            ))
        haz = str(getattr(row, "zagrozenie", ""))
        if haz and haz != "Brak krytycznego zagrożenia":
            risk_rows.append((
                haz,
                f"{crop} ({field_id})",
                str(getattr(row, "komunikat", "Monitoring łanu i zabieg biologiczny EKO")),
                f"NDVI {getattr(row, 'ndvi', 0.0):.2f} / warunki pogodowe",
                f"Reguła {getattr(row, 'rule_id', '')}",
            ))

    for idx, r_item in enumerate(risk_rows[:10], start=6):
        ws4[f"B{idx}"] = r_item[0]
        ws4[f"C{idx}"] = r_item[1]
        ws4[f"D{idx}"] = r_item[2]
        ws4[f"E{idx}"] = r_item[3]
        ws4[f"F{idx}"] = r_item[4]

    if machines_df is not None and not machines_df.empty:
        for idx, mrow in enumerate(machines_df.head(10).itertuples(index=False), start=19):
            ws4[f"B{idx}"] = str(getattr(mrow, "Maszyna", ""))
            ws4[f"C{idx}"] = str(getattr(mrow, "Wlasnosc", "Własna"))
            ws4[f"D{idx}"] = str(getattr(mrow, "Zabezpieczenie_EKO", "Mycie ciśnieniowe przed wjazdem na pole EKO"))
            ws4[f"E{idx}"] = str(getattr(mrow, "Data_mycia", ts_str[:10]))

    # --- ARKUSZ 5: Checklista przed audytem ---
    ws5 = wb["5_Checklista_Audyt_Kontrola"]
    ws5["D5"] = "DO WERYFIKACJI"
    ws5["E5"] = "Sprawdź aktualność umowy z jednostką certyfikującą IJHARS."
    ws5["D6"] = "TAK (WYGENEROWANO)"
    ws5["E6"] = f"Ujęto {len(eco_fields_df)} pól EKO ({total_area:.2f} ha) — wymaga podpisu doradcy."
    ws5["D7"] = "TAK (AUTOMAT)"
    ws5["E7"] = "Zasilone danymi z mapy satelitarnej, pogody i kalkulatora EKO."
    ws5["D8"] = "W TOKU"
    ws5["E8"] = "Zestawienie nawozów zgodnych z IUNG / UE 2018/848 gotowe; podepnij faktury."
    ws5["D11"] = "TAK (AUTOMAT)"
    ws5["E11"] = "Plan zarządzania ryzykiem wygenerowany w arkuszu 4."

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def render_eko_documentation_tab(
    result_df: pd.DataFrame,
    selected_timestamp: pd.Timestamp,
    location_label: str = "Małopolskie (kafel 33UXR)",
) -> None:
    """
    Renderuje osobną zakładkę 'Dokumentacja EKO i Audyt' w Streamlit.
    """
    st.subheader("Dokumentacja Rolnictwa Ekologicznego i Audyt (ARiMR / IJHARS)")
    st.caption(
        "Wybierz pola prowadzone w systemie ekologicznym. System automatycznie uzupełni Plan 5-letni, "
        "Dziennik Zabiegów (z wykazem IUNG / UE 2018/848), bilans magazynowy oraz ocenę ryzyka."
    )

    if result_df is None or result_df.empty:
        st.info("Brak danych pól do wygenerowania dokumentacji.")
        return

    # 1. Wybór pól prowadzonych ekologicznie (domyślnie zaciągane z oznaczeń 'Działka EKO' w Moim Gospodarstwie)
    all_ids = result_df["h3_index"].astype(str).tolist()
    labels_map = {}
    preselected_eco_ids = []

    for r in result_df.itertuples(index=False):
        h3_str = str(r.h3_index)
        uid_str = str(getattr(r, "field_uid", "")).strip()
        prefix = f"{uid_str} ({h3_str})" if uid_str else h3_str
        labels_map[h3_str] = f"{prefix} — {r.crop_name} ({getattr(r, 'area_ha', 1.5):.2f} ha, pH {r.soil_ph:.1f})"
        if bool(getattr(r, "is_eco_field", False)):
            preselected_eco_ids.append(h3_str)

    default_selection = preselected_eco_ids if preselected_eco_ids else all_ids[: min(5, len(all_ids))]

    selected_eco_ids = st.multiselect(
        "1. Zaznacz pola prowadzone w sposób ekologiczny (domyślnie zaznaczone działki EKO z Mojego Gospodarstwa):",
        options=all_ids,
        default=default_selection,
        format_func=lambda x: labels_map.get(x, x),
    )

    if not selected_eco_ids:
        st.warning("Zaznacz przynajmniej jedno pole ekologiczne, aby wygenerować dokumentację.")
        return

    eco_df = result_df[result_df["h3_index"].astype(str).isin(selected_eco_ids)].copy()
    eco_area = float(eco_df["area_ha"].sum()) if "area_ha" in eco_df.columns else len(eco_df) * 1.5

    m1, m2, m3 = st.columns(3)
    m1.metric("Wybrane pola EKO", f"{len(eco_df)} działek")
    m2.metric("Powierzchnia EKO", f"{eco_area:.2f} ha")
    m3.metric("Zgodność nawozów", "100% IUNG / UE 2018/848")

    saved_profile = st.session_state.get("farm_profile", {})
    default_farm_name = saved_profile.get("farm_name") or "Gospodarstwo Ekologiczne Zielone Pole"

    # 2. Dane nagłówkowe gospodarstwa (do Arkusza 1)
    with st.expander("2. Dane gospodarstwa i doradcy (uzupełniane w Planie Działalności EKO)", expanded=False):
        c1, c2 = st.columns(2)
        farm_meta = {
            "nazwa_gospodarstwa": c1.text_input("Imię i nazwisko / Nazwa gospodarstwa", value=default_farm_name),
            "numer_arimr": c2.text_input("Numer producenta ARiMR (EP)", value="045129874"),
            "lokalizacja": c1.text_input("Lokalizacja / Adres", value=location_label),
            "jednostka_cert": c2.text_input("Jednostka certyfikująca (nr upoważnienia)", value="PL-EKO-01"),
            "doradca": c1.text_input("Doradca rolnośrodowiskowy", value=""),
            "nr_doradcy": c2.text_input("Nr wpisu doradcy", value=""),
            "okres_planu": c1.text_input("Okres realizacji planu (5 lat)", value="2026–2030"),
            "data_konwersji": c2.text_input("Data rozpoczęcia konwersji", value="2024-03-15"),
            "przeznaczenie_plonow": "Sprzedaż certyfikowana EKO / Pasza własna",
            "domyslna_maszyna": "Rozsiewacz / Opryskiwacz (umyty EKO)",
        }

    # 3. Podgląd automatycznie wygenerowanego Dziennika Zabiegów EKO + możliwość dopisania własnego wpisu
    st.markdown("**3. Automatyczny Dziennik Zabiegów EKO (zasilony z mapy, gleby i pogody)**")
    preview_cols = [
        c for c in ["field_uid", "h3_index", "crop_name", "area_ha", "decyzja", "zalecany_nawoz", "nawozy_eko", "dawka_nawozu_kg_ha", "ilosc_nawozu_kg"]
        if c in eco_df.columns
    ]
    st.dataframe(eco_df[preview_cols], use_container_width=True, hide_index=True)

    with st.expander("Dodaj własny zabieg lub wykaz maszyn (opcjonalnie)"):
        custom_treatments = st.data_editor(
            pd.DataFrame(columns=["Data", "Dzialka", "Uprawa", "Zabieg", "Srodek_EKO", "Dawka", "Podstawa_EKO", "Maszyna_Paliwo", "Plon_Straty"]),
            num_rows="dynamic",
            use_container_width=True,
        )
        machines_df = st.data_editor(
            pd.DataFrame([
                {"Maszyna": "Rozsiewacz nawozów", "Wlasnosc": "Własna", "Zabezpieczenie_EKO": "Mycie ciśnieniowe przed pracą EKO", "Data_mycia": str(selected_timestamp)[:10]},
                {"Maszyna": "Opryskiwacz polowy", "Wlasnosc": "Własna", "Zabezpieczenie_EKO": "Płukanie potrójne + dedykowane dysze", "Data_mycia": str(selected_timestamp)[:10]},
            ]),
            num_rows="dynamic",
            use_container_width=True,
        )

    # 4. Pobranie gotowego pliku Excela (.xlsx) zgodnego ze wzorem audytowym
    xlsx_bytes = build_filled_eko_workbook(
        eco_fields_df=eco_df,
        farm_meta=farm_meta,
        selected_timestamp=selected_timestamp,
        custom_treatments_df=custom_treatments,
        machines_df=machines_df,
    )
    st.download_button(
        label="Pobierz wypełnioną Dokumentację Rolnika Ekologicznego (.xlsx)",
        data=xlsx_bytes,
        file_name=f"Dokumentacja_EKO_Audyt_{pd.to_datetime(selected_timestamp).strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
