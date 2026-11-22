import argparse
import datetime as dt
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import xarray as xr

DEFAULT_AREA = [51.80, 20.60, 51.45, 21.20]

ERA5_LAND_DATASET = "reanalysis-era5-land-monthly-means"
ERA5_LAND_VARS = {
    "2m_temperature": "t2m",
    "2m_dewpoint_temperature": "d2m",
    "soil_temperature_level_1": "stl1",
    "volumetric_soil_water_layer_1": "swvl1",
    "volumetric_soil_water_layer_2": "swvl2",
    "volumetric_soil_water_layer_3": "swvl3",
    "total_precipitation": "tp",
    "potential_evaporation": "pev",
}

LAYER_THICKNESS = {"swvl1": 0.07, "swvl2": 0.21, "swvl3": 0.72}

SOIL_PARAMS = {
    1: ("gruboziarnista", 0.403, 0.244, 0.059),
    2: ("średnia", 0.439, 0.347, 0.151),
    3: ("średnio-drobna", 0.430, 0.383, 0.133),
    4: ("drobna", 0.520, 0.448, 0.279),
    5: ("bardzo drobna", 0.614, 0.541, 0.335),
    6: ("organiczna", 0.766, 0.663, 0.267),
    7: ("tropikalna organiczna", 0.472, 0.323, 0.151),
}

WEIGHTS = {
    "intercept": -2.0,
    "SMA": -1.2,
    "SPEI3": -0.8,
    "VPDz": 0.4,
    "STLz": 0.3,
    "PAW": -1.5,
}

CLASSES = [(0.2, "brak"), (0.4, "niskie"), (0.6, "umiarkowane"), (0.8, "wysokie"), (1.01, "bardzo wysokie")]
GROWING_SEASON = range(4, 10)

_ND = NormalDist()


def normalize(ds: xr.Dataset) -> xr.Dataset:
    ren = {}
    if "time" not in ds.dims:
        for name in ("valid_time", "forecast_reference_time", "date"):
            if name in ds.dims:
                ren[name] = "time"
                break
    for a, b in (("lat", "latitude"), ("lon", "longitude")):
        if a in ds.dims:
            ren[a] = b
    ds = ds.rename(ren)
    if "expver" in ds.dims and ds.sizes["expver"] > 1:
        ds = ds.mean("expver", skipna=True)
    for d in list(ds.dims):
        if d not in ("time", "latitude", "longitude") and ds.sizes[d] == 1:
            ds = ds.squeeze(d, drop=True)
    ds = ds.drop_vars([c for c in ds.coords if c not in ds.dims], errors="ignore")
    if "time" in ds.dims:
        ds = ds.assign_coords(time=pd.DatetimeIndex(ds["time"].values).to_period("M").to_timestamp())
        ds = ds.sortby("time")
    return ds


def _cds(dataset: str, request: dict) -> xr.Dataset:
    import earthkit.data as ekd

    print(f"  CDS: {dataset} ({len(request.get('year', []))} lat, {len(request['variable'])} zmiennych)…")
    return normalize(ekd.from_source("cds", dataset, request).to_xarray())


def fetch_era5_land(area, year_from: int, year_to: int) -> xr.Dataset:
    today = dt.date.today()
    base = {
        "product_type": ["monthly_averaged_reanalysis"],
        "variable": list(ERA5_LAND_VARS),
        "time": ["00:00"],
        "area": area,
        "data_format": "grib",
        "download_format": "unarchived",
    }
    parts = []
    full_years = [str(y) for y in range(year_from, min(year_to, today.year - 1) + 1)]
    if full_years:
        parts.append(_cds(ERA5_LAND_DATASET, {**base, "year": full_years,
                                              "month": [f"{m:02d}" for m in range(1, 13)]}))
    if year_to >= today.year and today.month > 1:
        # dane miesięczne publikowane są kilka dni po końcu miesiąca
        last = today.month - 1 if today.day > 7 else today.month - 2
        if last >= 1:
            parts.append(_cds(ERA5_LAND_DATASET, {**base, "year": [str(today.year)],
                                                  "month": [f"{m:02d}" for m in range(1, last + 1)]}))
    ds = xr.concat(parts, dim="time") if len(parts) > 1 else parts[0]
    return ds[list(ERA5_LAND_VARS.values())]


