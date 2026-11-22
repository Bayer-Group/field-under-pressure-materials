"""
The threat catalogue: every rule the engine applies, with its numbers.

Each entry is keyed by the Threat.code the platform stores (refer to threats by code, never by id).
Numbers listed in `assumptions` are the team's own calibration; the rest follow the integrated pest
management guides. The rules are stored here; no document is read at run time.

Kinds of rules (see engine/scoring.py):
- "infection_hours": hours with temperature in range and wet / humid air, summed over a trailing
  window, during a susceptible growth stage.
- "soil_days", "snow_days", "flood": day counts of a soil / snow / waterlogging condition.
- "pest_activity": activity window (degree days or calendar) x local pressure (crop history).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

WHEAT = 1110
BARLEY = 1120
MAIZE = 1130
OTHER_CEREALS = 1150   # triticale, rye, oats (one class in the crop map)
POTATO = 1310
SUGAR_BEET = 1320
RAPESEED = 1430

CROP_NAMES = {WHEAT: "Wheat", BARLEY: "Barley", MAIZE: "Maize", OTHER_CEREALS: "Other cereals", POTATO: "Potatoes",
              SUGAR_BEET: "Sugar beet", RAPESEED: "Rapeseed"}  # CropClass names (the crop map's legend)

# Polish names for texts shown to the farmer (explanations are Polish: docs/database.md, explanation v1).
CROP_NAMES_PL = {WHEAT: "pszenica", BARLEY: "jęczmień", MAIZE: "kukurydza", OTHER_CEREALS: "inne zboża", POTATO: "ziemniak",
                 SUGAR_BEET: "burak cukrowy", RAPESEED: "rzepak", 1140: "ryż", 1210: "warzywa", 1220: "rośliny strączkowe",
                 1410: "słonecznik", 1420: "soja", 1440: "len / konopie", 2100: "winorośl", 2310: "sad", 3100: "inna uprawa polowa",
                 0: "brak uprawy"}


def crop_pl(code, fallback=None) -> str:
    """Polish crop name for a CropClass code (falls back to the given name, then the code)."""
    return CROP_NAMES_PL.get(code, fallback if fallback else str(code))



@dataclass(frozen=True)
class Rule:
    code: str
    crop: int
    name_pl: str
    name_en: str
    category: str  # fungal / bacterial / viral / pest (Threat.Category)
    kind: str
    # growth stage window (BBCH): full weight inside [stage_min, stage_max], ramps to 0 over `stage_ramp`
    stage_min: int = 0
    stage_max: int = 99
    stage_ramp: int = 5
    # infection_hours
    temp_min: float | None = None
    temp_max: float | None = None
    moisture: str = "wet"  # wet: RH >= 95 % or rain (engine.features.WET_RH); humid: RH >= 85 % or rain; rh90: RH >= 90 % or rain; mild: 50 <= RH < 95 % and no rain
    window_days: int = 7
    hours_low: float = 5.0   # hours in the window at which the weather starts to count
    hours_high: float = 20.0  # hours in the window at which the weather alone gives score 1
    needs_rain_days: int = 0  # rain-splash diseases: days with >= 1 mm in the window
    # pest_activity: degree days base 10 °C since 1 January
    dd10_start: float | None = None
    dd10_peak: tuple[float, float] | None = None
    dd10_end: float | None = None
    # multipliers from crop history / soil (applied inside the rule, explained as drivers)
    after_maize: float = 1.0          # previous crop was maize
    cereal_after_cereal: float = 1.0  # previous crop was a cereal (wheat, barley, other cereals)
    maize_monoculture: float = 1.0    # maize also last year
    heavy_soil: float = 1.0           # clay >= 30 %
    same_crop: float = 1.0            # previous crop was the same crop (any crop)
    after_crops: tuple = ()           # ((crop code, multiplier, why), ...) previous crop raises the risk
    acid_soil: float = 1.0            # soil pH < 6.5
    rotation_hosts: tuple = ()        # pest_activity: host crops whose presence in the last `rotation_years` sets the pressure
    rotation_years: int = 3
    soil_temp: tuple = (None, 12.0)   # soil_days: topsoil temperature range (°C)
    soil_wet: float = 0.30            # soil_days: topsoil moisture at least (m³/m³)
    flight_c: float = 12.0            # vector_days: daily max temperature that lets the insect fly (°C)
    severity: float = 0.1             # potential yield loss if the threat materialises, 0-1 (assumption)
    action_threshold: str = ""        # monitoring / economic threshold
    stage_thresholds: tuple = ()      # ((bbch_from, bbch_to, text), ...) threshold for the current stage
    warm_ramp: tuple | None = None    # pests: activity x (0.5 + 0.5 x ramp(7-day mean temperature, lo, hi))
    notes: tuple[str, ...] = ()
    assumptions: dict = field(default_factory=dict)


RULES: dict[str, Rule] = {}


def _add(rule: Rule) -> None:
    RULES[rule.code] = rule


# --- Wheat ---------------------------------------------------------------------------------------

_add(Rule(
    code="wheat.fusarium_head_blight", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="fuzarioza kłosów", name_en="Fusarium head blight",
    stage_min=61, stage_max=69, stage_ramp=6, temp_min=15, temp_max=25, moisture="wet",
    window_days=5, hours_low=4, hours_high=16, needs_rain_days=1, after_maize=1.5, severity=0.15,
    action_threshold="Infekcja następuje w czasie kwitnienia (BBCH 61-69); zabieg działa tylko zapobiegawczo, w okolicy kwitnienia.",
    notes=("Resztki kukurydzy (przedplon kukurydza) i uprawa uproszczona zwiększają ryzyko.",
           "Gatunki się różnią: F. graminearum 16-18 °C, F. culmorum 20-22 °C, F. avenaceum 5-10 °C przy rosie, mgle lub 2-5 mm deszczu.",
           "Każdy 1 % porażonych kłosów może dodać ok. 0,3 mg/kg DON (mykotoksyny) w ziarnie.",
           "Pola z fuzariozą kłosów w poprzednich sezonach i monokultury zbożowe są bardziej narażone."),
    assumptions={"hours_low": 4, "hours_high": 16, "window_days": 5, "after_maize": 1.5},
))
_add(Rule(
    code="wheat.septoria_leaf_blotch", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="septorioza paskowana liści pszenicy", name_en="Septoria leaf blotch",
    stage_min=30, stage_max=59, temp_min=4, temp_max=18, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, needs_rain_days=2, cereal_after_cereal=1.2, severity=0.15,
    stage_thresholds=((21, 29, "Krzewienie: 30-50 % liści z pierwszymi objawami lub 1 % liści z owocnikami"), (30, 39, "Strzelanie w źdźbło: 10-20 % powierzchni liścia podflagowego lub 1 % liści z owocnikami"), (51, 59, "Kłoszenie: 5-10 % powierzchni liścia flagowego lub 1 % liści z owocnikami")),
    action_threshold="Krzewienie: 30-50 % liści z pierwszymi objawami lub 1 % liści z owocnikami.",
    notes=("Rozprzestrzenia się z kroplami deszczu: potrzebne są dni z opadem w oknie.",),
    assumptions={"hours_low": 15, "hours_high": 50, "window_days": 10, "needs_rain_days": 2},
))
_add(Rule(
    code="wheat.brown_rust", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="rdza brunatna pszenicy", name_en="Brown (leaf) rust",
    stage_min=30, stage_max=75, temp_min=15, temp_max=18, moisture="wet",
    window_days=7, hours_low=3, hours_high=12, severity=0.10,
    stage_thresholds=((21, 29, "Krzewienie: 10-15 % liści z pierwszymi objawami"), (30, 39, "Strzelanie w źdźbło: 10 % źdźbeł z pierwszymi objawami"), (51, 59, "Kłoszenie: pierwsze objawy na liściu flagowym lub podflagowym")),
    action_threshold="Krzewienie: 10-15 % liści z pierwszymi objawami; strzelanie w źdźbło: 10 % źdźbeł.",
    notes=("Warunek: okresowy dobowy wzrost wilgotności powietrza (rosa); liczone jako mokre godziny w 15-18 °C.",),
    assumptions={"hours_low": 3, "hours_high": 12},
))
_add(Rule(
    code="wheat.powdery_mildew", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="mączniak prawdziwy zbóż i traw", name_en="Powdery mildew",
    stage_min=21, stage_max=59, temp_min=5, temp_max=30, moisture="mild",
    window_days=7, hours_low=90, hours_high=150, severity=0.08,
    stage_thresholds=((21, 29, "Krzewienie: 50-70 % roślin z pierwszymi objawami"), (30, 39, "Strzelanie w źdźbło: 10 % roślin z pierwszymi objawami"), (51, 59, "Kłoszenie: pierwsze objawy na liściu flagowym, podflagowym lub na kłosie")),
    action_threshold="Krzewienie: 50-70 % roślin z pierwszymi objawami.",
    notes=("Ciepła, słoneczna pogoda z wilgotnym, ale bezdeszczowym powietrzem sprzyja tworzeniu zarodników.",
           "Nadmiar azotu i gęsty łan zwiększają ryzyko (tego nie ma w naszych danych)."),
    assumptions={"hours_low": 90, "hours_high": 150},
))
_add(Rule(
    code="wheat.yellow_rust", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="rdza żółta", name_en="Yellow (stripe) rust",
    stage_min=29, stage_max=69, temp_min=10, temp_max=15, moisture="wet",
    window_days=7, hours_low=5, hours_high=20, severity=0.15,
    stage_thresholds=((21, 29, "Krzewienie: 30 % roślin z pierwszymi objawami"), (30, 39, "Strzelanie w źdźbło: 10 % powierzchni liścia podflagowego"), (51, 59, "Kłoszenie: pierwsze objawy na liściu flagowym lub podflagowym")),
    action_threshold="Krzewienie: 30 % roślin z pierwszymi objawami; strzelanie w źdźbło: 10 % powierzchni drugiego liścia.",
    notes=("Nowe patotypy (Warrior, Kranich) rozwijają się też w 10-28 °C, przy suchej i ciepłej pogodzie.",),
    assumptions={"hours_low": 5, "hours_high": 20},
))
_add(Rule(
    code="wheat.tan_spot", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="brunatna plamistość liści", name_en="Tan spot (DTR)",
    stage_min=37, stage_max=75, temp_min=18, temp_max=28, moisture="wet",
    window_days=7, hours_low=5, hours_high=20, cereal_after_cereal=1.3, severity=0.10,
    stage_thresholds=((21, 29, "Krzewienie: 10-15 % roślin z pierwszymi objawami"), (30, 39, "Strzelanie w źdźbło: 5 % liści z pierwszymi objawami"), (51, 59, "Kłoszenie: 5 % liści z pierwszymi objawami")),
    action_threshold="Krzewienie: 10-15 % roślin z pierwszymi objawami; strzelanie w źdźbło: 5 % liści.",
    notes=("Do infekcji potrzebuje mokrych liści; przeżywa na resztkach pszenicy (pszenica po pszenicy zwiększa ryzyko).",),
    assumptions={"hours_low": 5, "hours_high": 20, "cereal_after_cereal": 1.3},
))
_add(Rule(
    code="wheat.take_all", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="zgorzel podstawy źdźbła", name_en="Take-all",
    stage_min=21, stage_max=39, temp_min=12, temp_max=20, moisture="humid",
    window_days=10, hours_low=40, hours_high=120, cereal_after_cereal=1.5, severity=0.15,
    action_threshold="W sezonie nie ma zabiegu fungicydowego; zapobiega się płodozmianem i zaprawianiem nasion.",
    notes=("Głównym czynnikiem jest zboże po zbożu: 3-4 lata przerwy w uprawie zbóż silnie je ogranicza.",),
    assumptions={"hours_low": 40, "hours_high": 120, "cereal_after_cereal": 1.5},
))
_add(Rule(
    code="wheat.snow_mould", crop=WHEAT, category="fungal", kind="snow_days",
    name_pl="pleśń śniegowa", name_en="Snow mould",
    stage_min=10, stage_max=30, temp_min=0, temp_max=5, window_days=21, hours_low=3, hours_high=14,
    severity=0.10,
    action_threshold="Zaprawianie nasion i właściwa agrotechnika jesienią; pod śniegiem nie ma zabiegu.",
    notes=("Liczone jako dni z temperaturą 0-5 °C, pokrywą śnieżną i niezamarzniętą glebą.",),
    assumptions={"days_low": 3, "days_high": 14, "snow_depth_mm_we": 5},
))

# --- Maize ---------------------------------------------------------------------------------------
_add(Rule(
    code="maize.seedling_blight", crop=MAIZE, category="fungal", kind="soil_days",
    name_pl="zgorzel siewek", name_en="Seedling blight",
    stage_min=0, stage_max=14, stage_ramp=3, window_days=10, hours_low=2, hours_high=7, severity=0.08,
    action_threshold="Zapobiega się zaprawianiem nasion; obserwacje są najważniejsze na początku sezonu.",
    notes=("Liczone jako dni z zimną (< 12 °C) i mokrą (>= 0,30 m³/m³) wierzchnią warstwą gleby (0-7 cm).",),
    assumptions={"soil_temp_max_c": 12, "soil_moisture_min": 0.30, "days_low": 2, "days_high": 7},
))
_add(Rule(
    code="maize.fusarium_ear_rot", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="fuzarioza kolb", name_en="Fusarium ear rot",
    stage_min=63, stage_max=89, stage_ramp=8, temp_min=15, temp_max=30, moisture="humid",
    window_days=14, hours_low=60, hours_high=180, maize_monoculture=1.3, severity=0.12,
    action_threshold="Kluczowe są terminowy zbiór i rozdrobnienie resztek (mykotoksyny).",
    notes=("Uszkodzenia przez omacnicę i stres suszy zwiększają ryzyko; mokra jesień i późny zbiór zwiększają mykotoksyny.",),
    assumptions={"hours_low": 60, "hours_high": 180, "maize_monoculture": 1.3},
))
_add(Rule(
    code="maize.fusarium_stalk_rot", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="fuzarioza łodyg", name_en="Fusarium stalk rot",
    stage_min=51, stage_max=89, stage_ramp=10, temp_min=18, temp_max=30, moisture="humid",
    window_days=14, hours_low=60, hours_high=180, maize_monoculture=1.3, severity=0.10,
    action_threshold="Płodozmian, zagospodarowanie resztek, zrównoważone nawożenie potasem.",
    notes=("Stres suszy osłabia rośliny i zwiększa ich podatność.",),
    assumptions={"hours_low": 60, "hours_high": 180},
))
_add(Rule(
    code="maize.crazy_top", crop=MAIZE, category="fungal", kind="flood",
    name_pl="choroba szalonych wiech", name_en="Crazy top",
    stage_min=0, stage_max=16, stage_ramp=3, window_days=14, hours_low=1, hours_high=3, heavy_soil=1.3,
    severity=0.05,
    action_threshold="Usuń i zniszcz porażone rośliny, zanim uwolnią zarodniki.",
    notes=("Potrzebuje zalania pola przez 24-48 h: liczone jako dni z nasyconą wodą glebą lub opadem >= 30 mm.",),
    assumptions={"saturated_moisture": 0.40, "heavy_rain_mm": 30, "days_low": 1, "days_high": 3},
))
_add(Rule(
    code="maize.european_corn_borer", crop=MAIZE, category="pest", kind="pest_activity",
    name_pl="omacnica prosowianka", name_en="European corn borer",
    stage_min=30, stage_max=79, stage_ramp=10, dd10_start=150, dd10_peak=(420, 650), dd10_end=900,
    maize_monoculture=1.4, severity=0.10,
    action_threshold="Wiechowanie (BBCH 51-59): 6-8 złóż jaj na 100 roślin lub 15 % roślin uszkodzonych w poprzednim roku.",
    notes=("Motyle latają od początku lub połowy czerwca, szczyt w 1.-2. dekadzie lipca; jaja od drugiej połowy czerwca, najwięcej w połowie lipca; gąsienice wylęgają się od połowy czerwca.",
           "Gorące, suche lato skraca lot (koniec lipca lub początek sierpnia), chłodne i deszczowe wydłuża go do końca sierpnia.",
           "Liczy się też udział kukurydzy w okolicy; znamy tylko historię tego pola."),
    assumptions={"dd10_start": 150, "dd10_peak": [420, 650], "dd10_end": 900, "base_pressure": 0.6, "maize_monoculture": 1.4},
))
_add(Rule(
    code="maize.western_corn_rootworm", crop=MAIZE, category="pest", kind="pest_activity",
    name_pl="stonka kukurydziana", name_en="Western corn rootworm",
    stage_min=14, stage_max=79, stage_ramp=5, dd10_start=150, dd10_peak=(250, 700), dd10_end=1000,
    severity=0.15,
    action_threshold="Pola w monokulturze: co tydzień sprawdzaj larwy od 9 liści do wiechowania (BBCH 19-59).",
    notes=("Realne zagrożenie dopiero co najmniej w drugim roku kukurydzy na tym samym polu (jaja zimują w glebie).",),
    assumptions={"dd10_start": 150, "dd10_peak": [250, 700], "dd10_end": 1000, "pressure_first_year_maize": 0.05},
))
_add(Rule(
    code="maize.aphids", crop=MAIZE, category="pest", kind="pest_activity",
    name_pl="mszyce", name_en="Aphids",
    stage_min=10, stage_max=85, stage_ramp=5, dd10_start=250, dd10_peak=(380, 900), dd10_end=1200,
    severity=0.03,
    action_threshold="Od wiechowania (BBCH 51): 300 mszyc na roślinie. Przenoszą też wirusy.",
    notes=("Ciepła pogoda (średnia z 7 dni >= 18 °C) zwiększa aktywność.",),
    assumptions={"dd10_start": 250, "dd10_peak": [380, 900], "dd10_end": 1200, "warm_mean_c": 18},
))
_add(Rule(
    code="maize.frit_fly", crop=MAIZE, category="pest", kind="pest_activity",
    name_pl="ploniarka zbożówka", name_en="Frit fly",
    stage_min=10, stage_max=14, stage_ramp=2, severity=0.05,
    action_threshold="Od wschodów do 4 liści (BBCH 10-14): 15 % roślin uszkodzonych w poprzednim roku.",
    notes=("Chłodna wiosna i bliskość zbóż ozimych zwiększają ryzyko; liczone jako chłodna średnia z 7 dni (< 15 °C).",),
    assumptions={"cool_mean_c": 15},
))

# --- More wheat and maize threats ---------------------------------------------------------------
_add(Rule(
    code="wheat.eyespot", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="łamliwość źdźbła zbóż", name_en="Eyespot",
    stage_min=21, stage_max=32, stage_ramp=4, temp_min=5, temp_max=15, moisture="humid",
    window_days=14, hours_low=60, hours_high=200, cereal_after_cereal=1.5, severity=0.15,
    action_threshold="Od początku strzelania w źdźbło do pierwszego kolanka (BBCH 30-31): 20-30 % źdźbeł z objawami.",
    notes=("Wysoka wilgotność powietrza i gleby przy 5-15 °C; narasta w monokulturach zbożowych.",),
    assumptions={"hours_low": 60, "hours_high": 200, "window_days": 14, "cereal_after_cereal": 1.5},
))
_add(Rule(
    code="wheat.fusarium_foot_rot", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="fuzaryjna zgorzel podstawy źdźbła i korzeni", name_en="Fusarium foot and root rot",
    stage_min=21, stage_max=39, temp_min=5, temp_max=25, moisture="humid",
    window_days=14, hours_low=100, hours_high=250, cereal_after_cereal=1.3, after_maize=1.3, severity=0.12,
    action_threshold="Brak progu; zapobiega się płodozmianem, zagospodarowaniem resztek i zaprawianiem nasion.",
    notes=("Sprzyja jej wilgotne powietrze i gleba albo przesuszona gleba.",),
    assumptions={"hours_low": 100, "hours_high": 250, "window_days": 14},
))
_add(Rule(
    code="wheat.glume_blotch", crop=WHEAT, category="fungal", kind="infection_hours",
    name_pl="septorioza plew", name_en="Septoria glume blotch",
    stage_min=37, stage_max=75, temp_min=10, temp_max=20, moisture="wet",
    window_days=10, hours_low=12, hours_high=40, needs_rain_days=2, severity=0.10,
    stage_thresholds=((21, 29, "Krzewienie: 20 % roślin z pierwszymi objawami"), (30, 39, "Strzelanie w źdźbło: 20 % powierzchni liścia podflagowego lub 1 % liści z owocnikami"), (51, 59, "Kłoszenie: 10 % liścia podflagowego, w pełni kłoszenia 1 % liścia flagowego")),
    action_threshold="Zobacz progi dla faz rozwoju.",
    notes=("Krople deszczu przenoszą ją na liście i kłosy.",),
    assumptions={"hours_low": 12, "hours_high": 40, "needs_rain_days": 2},
))
_add(Rule(
    code="wheat.barley_yellow_dwarf", crop=WHEAT, category="viral", kind="vector_days",
    name_pl="żółta karłowatość jęczmienia (wirus przenoszony przez mszyce)", name_en="Barley yellow dwarf (aphid-borne virus)",
    stage_min=10, stage_max=29, stage_ramp=3, window_days=60, hours_low=8, hours_high=30, severity=0.12,
    action_threshold="Mszyce przenoszą wirusa: obserwuj pierwsze naloty na plantację jesienią i wiosną; pomagają żółte naczynia. Porażonych roślin nie da się wyleczyć.",
    notes=("Liczone jako jesienne dni wystarczająco ciepłe na loty mszyc (maks. >= 12 °C) od wschodów.",),
    assumptions={"aphid_flight_max_c": 12, "days_low": 8, "days_high": 30},
))
_add(Rule(
    code="wheat.aphids", crop=WHEAT, category="pest", kind="pest_activity",
    name_pl="mszyce (na kłosach)", name_en="Grain aphids",
    stage_min=51, stage_max=75, stage_ramp=4, dd10_start=0, dd10_peak=(0, 1e9), dd10_end=2e9, warm_ramp=(14, 20),
    severity=0.08,
    action_threshold="W czasie kłoszenia lub tuż po nim: 5 mszyc na kłosie.",
    notes=("Ciepła pogoda przyspiesza namnażanie mszyc.",),
    assumptions={"warm_mean_c": [14, 20]},
))
_add(Rule(
    code="wheat.cereal_leaf_beetle", crop=WHEAT, category="pest", kind="pest_activity",
    name_pl="skrzypionki", name_en="Cereal leaf beetle",
    stage_min=37, stage_max=59, stage_ramp=4, dd10_start=0, dd10_peak=(0, 1e9), dd10_end=2e9, warm_ramp=(12, 18),
    severity=0.10,
    action_threshold="Gdy pojawia się liść flagowy: 1-1,5 larwy na źdźble. Jedna larwa może zniszczyć 10 % liścia flagowego, czyli ok. 10 % plonu.",
    assumptions={"warm_mean_c": [12, 18]},
))
_add(Rule(
    code="maize.northern_leaf_blight", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="żółta plamistość liści kukurydzy", name_en="Northern corn leaf blight",
    stage_min=30, stage_max=85, stage_ramp=6, temp_min=18, temp_max=27, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, maize_monoculture=1.3, severity=0.08,
    action_threshold="Oglądaj dolne liście; rozdrobnienie resztek i płodozmian ją ograniczają.",
    assumptions={"temp_range_c": [18, 27], "hours_low": 15, "hours_high": 50},
))
_add(Rule(
    code="maize.eyespot", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="drobna plamistość liści kukurydzy", name_en="Maize eyespot (Kabatiella)",
    stage_min=30, stage_max=85, stage_ramp=6, temp_min=10, temp_max=20, moisture="wet",
    window_days=10, hours_low=20, hours_high=60, maize_monoculture=1.3, severity=0.06,
    action_threshold="Oglądaj liście po chłodnych, deszczowych okresach; rozdrobnienie resztek i płodozmian ją ograniczają.",
    assumptions={"temp_range_c": [10, 20], "hours_low": 20, "hours_high": 60},
))
_add(Rule(
    code="maize.common_rust", crop=MAIZE, category="fungal", kind="infection_hours",
    name_pl="rdza kukurydzy", name_en="Common rust",
    stage_min=30, stage_max=85, stage_ramp=6, temp_min=16, temp_max=25, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, severity=0.05,
    action_threshold="Oglądaj liście przy ciepłej, wilgotnej pogodzie.",
    assumptions={"temp_range_c": [16, 25], "hours_low": 15, "hours_high": 50},
))


# --- Other crops ------------------------------------------------------------------------------------
# Barley, other cereals (triticale, rye, oats), rapeseed, sugar beet and potatoes. Temperature and
# humidity ranges and thresholds follow the integrated protection guides for these crops; rapeseed has
# no guide in the package, so its numbers are general agronomy and listed under `assumptions`.


def _variant(code: str, new_code: str, crop: int, **changes) -> None:
    """A rule shared by several cereals: same biology, own code, crop and (optionally) numbers."""
    _add(replace(RULES[code], code=new_code, crop=crop, **changes))


# Barley (winter barley is the main form in the region)
_variant("wheat.powdery_mildew", "barley.powdery_mildew", BARLEY,
         stage_thresholds=((21, 29, "Krzewienie: 25-35 % roślin z pierwszymi objawami"), (30, 39, "Strzelanie w źdźbło: 10 % źdźbeł z pierwszymi objawami")),
         action_threshold="Krzewienie: 25-35 % roślin z pierwszymi objawami; strzelanie w źdźbło: 10 % źdźbeł.")
_variant("wheat.fusarium_head_blight", "barley.fusarium_head_blight", BARLEY, stage_min=55, stage_max=69, severity=0.10,
         notes=("Jęczmień browarny musi być wolny od fuzarium; resztki kukurydzy zwiększają ryzyko.",))
_variant("wheat.eyespot", "barley.eyespot", BARLEY)
_variant("wheat.fusarium_foot_rot", "barley.fusarium_foot_rot", BARLEY)
_variant("wheat.take_all", "barley.take_all", BARLEY, severity=0.10)
_variant("wheat.snow_mould", "barley.snow_mould", BARLEY)
_variant("wheat.barley_yellow_dwarf", "barley.barley_yellow_dwarf", BARLEY, severity=0.18,
         action_threshold="Jęczmień ozimy jest najbardziej narażony: mszyce przenoszą wirusa ok. 5 tygodni po wschodach jesienią; wiosną pierwsze naloty na plantację.")
_variant("wheat.aphids", "barley.aphids", BARLEY, action_threshold="W czasie kłoszenia lub tuż po nim: 5 mszyc na kłosie.")
_variant("wheat.cereal_leaf_beetle", "barley.cereal_leaf_beetle", BARLEY)
_add(Rule(
    code="barley.net_blotch", crop=BARLEY, category="fungal", kind="infection_hours",
    name_pl="plamistość siatkowa jęczmienia", name_en="Net blotch",
    stage_min=21, stage_max=69, temp_min=15, temp_max=25, moisture="wet",
    window_days=7, hours_low=6, hours_high=24, cereal_after_cereal=1.3, severity=0.15,
    stage_thresholds=((21, 29, "Krzewienie: 15-20 % powierzchni liści z objawami"), (30, 39, "Strzelanie w źdźbło: 15-20 % powierzchni liści z objawami")),
    action_threshold="15-20 % powierzchni liści z objawami (krzewienie i strzelanie w źdźbło).",
    notes=("Przeżywa na porażonym ziarnie, samosiewach i resztkach: jęczmień po jęczmieniu zwiększa ryzyko.",),
    assumptions={"hours_low": 6, "hours_high": 24, "cereal_after_cereal": 1.3},
))
_add(Rule(
    code="barley.scald", crop=BARLEY, category="fungal", kind="infection_hours",
    name_pl="rynchosporioza zbóż", name_en="Leaf scald (Rhynchosporium)",
    stage_min=21, stage_max=59, temp_min=5, temp_max=12, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, needs_rain_days=2, cereal_after_cereal=1.2, severity=0.12,
    stage_thresholds=((21, 29, "Krzewienie: 15-20 % powierzchni liści z objawami"), (30, 39, "Strzelanie w źdźbło: 15-20 % powierzchni liści z objawami")),
    action_threshold="15-20 % powierzchni liści z objawami (krzewienie i strzelanie w źdźbło).",
    notes=("Choroba chłodnej pogody, roznoszona przez krople deszczu.",),
    assumptions={"hours_low": 15, "hours_high": 50, "needs_rain_days": 2},
))
_add(Rule(
    code="barley.brown_rust", crop=BARLEY, category="fungal", kind="infection_hours",
    name_pl="rdza jęczmienia", name_en="Barley leaf rust",
    stage_min=21, stage_max=75, temp_min=10, temp_max=22, moisture="wet",
    window_days=7, hours_low=4, hours_high=16, severity=0.10,
    stage_thresholds=((21, 29, "Krzewienie: 10-15 % liści z pierwszymi objawami"), (30, 39, "Strzelanie w źdźbło: 10 % źdźbeł z pierwszymi objawami")),
    action_threshold="Krzewienie: 10-15 % liści z pierwszymi objawami; strzelanie w źdźbło: 10 % źdźbeł.",
    notes=("Źródłem są porażone samosiewy.",),
    assumptions={"hours_low": 4, "hours_high": 16},
))

# Other cereals: triticale, rye and oats share one crop-map class; rules follow triticale and rye
_variant("wheat.powdery_mildew", "other_cereals.powdery_mildew", OTHER_CEREALS)
_variant("wheat.fusarium_head_blight", "other_cereals.fusarium_head_blight", OTHER_CEREALS)
_variant("wheat.glume_blotch", "other_cereals.glume_blotch", OTHER_CEREALS)
_variant("wheat.yellow_rust", "other_cereals.yellow_rust", OTHER_CEREALS,
         notes=("Pszenżyto jest bardzo podatne na rdzę żółtą; nowe patotypy rozwijają się też w 10-28 °C, przy suchej i ciepłej pogodzie.",))
_variant("wheat.tan_spot", "other_cereals.tan_spot", OTHER_CEREALS)
_variant("wheat.eyespot", "other_cereals.eyespot", OTHER_CEREALS)
_variant("wheat.fusarium_foot_rot", "other_cereals.fusarium_foot_rot", OTHER_CEREALS)
_variant("wheat.snow_mould", "other_cereals.snow_mould", OTHER_CEREALS, severity=0.15,
         notes=("Żyto i pszenżyto są najbardziej narażone; liczone jako dni z temperaturą 0-5 °C, pokrywą śnieżną i niezamarzniętą glebą.",))
_variant("wheat.barley_yellow_dwarf", "other_cereals.barley_yellow_dwarf", OTHER_CEREALS)
_variant("wheat.aphids", "other_cereals.aphids", OTHER_CEREALS)
_variant("wheat.cereal_leaf_beetle", "other_cereals.cereal_leaf_beetle", OTHER_CEREALS)
_variant("wheat.brown_rust", "other_cereals.brown_rust", OTHER_CEREALS, temp_min=15, temp_max=20,
         notes=("Okresowy dobowy wzrost wilgotności powietrza (rosa); liczone jako mokre godziny w 15-20 °C. Żyto i pszenżyto są bardzo podatne.",))
_variant("barley.scald", "other_cereals.scald", OTHER_CEREALS)

# Winter rapeseed (sown late August)
_add(Rule(
    code="rapeseed.phoma_stem_canker", crop=RAPESEED, category="fungal", kind="infection_hours",
    name_pl="sucha zgnilizna kapustnych (phoma)", name_en="Phoma stem canker (blackleg)",
    stage_min=10, stage_max=19, stage_ramp=3, temp_min=8, temp_max=20, moisture="wet",
    window_days=10, hours_low=20, hours_high=60, needs_rain_days=2, same_crop=1.4, severity=0.15,
    action_threshold="Jesień: 10-20 % roślin z plamami na liściach w fazie 4-8 liści (BBCH 14-18).",
    notes=("Askospory uwalniają się z rzepakowego ścierniska po deszczu; jesienne infekcje wiosną przechodzą w nekrozy szyjki korzeniowej i łodygi.",),
    assumptions={"temp_range_c": [8, 20], "hours_low": 20, "hours_high": 60, "needs_rain_days": 2, "threshold": "10-20 % roślin", "same_crop": 1.4},
))
_add(Rule(
    code="rapeseed.light_leaf_spot", crop=RAPESEED, category="fungal", kind="infection_hours",
    name_pl="cylindrosporioza", name_en="Light leaf spot",
    stage_min=14, stage_max=59, temp_min=5, temp_max=16, moisture="wet",
    window_days=14, hours_low=30, hours_high=90, needs_rain_days=3, same_crop=1.3, severity=0.10,
    action_threshold="Jesień lub wczesna wiosna: 15-25 % roślin z objawami.",
    notes=("Choroba chłodnej i mokrej pogody, roznoszona przez krople deszczu; rozwija się w łagodne zimy.",),
    assumptions={"temp_range_c": [5, 16], "hours_low": 30, "hours_high": 90, "needs_rain_days": 3, "threshold": "15-25 % roślin"},
))
_add(Rule(
    code="rapeseed.sclerotinia_stem_rot", crop=RAPESEED, category="fungal", kind="infection_hours",
    name_pl="zgnilizna twardzikowa", name_en="Sclerotinia stem rot",
    stage_min=60, stage_max=69, stage_ramp=4, temp_min=10, temp_max=25, moisture="humid",
    window_days=5, hours_low=20, hours_high=60, same_crop=1.5, severity=0.20,
    after_crops=((1410, 1.3, "Przedplon: słonecznik (sklerocja w glebie)"), (1420, 1.3, "Przedplon: soja (sklerocja w glebie)")),
    action_threshold="Zabieg działa tylko zapobiegawczo, od początku do pełni kwitnienia (BBCH 61-65); decyduj na podstawie pogody i historii pola.",
    notes=("Sklerocja przeżywają w glebie latami; opadłe płatki w wilgotnym łanie zaczynają infekcję.",),
    assumptions={"temp_range_c": [10, 25], "hours_low": 20, "hours_high": 60, "window_days": 5, "same_crop": 1.5},
))
_add(Rule(
    code="rapeseed.alternaria_black_spot", crop=RAPESEED, category="fungal", kind="infection_hours",
    name_pl="czerń krzyżowych", name_en="Alternaria black spot",
    stage_min=70, stage_max=85, stage_ramp=5, temp_min=18, temp_max=27, moisture="wet",
    window_days=7, hours_low=10, hours_high=36, severity=0.10,
    action_threshold="Rozwój łuszczyn: 25 % łuszczyn z plamami.",
    notes=("Ciepła, mokra pogoda w czasie dojrzewania łuszczyn; porażone łuszczyny wcześnie pękają.",),
    assumptions={"temp_range_c": [18, 27], "hours_low": 10, "hours_high": 36, "threshold": "25 % łuszczyn"},
))
_add(Rule(
    code="rapeseed.clubroot", crop=RAPESEED, category="fungal", kind="soil_days",
    name_pl="kiła kapusty", name_en="Clubroot",
    stage_min=0, stage_max=19, stage_ramp=3, window_days=21, hours_low=5, hours_high=14,
    soil_temp=(15.0, 26.0), soil_wet=0.30, same_crop=1.5, acid_soil=1.5, severity=0.15,
    action_threshold="W sezonie nie ma zabiegu: płodozmian (4-5 lat bez kapustowatych), wapnowanie kwaśnych gleb, odmiany odporne.",
    notes=("Zarodniki przetrwalnikowe przeżywają ponad 10 lat; ciepła, mokra, kwaśna gleba w czasie siewu sprzyja infekcji.",),
    assumptions={"soil_temp_c": [15, 26], "soil_moisture_min": 0.30, "days_low": 5, "days_high": 14, "acid_soil_ph": 6.5},
))
_add(Rule(
    code="rapeseed.cabbage_stem_flea_beetle", crop=RAPESEED, category="pest", kind="vector_days",
    name_pl="pchełka rzepakowa", name_en="Cabbage stem flea beetle",
    stage_min=10, stage_max=18, stage_ramp=2, window_days=21, hours_low=7, hours_high=18, flight_c=18.0, severity=0.10,
    action_threshold="Od wschodów do 4 liści: 3 chrząszcze na m² lub 10 % zjedzonej powierzchni liści; później larwy w ogonkach i łodygach.",
    notes=("Chrząszcze nalatują na wschodzącą plantację w ciepłe jesienne dni.",),
    assumptions={"flight_max_c": 18, "days_low": 7, "days_high": 18},
))
_add(Rule(
    code="rapeseed.aphids_tuyv", crop=RAPESEED, category="viral", kind="vector_days",
    name_pl="mszyca brzoskwiniowa - wirus żółtaczki rzepy (TuYV)", name_en="Aphids and turnip yellows virus",
    stage_min=10, stage_max=19, stage_ramp=3, window_days=45, hours_low=10, hours_high=30, flight_c=15.0, severity=0.10,
    action_threshold="Jesień: obserwuj pierwsze uskrzydlone mszyce (żółte naczynia); długa, ciepła jesień zwiększa ryzyko.",
    notes=("Długa, ciepła jesień sprzyja nalotom mszyc na plantację.",),
    assumptions={"flight_max_c": 15, "days_low": 10, "days_high": 30},
))
_add(Rule(
    code="rapeseed.stem_weevils", crop=RAPESEED, category="pest", kind="vector_days",
    name_pl="chowacze łodygowe", name_en="Stem weevils",
    stage_min=30, stage_max=50, stage_ramp=3, window_days=10, hours_low=2, hours_high=6, flight_c=12.0, severity=0.12,
    action_threshold="Początek wzrostu pędu: ok. 20 chrząszczy w żółtym naczyniu w ciągu 3 dni; zabieg przed złożeniem jaj.",
    notes=("Pierwsze wiosenne naloty w dni powyżej ok. 12 °C, gdy pęd zaczyna rosnąć.",),
    assumptions={"flight_max_c": 12, "days_low": 2, "days_high": 6, "threshold": "20 chrząszczy / naczynie / 3 dni"},
))
_add(Rule(
    code="rapeseed.pollen_beetle", crop=RAPESEED, category="pest", kind="vector_days",
    name_pl="słodyszek rzepakowy", name_en="Pollen beetle",
    stage_min=50, stage_max=59, stage_ramp=2, window_days=7, hours_low=2, hours_high=5, flight_c=15.0, severity=0.15,
    stage_thresholds=((50, 53, "Zielony pąk: 1 chrząszcz na roślinie"), (54, 59, "Żółty pąk: 3-5 chrząszczy na roślinie")),
    action_threshold="Zielony pąk: 1 chrząszcz na roślinie; żółty pąk: 3-5 chrząszczy na roślinie.",
    notes=("Chrząszcze żerują na zamkniętych pąkach; gdy zaczyna się kwitnienie, zjadają pyłek i szkodzą niewiele.",),
    assumptions={"flight_max_c": 15, "days_low": 2, "days_high": 5},
))
_add(Rule(
    code="rapeseed.seed_weevil_pod_midge", crop=RAPESEED, category="pest", kind="vector_days",
    name_pl="chowacz podobnik i pryszczarek kapustnik", name_en="Seed weevil and pod midge",
    stage_min=60, stage_max=71, stage_ramp=3, window_days=7, hours_low=2, hours_high=5, flight_c=15.0, severity=0.08,
    action_threshold="Kwitnienie: 1 chowacz na 2 rośliny (otwory po chowaczu wpuszczają pryszczarka).",
    assumptions={"flight_max_c": 15, "days_low": 2, "days_high": 5},
))

# Sugar beet (sown early April)
_add(Rule(
    code="sugar_beet.cercospora_leaf_spot", crop=SUGAR_BEET, category="fungal", kind="infection_hours",
    name_pl="chwościk buraka", name_en="Cercospora leaf spot",
    stage_min=31, stage_max=49, stage_ramp=6, temp_min=16, temp_max=32, moisture="humid",
    window_days=7, hours_low=30, hours_high=90, same_crop=1.5, severity=0.20,
    action_threshold="Południe Polski: pierwsze plamy na liściach; w pozostałych rejonach do 5 sierpnia 5 % roślin z objawami, 5-15 sierpnia 10-15 %, 15 sierpnia - 10 września 45 %.",
    notes=("Najważniejsza choroba buraka w Polsce: ciepłe dni (25-30 °C), noce powyżej 15 °C i długie okresy wilgotne; obserwuj od początku lipca (na południu od połowy czerwca) po kilku deszczowych, ciepłych dniach.",
           "Liczone jako wilgotne godziny w 16-32 °C (z ciepłymi nocami)."),
    assumptions={"temp_range_c": [16, 32], "hours_low": 30, "hours_high": 90, "same_crop": 1.5},
))
_add(Rule(
    code="sugar_beet.ramularia_leaf_spot", crop=SUGAR_BEET, category="fungal", kind="infection_hours",
    name_pl="brunatna plamistość liści buraka", name_en="Ramularia leaf spot",
    stage_min=31, stage_max=49, stage_ramp=6, temp_min=15, temp_max=22, moisture="wet",
    window_days=10, hours_low=15, hours_high=50, severity=0.08,
    notes=("Chłodniejsza (17-20 °C) i mokra pogoda.",),
    assumptions={"temp_range_c": [15, 22], "hours_low": 15, "hours_high": 50},
))
_add(Rule(
    code="sugar_beet.powdery_mildew", crop=SUGAR_BEET, category="fungal", kind="infection_hours",
    name_pl="mączniak prawdziwy buraka", name_en="Beet powdery mildew",
    stage_min=35, stage_max=49, stage_ramp=6, temp_min=20, temp_max=30, moisture="mild",
    window_days=7, hours_low=40, hours_high=100, severity=0.08,
    notes=("Ciepła (20-30 °C), sucha i słoneczna pogoda.",),
    assumptions={"temp_range_c": [20, 30], "hours_low": 40, "hours_high": 100},
))
_add(Rule(
    code="sugar_beet.downy_mildew", crop=SUGAR_BEET, category="fungal", kind="infection_hours",
    name_pl="mączniak rzekomy buraka", name_en="Beet downy mildew",
    stage_min=10, stage_max=39, stage_ramp=4, temp_min=5, temp_max=15, moisture="wet",
    window_days=10, hours_low=20, hours_high=60, severity=0.05,
    notes=("Chłodna (do 15 °C), mokra i pochmurna pogoda.",),
    assumptions={"temp_range_c": [5, 15], "hours_low": 20, "hours_high": 60},
))
_add(Rule(
    code="sugar_beet.seedling_damping_off", crop=SUGAR_BEET, category="fungal", kind="soil_days",
    name_pl="zgorzel siewek buraka", name_en="Seedling damping-off",
    stage_min=0, stage_max=14, stage_ramp=3, window_days=10, hours_low=3, hours_high=8, soil_temp=(None, 15.0), heavy_soil=1.3,
    severity=0.08,
    action_threshold="Zapobiega się zaprawianiem nasion i siewem w ogrzaną glebę; w sezonie nie ma zabiegu.",
    notes=("Zgorzel przedwschodowa przy glebie do 15 °C i dużej wilgotności; zbita gleba ze skorupą ją pogarsza.",),
    assumptions={"soil_temp_max_c": 15, "soil_moisture_min": 0.30, "days_low": 3, "days_high": 8},
))
_add(Rule(
    code="sugar_beet.rhizoctonia_root_rot", crop=SUGAR_BEET, category="fungal", kind="soil_days",
    name_pl="zgnilizna brunatna korzeni buraka", name_en="Rhizoctonia root and crown rot",
    stage_min=31, stage_max=49, stage_ramp=6, window_days=21, hours_low=5, hours_high=14, soil_temp=(20.0, 30.0),
    same_crop=1.5, heavy_soil=1.3, severity=0.12,
    after_crops=((1130, 1.4, "Przedplon: kukurydza (ta sama grupa Rhizoctonia poraża kukurydzę)"),),
    action_threshold="W sezonie nie ma zabiegu: płodozmian, odmiany tolerancyjne, unikanie zagęszczenia gleby.",
    notes=("Ciepła (20-30 °C), mokra gleba latem.",),
    assumptions={"soil_temp_c": [20, 30], "soil_moisture_min": 0.30, "days_low": 5, "days_high": 14, "after_maize": 1.4},
))
_add(Rule(
    code="sugar_beet.aphids_virus_yellows", crop=SUGAR_BEET, category="viral", kind="vector_days",
    name_pl="mszyce - wirusowe żółtaczki buraka", name_en="Aphids and virus yellows",
    stage_min=12, stage_max=39, stage_ramp=4, window_days=14, hours_low=4, hours_high=10, flight_c=17.0, severity=0.12,
    action_threshold="Od 3-4 liści: co najmniej 15 % roślin z mszycami lub 15 bezskrzydłych mszyc na roślinie; przeciw wirusom już pierwsze uskrzydlone mszyce.",
    notes=("Ciepła, sucha wiosna przynosi wczesne naloty mszyc.",),
    assumptions={"flight_max_c": 17, "days_low": 4, "days_high": 10},
))
_add(Rule(
    code="sugar_beet.flea_beetle", crop=SUGAR_BEET, category="pest", kind="vector_days",
    name_pl="pchełka burakowa", name_en="Beet flea beetle",
    stage_min=10, stage_max=15, stage_ramp=2, window_days=7, hours_low=2, hours_high=5, flight_c=18.0, severity=0.06,
    action_threshold="Od wschodów do 4-5 liści: 5-10 chrząszczy na m².",
    notes=("Ciepła, sucha pogoda w czasie wschodów.",),
    assumptions={"flight_max_c": 18, "days_low": 2, "days_high": 5},
))
_add(Rule(
    code="sugar_beet.beet_leaf_miner", crop=SUGAR_BEET, category="pest", kind="pest_activity",
    name_pl="śmietka ćwiklanka", name_en="Beet leaf miner",
    stage_min=11, stage_max=19, stage_ramp=3, dd10_start=80, dd10_peak=(150, 300), dd10_end=450, warm_ramp=(12, 18),
    severity=0.05,
    stage_thresholds=((11, 12, "2 liście właściwe: 4 jaja lub miny na roślinie"), (13, 14, "4 liście właściwe: 8 jaj lub min na roślinie"), (15, 19, "6 liści właściwych: ponad 20 jaj lub min na roślinie")),
    action_threshold="Od maja: 4 jaja lub miny na roślinie przy 2 liściach, 8 przy 4 liściach, ponad 20 przy 6 liściach.",
    assumptions={"dd10_start": 80, "dd10_peak": [150, 300], "dd10_end": 450},
))
_add(Rule(
    code="sugar_beet.beet_cyst_nematode", crop=SUGAR_BEET, category="pest", kind="pest_activity",
    name_pl="mątwik burakowy", name_en="Beet cyst nematode",
    stage_min=10, stage_max=49, stage_ramp=5, dd10_start=50, dd10_peak=(200, 900), dd10_end=1400,
    rotation_hosts=(SUGAR_BEET, RAPESEED), rotation_years=3, severity=0.15,
    action_threshold="Analiza gleby przed siewem: 500 jaj i larw na 100 g gleby. W sezonie nie ma zabiegu: płodozmian, odmiany tolerancyjne, międzyplony odporne na mątwika.",
    notes=("Rzepak i inne kapustowate też są żywicielami: burak lub rzepak w ostatnich 3 sezonach utrzymuje populację.",),
    assumptions={"rotation_years": 3, "pressure_with_host": 1.0, "pressure_without_host": 0.1},
))

# Potato (planted late April)
_add(Rule(
    code="potato.late_blight", crop=POTATO, category="fungal", kind="infection_hours",
    name_pl="zaraza ziemniaka", name_en="Late blight",
    stage_min=21, stage_max=91, stage_ramp=5, temp_min=10, temp_max=25, moisture="rh90",
    window_days=2, hours_low=11, hours_high=22, same_crop=1.2, severity=0.30,
    action_threshold="Odmiany wczesne: zacznij ochronę, gdy rzędy się zwierają; późniejsze: gdy pojawią się pierwsze objawy na odmianach wczesnych. Zabiegi po pojawieniu się objawów rzadko ją zatrzymują.",
    notes=("Najważniejsza choroba ziemniaka. Liczona jak okres Smitha: godziny w 10-25 °C przy wilgotności >= 90 % lub deszczu w ostatnich 2 dniach (2 x 11 h = pełne ryzyko).",
           "Systemy wspomagania decyzji (NegFry) wyznaczają terminy zabiegów na podstawie pogody."),
    assumptions={"hours_low": 11, "hours_high": 22, "window_days": 2, "rh": 90},
))
_add(Rule(
    code="potato.early_blight", crop=POTATO, category="fungal", kind="infection_hours",
    name_pl="alternarioza ziemniaka", name_en="Early blight (Alternaria)",
    stage_min=40, stage_max=91, stage_ramp=10, temp_min=18, temp_max=30, moisture="wet",
    window_days=7, hours_low=10, hours_high=40, same_crop=1.3, severity=0.12,
    action_threshold="Od przyrostu bulw oglądaj starsze liście; rośliny w stresie (susza, mało azotu) są bardziej narażone.",
    notes=("Ciepła pogoda z przeplatającymi się okresami mokrymi i suchymi; resztki w glebie przenoszą ją na kolejny sezon.",),
    assumptions={"temp_range_c": [18, 30], "hours_low": 10, "hours_high": 40},
))
_add(Rule(
    code="potato.rhizoctonia", crop=POTATO, category="fungal", kind="soil_days",
    name_pl="rizoktonioza ziemniaka", name_en="Rhizoctonia stem canker",
    stage_min=0, stage_max=19, stage_ramp=3, window_days=14, hours_low=3, hours_high=10, soil_temp=(None, 10.0), same_crop=1.3,
    severity=0.08,
    action_threshold="Zapobiega się zaprawianiem sadzeniaków i sadzeniem w ogrzaną glebę; w sezonie nie ma zabiegu.",
    notes=("Zimna, mokra gleba po sadzeniu spowalnia wschody i pozwala grzybowi atakować kiełki i łodygi.",),
    assumptions={"soil_temp_max_c": 10, "soil_moisture_min": 0.30, "days_low": 3, "days_high": 10},
))
_add(Rule(
    code="potato.colorado_potato_beetle", crop=POTATO, category="pest", kind="pest_activity",
    name_pl="stonka ziemniaczana", name_en="Colorado potato beetle",
    stage_min=10, stage_max=79, stage_ramp=5, dd10_start=150, dd10_peak=(300, 650), dd10_end=950, warm_ramp=(15, 22),
    same_crop=1.4, severity=0.20,
    action_threshold="Po wschodach: 10 złóż jaj na 10 roślin lub 15 larw na roślinie lub 1-2 przezimowane chrząszcze na 25 roślin; zabieg, gdy większość larw jest w stadium L2-L3.",
    notes=("Chrząszcze zimują w glebie i nalatują z zeszłorocznych pól ziemniaka; najwięcej strat robią larwy (20-30 % bez ochrony).",),
    assumptions={"dd10_start": 150, "dd10_peak": [300, 650], "dd10_end": 950, "same_crop": 1.4},
))
_add(Rule(
    code="potato.aphids", crop=POTATO, category="viral", kind="pest_activity",
    name_pl="mszyce - wektory wirusów ziemniaka", name_en="Aphids (virus vectors)",
    stage_min=10, stage_max=69, stage_ramp=5, dd10_start=150, dd10_peak=(250, 700), dd10_end=1000, warm_ramp=(14, 20),
    severity=0.08,
    action_threshold="Po wschodach, jako wektory wirusów: 5-10 mszyc na 100 liści (plantacje nasienne), 10-20 na 100 liści (plantacje towarowe); jako szkodnik: 500 na 100 liści.",
    assumptions={"dd10_start": 150, "dd10_peak": [250, 700], "dd10_end": 1000},
))
_add(Rule(
    code="potato.cyst_nematode", crop=POTATO, category="pest", kind="pest_activity",
    name_pl="mątwik ziemniaczany", name_en="Potato cyst nematode",
    stage_min=10, stage_max=79, stage_ramp=5, dd10_start=50, dd10_peak=(200, 800), dd10_end=1200,
    rotation_hosts=(POTATO,), rotation_years=3, severity=0.10,
    action_threshold="Analiza gleby przed sadzeniem: do 10 jaj z żywymi larwami na 1 g gleby. W sezonie nie ma zabiegu: płodozmian i odmiany odporne.",
    notes=("Cysty zachowują żywotność do 20 lat; ziemniak w ostatnich 3 sezonach utrzymuje populację.",),
    assumptions={"rotation_years": 3, "pressure_with_host": 1.0, "pressure_without_host": 0.1},
))


CEREALS = {WHEAT, BARLEY, OTHER_CEREALS}
WINTER_CROPS = {WHEAT, BARLEY, OTHER_CEREALS, RAPESEED}  # dormant in winter: leaf diseases switch off in the cold

# Last season's risk on the same field that carries over in residue / soil (same pathogen or pest).
# Fusarium spp. infect both maize and wheat, so a bad maize year raises next year's head blight.
CARRYOVER = {
    "wheat.fusarium_head_blight": ("wheat.fusarium_head_blight", "barley.fusarium_head_blight", "other_cereals.fusarium_head_blight",
                                   "maize.fusarium_ear_rot", "maize.fusarium_stalk_rot"),
    "maize.fusarium_ear_rot": ("maize.fusarium_ear_rot", "maize.fusarium_stalk_rot", "wheat.fusarium_head_blight"),
    "maize.fusarium_stalk_rot": ("maize.fusarium_stalk_rot", "maize.fusarium_ear_rot", "wheat.fusarium_head_blight"),
    "wheat.septoria_leaf_blotch": ("wheat.septoria_leaf_blotch",),
    "wheat.tan_spot": ("wheat.tan_spot",),
    "wheat.take_all": ("wheat.take_all",),
    "maize.european_corn_borer": ("maize.european_corn_borer",),
    "barley.fusarium_head_blight": ("barley.fusarium_head_blight", "wheat.fusarium_head_blight", "other_cereals.fusarium_head_blight",
                                    "maize.fusarium_ear_rot", "maize.fusarium_stalk_rot"),
    "other_cereals.fusarium_head_blight": ("other_cereals.fusarium_head_blight", "wheat.fusarium_head_blight", "barley.fusarium_head_blight",
                                           "maize.fusarium_ear_rot", "maize.fusarium_stalk_rot"),
    "barley.net_blotch": ("barley.net_blotch",),
    "rapeseed.phoma_stem_canker": ("rapeseed.phoma_stem_canker",),
    "rapeseed.sclerotinia_stem_rot": ("rapeseed.sclerotinia_stem_rot",),
    "sugar_beet.cercospora_leaf_spot": ("sugar_beet.cercospora_leaf_spot",),
    "potato.late_blight": ("potato.late_blight",),
    "potato.colorado_potato_beetle": ("potato.colorado_potato_beetle",),
}


def rules_for_crop(crop_code: int) -> list[Rule]:
    return [r for r in RULES.values() if r.crop == crop_code]
