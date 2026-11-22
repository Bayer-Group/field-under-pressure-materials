"""
Question type without an LLM: keyword rules on folded text (lowercase, no Polish letters), plus
detection of field names, crop and threats. Priority:

  pending draft + a short yes/no -> potwierdzenie ("tak, ale to było na Klinie" -> obserwacja, a correction)
  "pokaż / wykres / trend / jak się zmieniało" -> wykres
  "widzę / zauważyłem / pojawiły się / znalazłem / zapisz obserwację" -> obserwacja
  "wszystkie pola / moich polach / co najpilniejsze / gospodarstwo" (or >= 2 fields compared, or "raport"
      with no field selected or named) -> podsumowanie_farmy
  complex (>= 2 fields, several threats, explicit date ranges) and ASSISTANT_AGENT_MODE=1 -> zlozone
  field reference ("to pole", a field name, a selected field) + risk / what-to-do words -> pytanie_o_pole
  thanks, greetings, nothing agricultural (no field in context) -> poza_zakresem (fixed answer, no LLM)
  otherwise -> pytanie_ogolne
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from assistant import domain

CONFIRM_YES = {"tak", "zapisz", "potwierdzam", "ok", "okej", "zgadza sie", "dobrze", "jasne", "tak zapisz", "zapisuj"}
CONFIRM_NO = {"nie", "anuluj", "nie zapisuj", "rezygnuje", "odrzuc", "stop", "nie trzeba"}

# "pokaż" (imperative) only, not "pokazuje"
CHART = [r"\bpokaz(cie)?\b", r"\bwykres", r"\btrend", r"jak sie zmienial", r"\bprzebieg", r"\bnarysuj", r"\bzobrazuj"]
OBSERVATION = [r"\bwidze\b", r"zauwazyl", r"pojawil\w* sie", r"znalazl", r"zapisz obserwacj", r"\bdostrzegl",
               r"na polu (sa|jest|maja)", r"mam na polu", r"zaobserwowal", r"odnotuj",
               r"oprysk\w*al\w*", r"\bpryskal", r"wykonal\w* zabieg", r"\b(zasial|posial|sialem|sialam|wysial)",
               r"\b(przeszedl|przeszlam|obszedl|obeszlam|sprawdzil)\w*", r"\bgrad\b", r"wylegl|polegl", r"zalal\w*|podtopi",
               r"nie oral|bez orki"]
OBSERVATION_STATEMENT = [r"\bsasiad\w*"]   # only when it is a statement, not a question
# "the field is clean" in other words than "nie widzę": a report too (kind absence), not a question
ABSENCE = [r"\bnie ma (zadnych |zadnego )?(objaw|plam|szkodnik|mszyc|chorob)", r"\bbrak objaw", r"\bpole (jest )?czyste",
           r"\bnic nie (znalazl|ma\b|widac)", r"\bnie znalazl\w* (zadnych |nic)"]
# words that only say yes / no / save, with nothing new for the draft ("Tak, zapisz tę obserwację proszę")
CONFIRM_FILLER = {"tak", "zapisz", "zapisuj", "potwierdzam", "ok", "okej", "dobrze", "jasne", "oczywiscie", "prosze",
                  "to", "te", "ta", "ja", "tego", "tej", "go", "obserwacje", "zgloszenie", "zgadza", "sie", "wszystko", "zgodnie",
                  "moze", "byc"}
CANCEL_FILLER = {"nie", "anuluj", "zapisuj", "rezygnuje", "odrzuc", "stop", "trzeba", "dziekuje", "jednak", "to", "te",
                 "ta", "tego", "tej", "go", "obserwacji", "obserwacje", "zgloszenie", "zapisywac", "prosze"}
FARM = [r"wszystkie pola", r"wszystkich pol", r"najpilniejsz", r"gospodarstw", r"ktore pole", r"na ktorym polu",
        r"podsumuj", r"przeglad pol", r"cala farm", r"wszystkich uprawach",
        r"\bmoich pol", r"\bmoje pola\b", r"\bmoich upraw", r"\bmoje uprawy", r"\bnaszych pol", r"\bnasze pola\b",
        r"\bw gospodarstwie", r"ktore (\w+ ){0,2}pola\b", r"\bpol\w* (sa )?najbardziej"]
FARM_IF_NO_FIELD = [r"\braport", r"\bpodsumowani", r"\bzestawieni"]   # "raport ryzyk" with no field selected or named
# only when no field is in context: "co dziś robić?", "od czego zacząć?" = which field first
FARM_NO_FIELD = [r"od czego (\w+ ){0,2}zacz", r"\bco (\w+ ){0,3}(robic|zrobic)\b", r"\bsytuac", r"\bplan\w* na (dzis|dzisiaj|dzien|tydzien)",
                 r"gdzie (\w+ ){0,2}(jechac|isc|zaczac|najpierw|zajrzec)", r"\bco (slychac|nowego)", r"\bczym (\w+ ){0,2}zajac"]
GREETING_ONLY = re.compile(r"^(czesc|hej|witam|witaj|dzien dobry|dobry wieczor|siema|halo|hello|hi)( \w+)?$")
THANKS = re.compile(r"^(no )?(dzieki|dziekuje|dziekujemy|dzieks|thx|thanks|super|swietnie|ok dzieki)\b(\W*\w+){0,4}$|"
                    r"^(to (juz )?wszystko|nic wiecej)\b")
# a question to the assistant ("czy pryskałeś?", "czy sprawdziłeś pogodę?"), not a report from the field
QUESTION_TO_ASSISTANT = re.compile(r"^czy\b|\b\w+(les|las|lescie|lyscie)\b")
# a general question that only looks like a follow-up ("co to jest BBCH?", "ile to kosztuje?")
NOT_FOLLOW_UP = re.compile(r"\bco to (jest|znaczy)|\bdefinic|\bile (to )?kosztuj|\bco oznacza")
FIELD_REF = [r"\bto pole", r"\btym polu", r"\btego pola", r"\bmoje pole", r"\bmoim polu", r"\bmojego pola",
             r"\bna polu\b", r"\bpola\b", r"\bpole\b"]
RISK_INTENT = [r"ryzyk", r"zagroz", r"dlaczego", r"\bco (\w+ ){0,5}(robic|zrobic)", r"\bco (teraz|dalej|radzisz|polecasz|proponujesz)",
               r"\bjak (\w+ ){0,2}(ograniczyc|zmniejszyc|chronic|zapobiec|uratowac|ratowac)", r"na co (\w+ )?uwazac",
               r"\bmartwic", r"\bboje", r"\bbac\b", r"\bpilnowac", r"\bczy (\w+ ){0,2}(dobrze|zle|ok)\b",
               r"czy grozi", r"\bstan\b", r"niebezpiecz", r"\bgrozi", r"co mu dolega", r"co sie dzieje", r"\bjak (jest|wyglada)",
               r"\balarm", r"\bostrzez", r"czy (musze|trzeba|nalezy)"]
AGRO = [r"choro", r"szkodni", r"\bpol[aeiuo]?\b", r"\bpol(ach|ami|om)\b", r"upraw", r"pszen", r"kukurydz", r"zboz", r"ryzyk", r"opryskiw",
        r"nawo", r"\bsiew", r"\bplon", r"lisc", r"klos", r"metodyk", r"ochron", r"chwast", r"grzyb", r"pogod",
        r"deszcz", r"opad", r"temperatur", r"wilgot", r"bbch", r"odmian", r"gleb", r"termin", r"\bprog",
        r"lustrac", r"objaw", r"plam", r"mszyc", r"rdz", r"septori", r"fuzari", r"maczni", r"omacni", r"herbicyd",
        r"fungicyd", r"insektycyd", r"srodek", r"srodk", r"\bdawk", r"hektar", r"/ha\b", r"zgnili", r"zgorzel",
        r"agrotechn", r"plodozmian", r"przedplon", r"\bph\b", r"susz", r"przymroz", r"gospodarstw", r"zagroz",
        r"obserwac", r"wykres", r"trend", r"\bzbior", r"ziarn", r"kolb", r"lodyg", r"korzen", r"siewk",
        r"\bpada", r"burz", r"wiatr", r"upal", r"mroz", r"\bgrad", r"zabieg", r"oprysk", r"lustr", r"\bsiac", r"\bsial",
        r"owad", r"gasienic", r"larw", r"\bzaraz", r"choruj"]
OFF_TOPIC = [r"przepis na", r"kto wygral", r"napisz wiersz", r"bitcoin", r"\bfilm", r"pilk\w* noz", r"\bpolityk",
             r"opowiedz (mi )?dowcip", r"\bkawal\b"]
DATE_RANGE = [r"\bod \d{1,2}[ .]\w+ do\b", r"\bod (stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia)",
              r"\bw (marcu|kwietniu|maju|czerwcu|lipcu|sierpniu)\b", r"\bcaly sezon", r"\bod poczatku sezonu"]
COMPARE = [r"porownaj", r"porownani", r"roznic", r"\bvs\b", r"\bczy bardziej"]
FOLLOW_UP = [r"^a\b", r"\btam\b", r"\btego\b", r"\btym\b", r"\bto\b", r"\bzmniejsz", r"\bograniczyc",
             r"\bzapobiec", r"\bpomoc", r"\bco dalej", r"\bkiedy\b"]
FOLLOW_UP_MAX_WORDS = 6   # a follow-up is short; a longer message without a field name is a new question
CROP_WORDS = {"pszenic": "pszenica", "kukurydz": "kukurydza", "zboz": "zboza"}


@dataclass
class Route:
    type: str
    field_id: int | None = None
    field_ids: list[int] = field(default_factory=list)
    crop: str | None = None
    threats: list[str] = field(default_factory=list)   # Threat codes
    reason: str = ""
    field_source: str = ""                             # selected | named | ""
    previous_draft: dict | None = None                 # the pending draft a correction ("tak, ale…") refers to


def _any(patterns, text) -> str | None:
    for p in patterns:
        if re.search(p, text):
            return p
    return None


FIELD_CONTEXT_WORDS = {"pole", "pola", "polu", "polem", "na", "z", "ze", "o", "w", "dzialka", "dzialce", "dzialki"}
NAME_SKIP = {"pole", "pola", "polu"}


def _name_stem(word: str) -> str:
    """Inflection-tolerant stem of a field-name word: Górka/Górce/Górki -> gor, Długie/Długim -> dlug, Klin/Klinie -> kli."""
    return word[:max(3, len(word) - 2)] if len(word) >= 5 else word[:max(2, len(word) - 1)]


def find_fields(text_f: str, message: str | None = None) -> list[tuple[int, str]]:
    """
    Fields whose name the text mentions. Every word of the name must be there: short words ("za", "nad", "pod",
    "przy") as whole words, longer ones by their stem (any inflection). A one-word name that is also an ordinary
    word ("Długie", "Klin", "Górka") counts only right after "pole / polu / na / z / o …" or written with a capital
    letter inside the sentence: "Długie deszcze…" is about rain, "na Górce" and "pole Długie" are fields.
    """
    from core.models import Field
    hits = []
    # folded words, each with: written with a capital letter inside a sentence (not after . ! ? or at the start)
    if message:
        words, capital, start = [], [], True
        for token in message.split():
            for k, w in enumerate(domain.fold(token).split()):
                words.append(w)
                capital.append(k == 0 and not start and token.lstrip("„\"'(")[:1].isupper())
            if domain.fold(token):
                start = token.rstrip("”\"')").endswith((".", "!", "?", ":"))
    else:
        words = text_f.split()
        capital = [False] * len(words)
    for fid, name in Field.objects.values_list("id", "name"):
        nw = [w for w in domain.fold(name).split() if w not in NAME_SKIP]
        if not nw:
            continue
        positions = []
        for w in nw:
            if len(w) <= 3:
                pos = [i for i, t in enumerate(words) if t == w]
            else:
                st = _name_stem(w)
                pos = [i for i, t in enumerate(words) if t.startswith(st) and len(t) <= len(w) + 3]
            positions.append(pos)
        if not all(positions):
            continue
        if len(nw) == 1:
            ok = False
            for i in positions[0]:
                if (i > 0 and words[i - 1] in FIELD_CONTEXT_WORDS) or capital[i]:
                    ok = True
                    break
            if not ok:
                continue
        hits.append((fid, name))
    return hits


def route(message: str, selected_field=None, state=None) -> Route:
    t = domain.fold(message)
    agent = os.getenv("ASSISTANT_AGENT_MODE", "0") == "1"
    named = find_fields(t, message)
    crop = next((v for k, v in CROP_WORDS.items() if k in t), None)
    crop_code = {"pszenica": 1110, "kukurydza": 1130}.get(crop or "")
    if crop_code is None and len(named) == 1:
        from core.models import Field
        crop_code = Field.objects.filter(pk=named[0][0]).values_list("crop_id", flat=True).first()
    if crop_code is None and selected_field is not None:
        crop_code = selected_field.crop_id
    if crop is None and crop_code:
        crop = domain.CROP_PL.get(crop_code)  # None for crops without guides (A-28a)
    matches = domain.resolve_threats(message, crop_code)
    threats = [m.code for m in matches]
    if crop is None and matches:  # "septorioza paskowana" alone -> wheat
        crop_code = crop_code or matches[0].crop_code
        crop = domain.CROP_PL.get(crop_code)  # None for crops without guides (A-28a)
    field_id, field_source = None, ""
    if len(named) == 1:
        field_id, field_source = named[0][0], "named"
    elif selected_field is not None:
        field_id, field_source = selected_field.id, "selected"
    elif state is not None and state.data.get("last_field_id") and not named and not NOT_FOLLOW_UP.search(t) and (
            _any(RISK_INTENT, t) or (len(t.split()) <= FOLLOW_UP_MAX_WORDS and _any(FOLLOW_UP, t)) or _any(CHART, t)):
        # a follow-up ("co mogę zrobić?", "a dlaczego?") continues with the field of the previous answer
        from core.models import Field
        last = Field.objects.filter(pk=state.data["last_field_id"]).first()
        if last is not None:
            field_id, field_source = last.id, "conversation"
            if crop is None:
                crop = domain.CROP_PL.get(last.crop_id)
                if not threats:
                    threats = [m.code for m in domain.resolve_threats(message, last.crop_id)]
    base = dict(field_id=field_id, field_ids=[f for f, _ in named], crop=crop, threats=threats,
                field_source=field_source)

    # 1. pending observation draft: only a short yes/no confirms; "tak, ale to było na polu Klin" or
    # "nie, to było wczoraj" corrects the draft; "Zapisz obserwację: na Górce widzę mszyce" is a new report
    if state is not None and state.draft:
        words = t.split()
        first = words[0] if words else ""
        # a confirmation says only yes/no (any length: "Tak, zapisz tę obserwację, proszę"); "Nie widzę objawów"
        # starts with "nie" but is a new report, not a cancel
        if t in CONFIRM_YES or (first in {"tak", "zapisz", "potwierdzam", "ok", "okej"} and set(words) <= CONFIRM_FILLER):
            return Route("potwierdzenie", reason="draft pending + yes", **base)
        if t in CONFIRM_NO or (first in {"nie", "anuluj"} and set(words) <= CANCEL_FILLER):
            return Route("potwierdzenie", reason="draft pending + no", **base)
        if first in {"tak", "nie"} and not state.draft.get("saved_observation_id") and not (
                _any(OBSERVATION, t) or _any(ABSENCE, t)):  # "nie, to było wczoraj": a correction of the draft
            return Route("obserwacja", reason="draft pending + correction", previous_draft=dict(state.draft), **base)
    # 2. chart
    if p := _any(CHART, t):
        return Route("wykres", reason=f"chart word {p}", **base)
    # 3. observation (a question to the assistant, "czy pryskałeś?", is not a report)
    asked = message.strip().endswith("?") and QUESTION_TO_ASSISTANT.search(t)
    if not asked and (p := _any(OBSERVATION, t) or _any(ABSENCE, t)):
        return Route("obserwacja", reason=f"observation word {p}", **base)
    if not message.strip().endswith("?") and (p := _any(OBSERVATION_STATEMENT, t)):
        return Route("obserwacja", reason=f"observation statement {p}", **base)
    # 4. farm overview
    complex_q = len(named) >= 2 or (len(threats) >= 2 and _any(COMPARE, t)) or bool(_any(DATE_RANGE, t))
    if agent and complex_q:
        return Route("zlozone", reason="complex question (agent mode)", **base)
    if p := (_any(FARM, t) or (len(named) >= 2 and "compare")
             or (field_id is None and _any(FARM_IF_NO_FIELD, t))
             or (field_id is None and not _any(FIELD_REF, t) and _any(FARM_NO_FIELD, t))):
        return Route("podsumowanie_farmy", reason=f"farm word {p}", **base)
    # 5. question about a field
    field_ref = field_id is not None or bool(_any(FIELD_REF, t))
    if field_ref and (p := _any(RISK_INTENT, t)):
        return Route("pytanie_o_pole", reason=f"field ref ({field_source or 'phrase'}) + intent {p}", **base)
    # 6. out of scope: thanks, unrelated topics, bare greetings, and (with no field in context) anything without
    # a single farming word ("Jaka jest stolica Francji?") get a fixed answer, without the LLM
    if THANKS.match(t):
        return Route("poza_zakresem", reason="thanks", **base)
    if _any(OFF_TOPIC, t) or GREETING_ONLY.match(t) or t in CONFIRM_YES or t in CONFIRM_NO:
        return Route("poza_zakresem", reason="off-topic, greeting or a bare yes/no", **base)
    if field_id is None and not named and not threats and not crop and len(t.split()) >= 3 and not _any(AGRO, t):
        return Route("poza_zakresem", reason="no farming word", **base)
    # 7. anything else goes to the model: with the field's data when a field is in context
    if field_id is not None:
        return Route("pytanie_o_pole", reason=f"open question, field in context ({field_source})", **base)
    return Route("pytanie_ogolne", reason="default", **base)