def fetch_soil_type(area) -> xr.DataArray:
    """Typ gleby (pole stałe) z ERA5, przeliczony na siatkę 0.1°."""
    req = {
        "product_type": ["reanalysis"],
        "variable": ["soil_type"],
        "year": ["2020"], "month": ["01"], "day": ["01"], "time": ["00:00"],
        "area": area,
        "grid": [0.1, 0.1],
        "data_format": "grib",
        "download_format": "unarchived",
    }
    ds = _cds("reanalysis-era5-single-levels", req)
    slt = ds["slt"]
    if "time" in slt.dims:
        slt = slt.isel(time=0, drop=True)
    return slt

def demo_data(area, year_from: int, year_to: int, seed: int = 1):
    rng = np.random.default_rng(seed)
    n, w, s, e = area
    lat = np.round(np.arange(n, s - 1e-9, -0.1), 2)
    lon = np.round(np.arange(w, e + 1e-9, 0.1), 2)
    time = pd.date_range(f"{year_from}-01-01", f"{year_to}-12-01", freq="MS")
    nt, ny, nx = len(time), len(lat), len(lon)
    month = time.month.values
    season = np.cos(2 * np.pi * (month - 7) / 12)[:, None, None]

    anom = np.zeros(nt)
    for i in range(1, nt):
        anom[i] = 0.7 * anom[i - 1] + rng.normal(0, 0.6)
    last_summer = (time.year == year_to) & np.isin(month, [5, 6, 7, 8])
    anom[last_summer] += 2.0
    a = anom[:, None, None] + rng.normal(0, 0.2, (nt, ny, nx))

    t2m = 281.0 + 10.0 * season + 1.2 * a
    d2m = t2m - (5.0 + 2.0 * season + 1.5 * a)
    stl1 = 282.0 + 11.0 * season + 1.4 * a
    tp = np.clip((1.8 + 0.8 * season - 0.6 * a) / 1000, 0, None)
    pev = -np.clip((1.2 + 2.2 * season + 0.4 * a) / 1000, 0, None)
    sm = 0.30 - 0.05 * season - 0.035 * a
    ds = xr.Dataset(
        {
            "t2m": (("time", "latitude", "longitude"), t2m),
            "d2m": (("time", "latitude", "longitude"), d2m),
            "stl1": (("time", "latitude", "longitude"), stl1),
            "swvl1": (("time", "latitude", "longitude"), np.clip(sm - 0.03 * season, 0.05, 0.5)),
            "swvl2": (("time", "latitude", "longitude"), np.clip(sm, 0.05, 0.5)),
            "swvl3": (("time", "latitude", "longitude"), np.clip(sm + 0.02, 0.05, 0.5)),
            "tp": (("time", "latitude", "longitude"), tp),
            "pev": (("time", "latitude", "longitude"), pev),
        },
        coords={"time": time, "latitude": lat, "longitude": lon},
    )
    slt = xr.DataArray(rng.choice([1, 2, 3], size=(ny, nx), p=[0.5, 0.3, 0.2]).astype(float),
                       coords={"latitude": lat, "longitude": lon}, dims=("latitude", "longitude"))
    return ds, slt

