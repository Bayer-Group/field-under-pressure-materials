"""
Scores one field's threats over a range of days, each with an explanation.

score = weather_or_activity (0-1) x stage_weight (0-1) x multipliers (crop history, soil), capped at 1.
Every factor becomes a "driver" in the explanation, with its value, unit, the rule's threshold and
its effect: how much the final score would change without it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from engine import features as F
from engine.catalog import CEREALS, MAIZE, WHEAT, WINTER_CROPS, Rule, crop_pl
from engine import observations as OBS
from engine.phenology import STAGE_CONFIDENCE_GDD, stage_name

MODEL_VERSION = "0.1.0"
# Same cut-offs as the map (frontend/src/risk.ts) and the assistant (assistant/domain.py): < 0.33 low,
# 0.33-0.66 medium, >= 0.66 high. The engine writes `level` into every explanation; readers should use it.
HIGH, MEDIUM = 0.66, 0.33
LEVELS = ((HIGH, "high"), (MEDIUM, "medium"), (0.0, "low"))
NO_IN_SEASON_TREATMENT = {"wheat.take_all", "wheat.snow_mould", "maize.seedling_blight", "maize.crazy_top",
                          "maize.fusarium_stalk_rot", "maize.fusarium_ear_rot",
                          "barley.take_all", "barley.snow_mould", "other_cereals.snow_mould", "rapeseed.clubroot",
                          "sugar_beet.seedling_damping_off", "sugar_beet.rhizoctonia_root_rot", "sugar_beet.beet_cyst_nematode",
                          "potato.rhizoctonia", "potato.cyst_nematode"}
# Spraying conditions: 1-25 °C, no rain, wind <= 4 m/s.
SPRAY = {"max_temperature": 25.0, "min_temperature": 1.0, "total_precipitation": 1.0, "avg_wind_speed": 14.4}


LEVEL_PL = {"high": "Wysokie", "medium": "Średnie", "low": "Niskie"}


def plural(n: float, one: str, few: str, many: str) -> str:
    """Polish plural: 1 dzień, 2 dni, 5 dni; 1 sezon, 2 sezony, 5 sezonów."""
    n = int(round(n))
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def days_pl(n: float) -> str:
    return plural(n, "dzień", "dni", "dni")


def pl_date(d) -> str:
    """2025-06-14 -> 14.06.2025 (texts only; date keys stay ISO)."""
    s = d.isoformat() if hasattr(d, "isoformat") else str(d)
    y, m, dd = s[:10].split("-")
    return f"{dd}.{m}.{y}"


def _pl_num(x: float) -> str:
    """0.66 -> "0,66" (texts for the farmer use a decimal comma)."""
    return f"{x:.2f}".replace(".", ",")


def level_of(score: float) -> str:
    for cut, name in LEVELS:
        if score >= cut:
            return name
    return "low"


@dataclass
class FieldContext:
    crop: int
    crop_source: str                 # "field" (Field.crop) or "satellite" / "farmer" later
    previous_crop: int | None        # dominant class last season
    previous_crop_name: str | None
    maize_years_in_row: int          # consecutive maize seasons including this one
    soil: dict = field(default_factory=dict)  # averaged root-zone values: clay, sand, ph
    last_season: dict = field(default_factory=dict)  # threat code -> {"peak", "date", "threat"} from last season's risks
    history: dict = field(default_factory=dict)  # season -> dominant crop code (crop map), for rotation pests
    season: int | None = None


def stage_weight(bbch: np.ndarray, rule: Rule) -> np.ndarray:
    lo, hi, ramp = rule.stage_min, rule.stage_max, max(rule.stage_ramp, 1)
    w = np.ones_like(bbch, dtype=float)
    w = np.where(bbch < lo, np.clip(1 - (lo - bbch) / ramp, 0, 1), w)
    w = np.where(bbch > hi, np.clip(1 - (bbch - hi) / ramp, 0, 1), w)
    return np.where(bbch < 0, 0.0, w)  # not sown yet


def ramp(x, low, high):
    return np.clip((np.asarray(x, dtype=float) - low) / max(high - low, 1e-9), 0, 1)


def multipliers(rule: Rule, ctx: FieldContext) -> list[dict]:
    out = []
    if rule.after_maize != 1.0 and ctx.previous_crop == MAIZE:
        out.append({"factor": "previous_crop", "label": "Przedplon: kukurydza (resztki pożniwne przenoszą grzyba)",
                    "value": ctx.previous_crop, "unit": "kod uprawy", "display": crop_pl(ctx.previous_crop, ctx.previous_crop_name), "multiplier": rule.after_maize})
    if rule.cereal_after_cereal != 1.0 and ctx.previous_crop in CEREALS:
        out.append({"factor": "previous_crop", "label": f"Zboże po zbożu (przedplon: {crop_pl(ctx.previous_crop, ctx.previous_crop_name)})",
                    "value": ctx.previous_crop, "unit": "kod uprawy", "display": crop_pl(ctx.previous_crop, ctx.previous_crop_name), "multiplier": rule.cereal_after_cereal})
    if rule.maize_monoculture != 1.0 and ctx.maize_years_in_row >= 2:
        out.append({"factor": "maize_monoculture", "label": f"Monokultura kukurydzy ({ctx.maize_years_in_row} {plural(ctx.maize_years_in_row, 'sezon', 'sezony', 'sezonów')} z rzędu)",
                    "value": ctx.maize_years_in_row, "unit": "sezony", "multiplier": rule.maize_monoculture})
    if rule.same_crop != 1.0 and ctx.previous_crop is not None and ctx.previous_crop == rule.crop:
        name = crop_pl(rule.crop, "ta sama uprawa")
        out.append({"factor": "previous_crop", "label": f"Ta sama uprawa co w poprzednim sezonie ({name}): sprawca choroby lub szkodnik zostaje na polu",
                    "value": ctx.previous_crop, "unit": "kod uprawy", "display": crop_pl(ctx.previous_crop, ctx.previous_crop_name), "multiplier": rule.same_crop})
    for code, mult, why in rule.after_crops:
        if ctx.previous_crop == code:
            out.append({"factor": "previous_crop", "label": why, "value": code, "unit": "kod uprawy",
                        "display": crop_pl(ctx.previous_crop, ctx.previous_crop_name), "multiplier": mult})
    ph = ctx.soil.get("ph")
    if ph is not None and ph > 14:  # pH x 10 in raw SoilGrids units
        ph = ph / 10
    if rule.acid_soil != 1.0 and ph is not None and ph < 6.5:
        out.append({"factor": "acid_soil", "label": f"Kwaśna gleba (pH {ph:.1f}) sprzyja zagrożeniu",
                    "value": round(ph, 1), "unit": "pH", "multiplier": rule.acid_soil})
    carry = ctx.last_season.get(rule.code)
    if carry and carry["peak"] >= HIGH:
        out.append({"factor": "last_season", "label": f"Wysoka presja ({carry['threat']}) na tym polu w poprzednim sezonie (szczyt {_pl_num(carry['peak'])} dnia {pl_date(carry['date']) if carry['date'] else '?'}): porażone resztki",
                    "value": round(carry["peak"], 2), "unit": "0-1", "multiplier": 1.2})
    clay = ctx.soil.get("clay")
    if rule.heavy_soil != 1.0 and clay is not None and clay >= 30:
        out.append({"factor": "heavy_soil", "label": f"Ciężka gleba (ił {clay:.0f} %) zatrzymuje wodę",
                    "value": round(clay, 1), "unit": "% iłu", "multiplier": rule.heavy_soil})
    return out


@dataclass
class DayResult:
    day: date
    score: float
    explanation: dict


def score_rule(rule: Rule, ctx: FieldContext, daily: pd.DataFrame, hourly: pd.DataFrame,
               stages: pd.DataFrame, dd10: pd.Series, days: pd.DatetimeIndex, reports=None) -> list[DayResult]:
    """Scores one rule for the given days (all inside one season)."""
    d = daily
    bbch = stages["bbch"].reindex(days).fillna(0).to_numpy()
    sw = stage_weight(bbch, rule)
    estimated = pd.Series(False, index=days)
    extra: dict[str, pd.Series] = {}
    # factor -> the weather/activity part without that factor, for its "effect" (leave one out)
    without_base: dict[str, np.ndarray] = {}

    if rule.kind == "infection_hours":
        hours, est = F.condition_hours(d, hourly, rule.temp_min, rule.temp_max, rule.moisture)
        win = F.trailing_sum(hours, rule.window_days).reindex(days).fillna(0)
        est_any = F.trailing_sum(est.astype(float), rule.window_days).reindex(days).fillna(0) > 0
        estimated = est_any
        b0 = np.asarray(ramp(win, rule.hours_low, rule.hours_high), dtype=float)
        rain_factor = np.ones(len(days))
        active = np.ones(len(days))
        base = b0
        main = {"factor": "condition_hours", "values": win,
                "label": f"Godziny w {rule.temp_min:g}-{rule.temp_max:g} °C z {_moisture_text(rule.moisture)} w ostatnich {rule.window_days} dniach",
                "unit": "h", "threshold": f"od {rule.hours_low:g} h ryzyko rośnie, {rule.hours_high:g} h = pełne ryzyko"}
        if rule.needs_rain_days:
            rain_days = F.trailing_sum((d["precip"].fillna(0) >= 1).astype(float), rule.window_days).reindex(days).fillna(0)
            rain_factor = np.clip(rain_days.to_numpy() / rule.needs_rain_days, 0.0, 1.0)
            extra["rain_days"] = rain_days
        if rule.crop in WINTER_CROPS:  # winter dormancy: leaf diseases do not develop in cold weather
            mean7 = F.trailing_mean(d["avg_temperature"], 7).reindex(days)
            active = np.where(np.isnan(mean7.to_numpy()), 1.0, ramp(mean7.to_numpy(), 3, 8))
            extra["mean_temperature_7d"] = mean7
        base = b0 * rain_factor * active
        if "rain_days" in extra:
            without_base["rain_days"] = b0 * active
        if "mean_temperature_7d" in extra:
            without_base["mean_temperature_7d"] = b0 * rain_factor
        if rule.code in ("maize.fusarium_ear_rot", "maize.fusarium_stalk_rot"):
            balance = F.trailing_sum(d["precip"].fillna(0) - d["eto"].fillna(0), 30).reindex(days).fillna(0)
            drought = np.asarray(ramp(-balance, 60, 150), dtype=float)  # water deficit 60-150 mm over 30 days
            without_base = {k: np.maximum(v, 0.8 * drought) for k, v in without_base.items()}
            without_base["water_balance_30d"] = base
            base = np.maximum(base, 0.8 * drought)
            extra["water_balance_30d"] = balance
    elif rule.kind == "soil_days":
        lo, hi = rule.soil_temp
        st = d["avg_soil_temperature_level_1"]
        in_t = (st < hi) if lo is None else st.between(lo, hi)
        cond = (in_t & (d["avg_soil_moisture_level_1"] >= rule.soil_wet)).astype(float)
        win = F.trailing_sum(cond, rule.window_days).reindex(days).fillna(0)
        base = ramp(win, rule.hours_low, rule.hours_high)
        t_txt = f"zimną (< {hi:g} °C)" if lo is None else f"ciepłą ({lo:g}-{hi:g} °C)"
        main = {"factor": "cold_wet_soil_days" if lo is None else "warm_wet_soil_days", "values": win, "unit": "dni",
                "label": f"Dni z {t_txt} i mokrą (≥ {rule.soil_wet:.2f} m³/m³) wierzchnią warstwą gleby w ostatnich {rule.window_days} dniach",
                "threshold": _days_threshold(rule)}
    elif rule.kind == "snow_days":
        cond = (d["avg_temperature"].between(rule.temp_min - 2, rule.temp_max)
                & ((d["avg_snow_depth"].fillna(0) >= 5) | (d["avg_relative_humidity"] >= 90))
                & (d["min_soil_temperature_level_1"] > -0.5)).astype(float)
        win = F.trailing_sum(cond, rule.window_days).reindex(days).fillna(0)
        base = ramp(win, rule.hours_low, rule.hours_high)
        main = {"factor": "snow_mould_days", "values": win, "unit": "dni",
                "label": f"Dni z temperaturą ok. 0-5 °C, mokro lub pod śniegiem, gleba niezamarznięta, w ostatnich {rule.window_days} dniach",
                "threshold": _days_threshold(rule)}
    elif rule.kind == "flood":
        cond = ((d["avg_soil_moisture_level_1"] >= 0.40) | (d["precip"].fillna(0) >= 30)).astype(float)
        win = F.trailing_sum(cond, rule.window_days).reindex(days).fillna(0)
        base = ramp(win, rule.hours_low, rule.hours_high)
        main = {"factor": "waterlogged_days", "values": win, "unit": "dni",
                "label": f"Dni z glebą nasyconą wodą lub opadem ≥ 30 mm w ostatnich {rule.window_days} dniach",
                "threshold": _days_threshold(rule)}
    elif rule.kind == "vector_days":
        emerged = (stages["bbch"].reindex(d.index).fillna(-1) >= 10).astype(float)
        flight = ((d["max_temperature"] >= rule.flight_c).astype(float) * emerged)
        win = F.trailing_sum(flight, rule.window_days).reindex(days).fillna(0)
        base = ramp(win, rule.hours_low, rule.hours_high)
        aphids = "aphid" in rule.name_en.lower() or rule.category == "viral"
        insect = "mszyc" if aphids else "szkodnika"
        main = {"factor": "aphid_flight_days" if aphids else "flight_days", "values": win, "unit": "dni",
                "label": f"Dni wystarczająco ciepłe na loty {insect} (maks. ≥ {rule.flight_c:g} °C) od wschodów, w ostatnich {rule.window_days} dniach",
                "threshold": _days_threshold(rule)}
    elif rule.kind == "pest_activity":
        mean7 = F.trailing_mean(d["avg_temperature"], 7).reindex(days)
        if rule.code == "maize.frit_fly":
            base = ramp(-mean7.to_numpy(), -18, -12)  # cooler than 15 °C -> active
            main = {"factor": "mean_temperature_7d", "values": mean7, "unit": "°C",
                    "label": "Średnia temperatura z ostatnich 7 dni (chłodna wiosna sprzyja ploniarce)", "threshold": "poniżej 15 °C sprzyja"}
        else:
            x = dd10.reindex(days).fillna(0).to_numpy()
            p0, p1 = rule.dd10_peak
            act = np.minimum(ramp(x, rule.dd10_start, p0), 1 - ramp(x, p1, rule.dd10_end))
            pressure = 0.6
            pressure_why = f"typowa w regionie dla tej uprawy ({crop_pl(rule.crop)}) (założenie)"
            if rule.rotation_hosts:
                seasons = [ctx.season - k for k in range(1, rule.rotation_years + 1)] if ctx.season else []
                hosts = [(s, ctx.history.get(s)) for s in seasons if ctx.history.get(s) in rule.rotation_hosts]
                pressure = 1.0 if hosts else 0.1
                pressure_why = ("roślina żywicielska na tym polu w ostatnich {} sezonach ({}): populacja utrzymuje się w glebie".format(
                    rule.rotation_years, ", ".join(f"{crop_pl(c)} {s}" for s, c in hosts)) if hosts
                    else f"brak rośliny żywicielskiej na tym polu w ostatnich {rule.rotation_years} sezonach")
            if rule.code == "maize.western_corn_rootworm":
                pressure = 1.0 if ctx.maize_years_in_row >= 2 else 0.05
                pressure_why = (f"kukurydza na tym polu {ctx.maize_years_in_row} {plural(ctx.maize_years_in_row, 'sezon', 'sezony', 'sezonów')} z rzędu: jaja zimują w glebie"
                                if ctx.maize_years_in_row >= 2 else "pierwszy sezon kukurydzy na tym polu: w glebie nie ma jaj, z których wylęgłyby się larwy")
            act0 = act
            warm_range = (14, 20) if rule.code == "maize.aphids" else rule.warm_ramp
            if warm_range:
                act = act * np.where(np.isnan(mean7.to_numpy()), 1.0, 0.5 + 0.5 * ramp(mean7.to_numpy(), *warm_range))
                extra["mean_temperature_7d"] = mean7
                without_base["mean_temperature_7d"] = act0 * pressure
            base = act * pressure
            extra["local_pressure"] = pd.Series(pressure, index=days)
            without_base["local_pressure"] = act  # without the local pressure assumption: full activity
            extra["_pressure_reason"] = f"presja lokalna {pressure:.0%}: {pressure_why}"
            main = {"factor": "pest_activity", "values": pd.Series(np.round(act * 100), index=days), "unit": "% szczytu aktywności",
                    "label": "Okno aktywności szkodnika wg sumy temperatur (próg 10 °C, od 1 stycznia)",
                    "threshold": f"zaczyna się przy {rule.dd10_start:g}, szczyt {p0:g}-{p1:g}, koniec przy {rule.dd10_end:g} °C·dni"}
            extra["degree_days_10"] = dd10.reindex(days)
    else:
        raise ValueError(rule.kind)

    mults = multipliers(rule, ctx)
    m_total = float(np.prod([m["multiplier"] for m in mults])) if mults else 1.0
    base = np.asarray(base, dtype=float)
    final = np.clip(base * sw * m_total, 0, 1)
    effs = OBS.effects(rule, reports or [], days)
    loo = []
    if effs:
        rules_only = final
        final = OBS.combine(rules_only, effs)
        loo = [OBS.combine(rules_only, effs, skip=j) for j in range(len(effs))]

    def scored(x) -> np.ndarray:  # a counterfactual weather part -> its final score (with the farmer's reports)
        x = np.clip(np.asarray(x, dtype=float), 0, 1)
        return OBS.combine(x, effs) if effs else x

    # "effect" of each factor = final score - the final score without it (both with the farmer's reports)
    alt = {"growth_stage": scored(base * m_total),
           **{k: scored(v * sw * m_total) for k, v in without_base.items()},
           **{f"mult{j}": scored(base * sw * m_total / m["multiplier"]) for j, m in enumerate(mults) if m["multiplier"]}}

    results = []
    for i, day in enumerate(days):
        active = [(e, float(final[i] - loo[j][i])) for j, e in enumerate(effs)
                  if e.mult[i] != 1 or e.floor[i] > 0 or e.after[i] != 1]
        results.append(DayResult(day.date(), round(float(final[i]), 3), _explain(
            rule, ctx, day, float(final[i]), float(base[i]), float(sw[i]), float(bbch[i]), m_total, mults, main, i,
            stages, extra, bool(estimated.iloc[i]) if len(estimated) else False, active,
            {k: float(v[i]) for k, v in alt.items()})))
    return results


def _moisture_text(kind: str) -> str:
    return {"wet": "mokrymi liśćmi (wilgotność względna powietrza ≥ 95 % lub deszcz)",
            "humid": "wilgotnym powietrzem (wilgotność względna ≥ 85 % lub deszcz)",
            "mild": "wilgotnym, ale bezdeszczowym powietrzem (wilgotność względna 50-95 %)",
            "rh90": "wilgotnością względną powietrza ≥ 90 % lub deszczem"}[kind]


def _days_threshold(rule: Rule) -> str:
    return f"od {rule.hours_low:g} {days_pl(rule.hours_low)} ryzyko rośnie, {rule.hours_high:g} {days_pl(rule.hours_high)} = pełne ryzyko"


def _explain(rule, ctx, day, final, base, sw, bbch, m_total, mults, main, i, stages, extra, estimated, active=(),
             alt=None) -> dict:
    """alt: factor -> the final score without that factor (growth_stage, mult<j>, extra keys)."""
    alt = alt or {}
    level = level_of(round(final, 3))  # the same rounding as the stored score, so level and score never disagree
    value = main["values"].iloc[i] if hasattr(main["values"], "iloc") else main["values"][i]
    value = None if pd.isna(value) else round(float(value), 1)
    drivers = [{
        "factor": main["factor"], "label": main["label"], "value": value, "unit": main["unit"],
        "threshold": main["threshold"], "effect": round(final, 3),
        "note": "oszacowane z danych dobowych (brak danych godzinowych)" if estimated else None,
    }]
    st = stages.loc[day] if day in stages.index else None
    drivers.append({
        "factor": "growth_stage", "label": f"Faza rozwoju BBCH {bbch:.0f} ({stage_name(bbch, rule.crop)}); faza podatna BBCH {rule.stage_min}-{rule.stage_max}",
        "value": int(round(bbch)), "unit": "BBCH", "threshold": f"BBCH {rule.stage_min}-{rule.stage_max}",
        "effect": round(final - alt.get("growth_stage", min(1.0, base * m_total)), 3),
    })
    for j, m in enumerate(mults):
        without = alt.get(f"mult{j}", min(1.0, base * sw * m_total / m["multiplier"]))
        drivers.append({**{k: v for k, v in m.items()}, "effect": round(final - without, 3)})
    for e, eff in active:
        r = e.report
        drivers.append({"factor": "farmer_report", "kind": r.kind, "label": r.label(), "observed_on": r.observed_on.isoformat(),
                        "threat_code": r.threat_code, "text": r.text or None, "report_id": r.id, "effect": round(eff, 3)})
    pressure_reason = extra.get("_pressure_reason")
    for k, s in extra.items():
        if k.startswith("_"):
            continue
        v = s.iloc[i] if hasattr(s, "iloc") else s
        if pd.isna(v):
            continue
        drivers.append({"factor": k, "label": _EXTRA_LABELS.get(k, k), "value": round(float(v), 1),
                        "unit": _EXTRA_UNITS.get(k, ""),
                        "effect": round(final - alt[k], 3) if k in alt else None})  # None: context only

    def lc(text: str) -> str:  # lower-case the first letter only (keeps °C, RH, BBCH)
        return text[:1].lower() + text[1:]

    reasons = []
    if bbch < 0:
        reasons.append("uprawa nie jest jeszcze zasiana")
    elif sw == 0:
        reasons.append(f"uprawa poza fazą podatną (BBCH {rule.stage_min}-{rule.stage_max}; teraz BBCH {bbch:.0f}, {stage_name(bbch, rule.crop)})")
    else:
        reasons.append(f"{lc(main['label'])}: {value:g} {main['unit']}" if value is not None else lc(main["label"]))
        stage_txt = f"{stage_name(bbch, rule.crop)}, BBCH {bbch:.0f}"
        reasons.append(f"faza: {stage_txt}" + ("" if sw >= 1 else f" (tylko częściowo w fazie podatnej BBCH {rule.stage_min}-{rule.stage_max})"))
        reasons += [lc(m["label"]) for m in mults]
        if pressure_reason:
            reasons.append(pressure_reason)
    reasons += [lc(e.report.label()) for e, _ in active]
    summary = f"{LEVEL_PL[level]} ryzyko – {rule.name_pl}: " + "; ".join(reasons) + "."

    st_conf = float(st["confidence"]) if st is not None and "confidence" in st else STAGE_CONFIDENCE_GDD
    st_method = str(st["method"]) if st is not None and "method" in st else "suma temperatur, typowa data siewu"
    confidence = st_conf * (0.7 if estimated else 1.0)
    if any(e.report.kind == "symptoms" for e, _ in active):
        confidence = 1.0  # seen in the field
    treated = [e.report for e, _ in active if e.after[i] < 1]
    return {
        "version": 1,
        "summary": summary,
        "level": level,
        "score": round(final, 3),
        "threat": {"code": rule.code, "name_pl": rule.name_pl, "name_en": rule.name_en, "category": rule.category},
        "as_of": day.date().isoformat(),
        "crop": {"code": ctx.crop, "source": ctx.crop_source},
        "growth_stage": {"bbch": int(round(bbch)), "name": stage_name(bbch, rule.crop), "method": st_method,
                         "sowing_assumed": str(st["sowing"]) if st is not None else None, "confidence": st_conf},
        "drivers": drivers,
        "action": _action(rule, level, sw, treated, bbch),
        "severity": rule.severity,
        "expected_loss": round(final * rule.severity, 4),
        "confidence": round(confidence, 2),
        "notes": list(rule.notes),
        "assumptions": rule.assumptions,
        "model": "rules", "model_version": MODEL_VERSION,
    }


_EXTRA_LABELS = {"rain_days": "Dni z opadem ≥ 1 mm w oknie (krople deszczu roznoszą zarodniki)",
                 "mean_temperature_7d": "Średnia temperatura z ostatnich 7 dni (chłód hamuje rozwój grzybów i aktywność szkodników)",
                 "water_balance_30d": "Bilans wodny (opad minus ewapotranspiracja) z ostatnich 30 dni; mocno ujemny = stres suszy",
                 "local_pressure": "Lokalna presja szkodnika z historii pola (0-1)",
                 "degree_days_10": "Suma temperatur (próg 10 °C) od 1 stycznia"}
_EXTRA_UNITS = {"rain_days": "dni", "mean_temperature_7d": "°C", "water_balance_30d": "mm", "local_pressure": "0-1", "degree_days_10": "°C·dni"}


def stage_threshold(rule: Rule, bbch: float) -> str | None:
    for lo, hi, text in rule.stage_thresholds:
        if lo <= bbch <= hi:
            return text + " (próg dla tej fazy)"
    return rule.action_threshold or None


def _action(rule: Rule, level: str, sw: float, treated=(), bbch: float = 0) -> dict:
    out = _action_base(rule, level, sw, treated)
    out["threshold"] = stage_threshold(rule, bbch)
    return out


def _action_base(rule: Rule, level: str, sw: float, treated=()) -> dict:
    if treated:
        t = max(treated, key=lambda r: r.observed_on)
        return {"type": "wait", "text": f"Pole chronione zabiegiem z {pl_date(t.observed_on)}; obejrzyj je ponownie, gdy ochrona się skończy (ok. 14-21 dni).",
                "threshold": rule.action_threshold or None, "spray_window": None}
    if sw == 0 or level == "low":
        return {"type": "wait", "text": "Na razie nic nie trzeba robić.", "threshold": rule.action_threshold or None, "spray_window": None}
    if level == "medium":
        return {"type": "monitor", "text": "Obejrzyj pole w najbliższych dniach i porównaj stan z progiem.",
                "threshold": rule.action_threshold or None, "spray_window": None}
    if rule.code in NO_IN_SEASON_TREATMENT:
        return {"type": "monitor", "text": "Wysokie ryzyko, ale w sezonie nie ma zabiegu: obejrzyj pole, zapisz obserwację i zaplanuj profilaktykę (płodozmian, resztki pożniwne, zaprawianie).",
                "threshold": rule.action_threshold or None, "spray_window": None}
    return {"type": "treat", "text": "Wysokie ryzyko: obejrzyj pole teraz; po przekroczeniu progu zabieg jest uzasadniony.",
            "threshold": rule.action_threshold or None, "spray_window": None}


def spray_window(forecast: pd.DataFrame) -> dict | None:
    """
    First forecast day suitable for spraying, from the daily forecast:
    1-25 °C, the following night >= 1 °C, RH 50-95 %, no rain, wind <= 4 m/s.
    "optimal" when 12-20 °C, RH 75-95 % and wind 0.5-1.5 m/s as well. Daily values approximate the hours.
    """
    if forecast is None or forecast.empty:
        return None
    fc = forecast.sort_index()
    rows = list(fc.iterrows())
    for k, (d, row) in enumerate(rows):
        def val(name):
            v = row.get(name)
            return None if v is None or pd.isna(v) else float(v)
        tmax, tmin, rh, wind, rain = val("max_temperature"), val("min_temperature"), val("avg_relative_humidity"), val("avg_wind_speed"), val("total_precipitation")
        night = None
        if k + 1 < len(rows):
            nv = rows[k + 1][1].get("min_temperature")
            night = None if nv is None or pd.isna(nv) else float(nv)
        ok = (tmax is not None and tmax <= 25 and tmin is not None and tmin >= 1
              and (night is None or night >= 1) and (rh is None or 50 <= rh <= 95)
              and (rain is None or rain < 1.0) and wind is not None and wind <= 14.4)
        if not ok:
            continue
        mean_t = (tmax + tmin) / 2
        optimal = 12 <= mean_t <= 20 and (rh is None or 75 <= rh <= 95) and 1.8 <= wind <= 5.4
        notes = []
        if rain is None:
            notes.append("Prognoza nie ma opadu: przed zabiegiem sprawdź deszcz (w ciągu 3-6 h po zabiegu < 2 mm).")
        if rh is None:
            notes.append("Prognoza nie ma wilgotności powietrza.")
        return {"date": pd.Timestamp(d).date().isoformat(), "quality": "optimal" if optimal else "acceptable",
                "conditions": {"max_temperature_c": round(tmax, 1), "min_temperature_c": round(tmin, 1),
                               "next_night_min_c": None if night is None else round(night, 1),
                               "avg_relative_humidity": None if rh is None else round(rh), "precipitation_mm": rain,
                               "avg_wind_kmh": round(wind, 1)},
                "rule": "1-25 °C, następna noc >= 1 °C, wilgotność 50-95 %, bez deszczu, wiatr <= 14,4 km/h (4 m/s); optymalnie 12-20 °C, wilgotność 75-95 %, wiatr 1,8-5,4 km/h",
                "note": " ".join(notes) or None}
    return None