def _gringorten_z(a: np.ndarray) -> np.ndarray:
    valid = ~np.isnan(a)
    n = valid.sum(axis=0)
    order = np.where(valid, a, np.inf).argsort(axis=0, kind="stable")
    ranks = np.empty_like(order)
    pos = np.broadcast_to(np.arange(1, a.shape[0] + 1).reshape((-1,) + (1,) * (a.ndim - 1)), order.shape)
    np.put_along_axis(ranks, order, pos, axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        p = (ranks - 0.44) / (n + 0.12)
    z = np.full(a.shape, np.nan)
    z[valid] = np.vectorize(_ND.inv_cdf)(p[valid])
    return z


def standardize(da: xr.DataArray) -> xr.DataArray:
    out = xr.full_like(da, np.nan, dtype=float)
    months = da["time"].dt.month.values
    for m in range(1, 13):
        idx = np.where(months == m)[0]
        if len(idx):
            out[dict(time=idx)] = _gringorten_z(da.isel(time=idx).values.astype(float))
    return out


def soil_parameters(slt: xr.DataArray, like: xr.Dataset):
    slt = slt.sel(latitude=like["latitude"], longitude=like["longitude"], method="nearest")
    slt = slt.assign_coords(latitude=like["latitude"], longitude=like["longitude"])
    code = slt.round().fillna(0).astype(int)

    def lookup(i):
        table = np.full(8, np.nan)
        for k, v in SOIL_PARAMS.items():
            table[k] = v[i]
        return xr.DataArray(table[code.clip(0, 7).values], coords=code.coords, dims=code.dims)

    return code, lookup(1), lookup(2), lookup(3)  # kod, porowatość, θfc, θwp


def vapour_pressure_kpa(t_c):
    return 0.6108 * np.exp(17.27 * t_c / (t_c + 237.3))


def drought_indicators(ds: xr.Dataset, slt: xr.DataArray) -> xr.Dataset:
    days = xr.DataArray(pd.DatetimeIndex(ds["time"].values).days_in_month,
                        coords={"time": ds["time"]}, dims="time")
    t2m = ds["t2m"] - 273.15
    d2m = ds["d2m"] - 273.15
    stl1 = ds["stl1"] - 273.15
    precip = ds["tp"] * days * 1000.0
    pet = (-ds["pev"]).clip(min=0) * days * 1000.0
    cwb = precip - pet
    vpd = (vapour_pressure_kpa(t2m) - vapour_pressure_kpa(d2m)).clip(min=0)

    theta = sum(ds[k] * h for k, h in LAYER_THICKNESS.items()) / sum(LAYER_THICKNESS.values())

    code, porosity, fc, wp = soil_parameters(slt, ds)
    land = code > 0
    paw = ((theta - wp) / (fc - wp)).clip(0, 1)
    swdi = 10.0 * (theta - fc) / (fc - wp)
    sat = (theta / porosity).clip(0, 1)

    out = xr.Dataset({
        "T2m_C": t2m, "Tgleby_C": stl1, "opad_mm": precip, "PET_mm": pet, "CWB_mm": cwb,
        "VPD_kPa": vpd, "theta": theta, "porowatosc": porosity, "theta_fc": fc, "theta_wp": wp,
        "PAW": paw, "SWDI": swdi, "SAT": sat,
        "SMA": standardize(theta),
        "SPEI3": standardize(cwb.rolling(time=3, min_periods=3).sum()),
        "VPDz": standardize(vpd),
        "STLz": standardize(stl1),
    })
    out = out.where(land)

    w = WEIGHTS
    lin = (w["intercept"] + w["SMA"] * out["SMA"] + w["SPEI3"] * out["SPEI3"].fillna(0)
           + w["VPDz"] * out["VPDz"] + w["STLz"] * out["STLz"] + w["PAW"] * (out["PAW"] - 0.5))
    out["P_susza"] = (1.0 / (1.0 + np.exp(-lin))).where(land)
    out["sezon_wegetacyjny"] = out["time"].dt.month.isin(list(GROWING_SEASON))
    return out


def classify(p: float) -> str:
    if np.isnan(p):
        return "-"
    return next(name for limit, name in CLASSES if p < limit)


def swdi_class(v: float) -> str:
    if np.isnan(v):
        return "-"
    if v > 0:
        return "brak deficytu"
    if v > -2:
        return "lekki"
    if v > -5:
        return "umiarkowany"
    if v > -10:
        return "silny"
    return "ekstremalny"

def summary_table(res: xr.Dataset) -> pd.DataFrame:
    cols = ["T2m_C", "Tgleby_C", "opad_mm", "PET_mm", "theta", "PAW", "SWDI", "SMA", "SPEI3", "VPDz", "P_susza"]
    df = res[cols].mean(["latitude", "longitude"]).to_dataframe()[cols]
    df["klasa"] = df["P_susza"].map(classify)
    df["SWDI_klasa"] = df["SWDI"].map(swdi_class)
    df.index = df.index.strftime("%Y-%m")
    return df


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Prawdopodobieństwo suszy rolniczej (ERA5-Land przez earthkit)")
    ap.add_argument("--area", nargs=4, type=float, default=DEFAULT_AREA, metavar=("N", "W", "S", "E"))
    ap.add_argument("--od", type=int, default=1991, help="pierwszy rok (klimatologia)")
    ap.add_argument("--do", type=int, default=dt.date.today().year, help="ostatni rok")
    ap.add_argument("--punkt", nargs=2, type=float, metavar=("LAT", "LON"), help="wypisz szereg dla punktu")
    ap.add_argument("--miesiace", type=int, default=12, help="ile ostatnich miesięcy pokazać")
    ap.add_argument("--demo", action="store_true", help="dane syntetyczne zamiast pobierania z CDS")
    ap.add_argument("--wyniki", default=str(Path(__file__).with_name("wyniki_susza")), help="katalog wyników")
    args = ap.parse_args()

    if args.do - args.od < 9:
        print("Uwaga: do sensownej klimatologii potrzeba co najmniej ~10 lat (najlepiej 30).")

    print(f"Obszar [N, W, S, E]: {args.area}, lata {args.od}–{args.do}")
    if args.demo:
        print("Tryb DEMO – dane syntetyczne.")
        ds, slt = demo_data(args.area, args.od, args.do)
    else:
        print("Pobieranie danych przez earthkit (pierwsze pobranie może potrwać – CDS kolejkuje zlecenia)…")
        ds = fetch_era5_land(args.area, args.od, args.do)
        slt = fetch_soil_type(args.area)

    res = drought_indicators(ds, slt)

    # typy gleb w obszarze
    codes, counts = np.unique(soil_parameters(slt, ds)[0].values, return_counts=True)
    print("\nGleby w obszarze (typ ERA5: udział, porowatość / θfc / θwp):")
    for c, k in zip(codes, counts):
        if c in SOIL_PARAMS:
            name, por, fc, wp = SOIL_PARAMS[c]
            print(f"  {c} {name:<22} {k / counts.sum():5.0%}   {por:.3f} / {fc:.3f} / {wp:.3f}")

    df = summary_table(res)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    print(f"\nŚrednie dla obszaru – ostatnie {args.miesiace} mies.:")
    print(df.tail(args.miesiace).round(2).to_string())

    last = res.isel(time=-1)
    p = last["P_susza"]
    print(f"\nOstatni miesiąc {pd.Timestamp(last['time'].values):%Y-%m}: "
          f"P(susza) średnio {float(p.mean()):.0%}, max {float(p.max()):.0%}, "
          f"udział obszaru z P ≥ 60%: {float((p >= 0.6).sum() / p.notnull().sum()):.0%}")
    if not bool(last["sezon_wegetacyjny"]):
        print("  (poza sezonem wegetacyjnym IV–IX – susza rolnicza ma wtedy mniejsze znaczenie)")

    if args.punkt:
        lat, lon = args.punkt
        pt = res.sel(latitude=lat, longitude=lon, method="nearest")
        dfp = pt[["T2m_C", "Tgleby_C", "theta", "PAW", "SWDI", "SMA", "SPEI3", "P_susza"]].to_dataframe()
        dfp = dfp.drop(columns=["latitude", "longitude"], errors="ignore")
        dfp["klasa"] = dfp["P_susza"].map(classify)
        dfp.index = dfp.index.strftime("%Y-%m")
        print(f"\nPunkt {float(pt.latitude):.2f}N {float(pt.longitude):.2f}E "
              f"(porowatość {float(pt['porowatosc']):.3f}):")
        print(dfp.tail(args.miesiace).round(2).to_string())

    out_dir = Path(args.wyniki)
    out_dir.mkdir(parents=True, exist_ok=True)
    res.drop_vars("sezon_wegetacyjny").to_netcdf(out_dir / "susza_wskazniki.nc")
    df.to_csv(out_dir / "susza_srednie_obszaru.csv", encoding="utf-8-sig")
    print(f"\nZapisano: {out_dir / 'susza_wskazniki.nc'}\n          {out_dir / 'susza_srednie_obszaru.csv'}")


if __name__ == "__main__":
    main()
