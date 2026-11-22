"""Orchestrator tests: router, guard, citations, prompt budget, flows and answer() on FakeLLM.

No real LLM and no Qdrant: guide search is replaced by fixed passages."""
from __future__ import annotations

import datetime as dt
import json
from unittest import mock

from django.test import SimpleTestCase, TestCase

from assistant import devdata
from assistant.answer import Reply, answer
from assistant.models import Conversation, Message
from core.models import Observation
from assistant.orchestrator import citations, guard, prompts, router
from assistant.orchestrator.llm import FakeLLM, LLMError
from assistant.orchestrator.state import State

TODAY = dt.date(2024, 5, 15)
CIT = {"type": "guide", "document": "metodyka_-_PSZENICA_-_www.pdf", "page": 79, "printed_page": 77, "section": "5.1"}
SOURCES = [
    {"chunk_id": "pszenica_doradcy:5.1:0018", "citation_text": "Metodyka … (doradcy), s. 77", "section": "5.1",
     "kind": "table", "text": "| Septorioza paskowana liści pszenicy | owalne plamy z piknidiami |", "citation": CIT},
    {"chunk_id": "pszenica_producenci:IV.2:0001", "citation_text": "Metodyka … (producenci), s. 31", "section": "IV.2",
     "kind": "table", "text": "| Septorioza | niszczenie resztek pożniwnych, płodozmian |",
     "citation": CIT | {"document": "pszenicy_ozimej_i_jarej__DLA_PRODUCENTOW.pdf", "page": 33}},
]


def fake_sources(queries, budget=2000, max_n=5, exclude=None):
    return list(SOURCES), None


class WorldTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = devdata.build(start=dt.date(2024, 4, 20), end=dt.date(2024, 5, 31), today=TODAY)
        cls.f = {f.name: f for f in cls.world.fields}
        cls.wheat = cls.f["Pole Północne"]
        cls.maize = cls.f["Kukurydza Zachód"]

    def setUp(self):
        p = mock.patch("assistant.orchestrator.context.guide_sources", side_effect=fake_sources)
        p.start()
        self.addCleanup(p.stop)

    def conv(self, *messages):
        c = Conversation.objects.create(title="t")
        for role, text in messages:
            Message.objects.create(conversation=c, role=role, text=text)
        return c


# ----------------------------------------------------------------------------- router
class RouterTests(WorldTestCase):
    CASES = [
        # (message, selected field name or None, expected type)
        ("W jakich warunkach rozwija się septorioza paskowana?", None, "pytanie_ogolne"),
        ("Jaki jest próg szkodliwości mszyc w pszenicy?", None, "pytanie_ogolne"),
        ("Jakie są objawy rdzy brunatnej?", None, "pytanie_ogolne"),
        ("Kiedy siać kukurydzę?", None, "pytanie_ogolne"),
        ("Jakie metody niechemiczne ograniczają fuzariozę kłosów?", None, "pytanie_ogolne"),
        ("Co to jest faza BBCH 31?", None, "pytanie_ogolne"),
        ("Jaki przedplon jest dobry dla pszenicy ozimej?", None, "pytanie_ogolne"),
        ("Ile litrów herbicydu na hektar zastosować w kukurydzy?", None, "pytanie_ogolne"),
        ("Jaka dawka fungicydu na septoriozę?", None, "pytanie_ogolne"),
        ("Jak rozpoznać omacnicę prosowiankę?", None, "pytanie_ogolne"),
        ("Dlaczego to pole jest zagrożone?", "Pole Północne", "pytanie_o_pole"),
        ("Co mam teraz zrobić na tym polu?", "Pole Północne", "pytanie_o_pole"),
        ("Czy na Polu Długim grozi septorioza?", None, "pytanie_o_pole"),
        ("Jakie jest ryzyko na polu Kukurydza Zachód?", None, "pytanie_o_pole"),
        ("Dlaczego ryzyko rośnie?", "Kukurydza Zachód", "pytanie_o_pole"),
        ("Jaki jest stan mojego pola?", "Pole przy Lesie", "pytanie_o_pole"),
        ("Czy muszę coś robić z polem przy lesie?", None, "pytanie_o_pole"),
        ("Co się dzieje na tym polu?", "Pole Długie", "pytanie_o_pole"),
        ("Pokaż wykres ryzyka septoriozy", "Pole Północne", "wykres"),
        ("Jak się zmieniało ryzyko rdzy przez ostatnie dwa tygodnie?", "Pole Północne", "wykres"),
        ("Pokaż opady i ryzyko na tym polu", "Pole przy Lesie", "wykres"),
        ("Narysuj trend ryzyka dla Kukurydzy Wschód", None, "wykres"),
        ("Pokaż mi przebieg temperatury", "Pole Północne", "wykres"),
        ("Widzę brunatne plamy z czarnymi kropkami na liściach", "Pole Północne", "obserwacja"),
        ("Zauważyłem dużo mszyc na kukurydzy", "Kukurydza Zachód", "obserwacja"),
        ("Pojawiły się gąsienice w łodygach", None, "obserwacja"),
        ("Znalazłam biały nalot na liściach pszenicy", None, "obserwacja"),
        ("Zapisz obserwację: grad uszkodził liście", "Pole Długie", "obserwacja"),
        ("Na polu są żółte paski na liściach", "Pole Północne", "obserwacja"),
        ("Które pole jest najpilniejsze?", None, "podsumowanie_farmy"),
        ("Co jest najpilniejsze w gospodarstwie?", None, "podsumowanie_farmy"),
        ("Podsumuj ryzyko na wszystkich polach", None, "podsumowanie_farmy"),
        ("Na którym polu jest najgorzej?", None, "podsumowanie_farmy"),
        ("Porównaj Pole Północne i Pole Długie", None, "podsumowanie_farmy"),
        ("Napisz wiersz o kotach", None, "poza_zakresem"),
        ("Kto wygrał mecz wczoraj?", None, "poza_zakresem"),
        ("Opowiedz mi dowcip", None, "poza_zakresem"),
        ("Jaki jest kurs bitcoina?", None, "poza_zakresem"),
        ("Cześć", None, "poza_zakresem"),
        ("Podaj przepis na sernik", None, "poza_zakresem"),
    ]

    def test_forty_messages(self):
        self.assertEqual(len(self.CASES), 40)
        wrong = []
        for msg, sel, expected in self.CASES:
            r = router.route(msg, self.f.get(sel) if sel else None, State(None))
            if r.type != expected:
                wrong.append((msg, expected, r.type, r.reason))
        self.assertEqual(wrong, [])

    def test_farm_report_without_a_field(self):
        cases = [
            ("Daj mi raport ryzyk na moich polach", None, "podsumowanie_farmy"),
            ("Jakie są ryzyka na moich polach?", None, "podsumowanie_farmy"),
            ("raport ryzyk", None, "podsumowanie_farmy"),
            ("raport ryzyk", "Pole Północne", "pytanie_o_pole"),           # a selected field: its own report
            ("Jak zwalczać septoriozę na polach pszenicy?", None, "pytanie_ogolne"),
        ]
        got = [(m, router.route(m, self.f.get(sel) if sel else None, State(None)).type) for m, sel, _ in cases]
        self.assertEqual(got, [(m, e) for m, _, e in cases])

    def test_detects_field_crop_threat(self):
        r = router.route("Czy na Polu Długim grozi septorioza?", None, State(None))
        self.assertEqual(r.field_id, self.f["Pole Długie"].id)
        self.assertEqual(r.crop, "pszenica")
        self.assertEqual(r.threats[0], "wheat.septoria_leaf_blotch")

    def test_confirmation_only_with_pending_draft(self):
        s = State(None)
        self.assertEqual(router.route("tak", None, s).type, "poza_zakresem")
        s.set_draft({"draft_id": "x"})
        self.assertEqual(router.route("tak", None, s).type, "potwierdzenie")
        self.assertEqual(router.route("Nie, anuluj", None, s).type, "potwierdzenie")


# ----------------------------------------------------------------------------- guard
class GuardTests(SimpleTestCase):
    POSITIVE = [
        "Zastosuj herbicyd w dawce 1,5 l/ha.",
        "Fungicyd stosuje się w dawce 0,8–1,0 l/ha po wykłoszeniu.",
        "Insektycyd: 200 ml/ha przy przekroczeniu progu.",
        "Środek należy użyć w ilości 50 g/ha.",
        "Zaprawa nasienna 2 l/100 l wody.",
        "Preparat X w dawce 3–4 l/ha działa najlepiej.",
        "Substancja czynna w ilości 120 g/ha ogranicza chorobę.",
        "Wykonaj oprysk dawką 1 l/ha.",
        "Dawka herbicydu to 480-600 g/ha.",
        "Polecam środek ochrony roślin 0,5 kg/ha.",
    ]
    NEGATIVE = [
        "Nawożenie azotem: 120 kg N/ha w dwóch dawkach.",
        "Zastosuj 60 kg/ha P2O5 przed siewem.",
        "Potas: 80 kg/ha K2O jesienią.",
        "Wysiew 180 kg/ha nasion pszenicy.",
        "Norma wysiewu 200 kg/ha ziarna.",
        "Dobór środka i dawki według aktualnej etykiety, skonsultuj z doradcą.",
        "Próg szkodliwości: 5 mszyc na źdźble.",
        "Ciecz użytkowa 200 l/ha — oprysk wykonuj przy słabym wietrze.",
        "Plon wyniósł 8 t/ha.",
        "Średnia temperatura 12 °C sprzyja septoriozie.",
    ]

    def test_positive(self):
        self.assertEqual([s for s in self.POSITIVE if guard.check(s)], [])

    def test_negative(self):
        self.assertEqual([s for s in self.NEGATIVE if not guard.check(s)], [])


# ----------------------------------------------------------------------------- citations / prompt
class CitationTests(SimpleTestCase):
    def test_known_numbered_unknown_removed_plain_brackets_kept(self):
        allowed = {"pszenica_doradcy:5.1:0018": CIT, "ryzyka_zebrane:pszenica.r019": {"type": "guide", "document": "ryzyka_zebrane.xlsx"}}
        text = ("Septorioza lubi wilgoć [ryzyka_zebrane:pszenica.r019]. Objawy to plamy [pszenica_doradcy:5.1:0018]. "
                "Zmyślony cytat [kukurydza_doradcy:VI:0009]. Oba [pszenica_doradcy:5.1:0018, ryzyka_zebrane:pszenica.r019]. "
                "Skala [1–9] zostaje.")
        out, cits, unknown = citations.finalize(text, allowed)
        self.assertIn("wilgoć [1].", out)
        self.assertIn("plamy [2].", out)
        self.assertIn("Zmyślony cytat.", out)
        self.assertIn("Oba [1, 2]", out)
        self.assertIn("[1–9]", out)
        self.assertEqual(unknown, ["kukurydza_doradcy:VI:0009"])
        self.assertEqual([c["ref"] for c in cits], [1, 2])
        self.assertEqual(cits[1]["document"], "metodyka_-_PSZENICA_-_www.pdf")


class PromptBudgetTests(SimpleTestCase):
    def test_trims_sources_then_history(self):
        big = [dict(SOURCES[0], chunk_id=f"pszenica_doradcy:5.1:{i:04d}", text="tekst " * 400) for i in range(6)]
        hist = [{"role": "user", "text": "pytanie " * 50}, {"role": "assistant", "text": "odpowiedź " * 50}]
        msgs, info = prompts.build_messages(["Data sezonu: 2024-05-15"], big, hist, "Pytanie?", budget=2500)
        self.assertLessEqual(info["estimated_input_tokens"], 2500)
        self.assertTrue(info["dropped_sources"])
        self.assertEqual(info["dropped_sources"][0], "pszenica_doradcy:5.1:0005")  # weakest (last) first


# ----------------------------------------------------------------------------- answer()
def cite_first(messages, json_mode):
    import re
    ids = re.findall(r"^\[([a-z_]+:[^\]\s]+)\]", messages[-1]["content"], re.M)
    return f"Według metodyki to ważne [{ids[0]}]. Wymyślony [pszenica_doradcy:9.9:0001]." if ids else "Brak źródeł."


class AnswerTests(WorldTestCase):
    def test_general_question_one_llm_call_with_citations(self):
        llm = FakeLLM(cite_first)
        c = self.conv(("user", "W jakich warunkach rozwija się septorioza paskowana?"))
        r = answer(c, "W jakich warunkach rozwija się septorioza paskowana?", None, llm=llm)
        self.assertIsInstance(r, Reply)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("[1]", r.text)
        self.assertNotIn("pszenica_doradcy:9.9:0001", r.text)
        self.assertEqual(r.meta["route"], "pytanie_ogolne")
        self.assertEqual(r.meta["removed_citations"], ["pszenica_doradcy:9.9:0001"])
        self.assertTrue(any(ci["type"] == "guide" and ci["ref"] == 1 for ci in r.citations))

    def test_field_question_uses_engine_and_risk_citations(self):
        llm = FakeLLM(cite_first)
        c = self.conv(("user", "Dlaczego to pole jest zagrożone?"))
        r = answer(c, "Dlaczego to pole jest zagrożone?", self.wheat, llm=llm)
        prompt = llm.calls[0]["messages"][-1]["content"]
        self.assertIn("powody (silnik)", prompt)
        self.assertIn("Pole Północne", prompt)
        self.assertEqual(len(llm.calls), 1)
        self.assertTrue(any(ci["type"] == "risk" and ci["field_id"] == self.wheat.id for ci in r.citations))
        self.assertIsNone(r.focus_field_id)  # the field was selected already

    def test_field_question_without_selection_picks_highest_risk_and_focuses(self):
        r = answer(self.conv(), "Dlaczego to pole jest zagrożone?", None, llm=FakeLLM(cite_first))
        self.assertIsNotNone(r.focus_field_id)
        self.assertEqual(r.meta["field_choice"], "highest_risk")

    def test_dose_regenerated_then_safe_message(self):
        llm = FakeLLM(["Zastosuj fungicyd 1 l/ha [pszenica_doradcy:5.1:0018].", "Dobór środka według etykiety."])
        r = answer(self.conv(), "Jak zwalczać septoriozę?", None, llm=llm)
        self.assertEqual(len(llm.calls), 2)
        self.assertNotIn("l/ha", r.text)
        llm = FakeLLM("Herbicyd 2 l/ha.")
        r = answer(self.conv(), "Ile litrów herbicydu na hektar?", None, llm=llm)
        self.assertEqual(r.text.split("\n")[0], guard.SAFE_MESSAGE)

    def test_dose_question_always_refers_to_label(self):
        r = answer(self.conv(), "Ile litrów herbicydu na hektar zastosować w kukurydzy?", None,
                   llm=FakeLLM("Zwalczanie chwastów zależy od fazy."))
        self.assertIn("etykiety", r.text)

    def test_chart_flow(self):
        llm = FakeLLM("Ryzyko było najwyższe 19 maja.")
        r = answer(self.conv(), "Pokaż wykres ryzyka septoriozy", self.wheat, llm=llm)
        self.assertEqual(r.meta["route"], "wykres")
        self.assertIsNotNone(r.chart)
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("Podsumowanie wykresu", llm.calls[0]["messages"][-1]["content"])

    def test_farm_summary(self):
        llm = FakeLLM("Najpierw Pole Długie.")
        r = answer(self.conv(), "Które pole jest najpilniejsze?", None, llm=llm)
        self.assertEqual(r.meta["route"], "podsumowanie_farmy")
        self.assertEqual(len(llm.calls), 1)
        self.assertTrue(r.citations)

    def test_out_of_scope_no_llm(self):
        llm = FakeLLM("x")
        r = answer(self.conv(), "Napisz wiersz o kotach", None, llm=llm)
        self.assertEqual(llm.calls, [])
        self.assertIn("pszenicy i kukurydzy", r.text)

    def test_llm_error_and_crash_become_polish_messages(self):
        class Down:
            def complete(self, *a, **k):
                raise LLMError("limit")
        r = answer(self.conv(), "Jakie są objawy rdzy brunatnej?", None, llm=Down())
        self.assertTrue(r.text.startswith("Nie mogę teraz odpowiedzieć"))
        with mock.patch("assistant.orchestrator.router.route", side_effect=RuntimeError("boom")):
            r = answer(self.conv(), "cokolwiek", None, llm=FakeLLM("x"))
        self.assertIn("błąd", r.text)


# ----------------------------------------------------------------------------- observations
class ObservationFlowTests(WorldTestCase):
    def _llm(self, **draft):
        base = {"field_id": None, "date": None, "category": "choroba", "threat": None, "severity": None,
                "note": "brunatne plamy z czarnymi kropkami", "missing": []}
        return FakeLLM(json.dumps(base | draft, ensure_ascii=False))

    def test_draft_confirm_save_and_no_duplicate(self):
        c = self.conv()
        msg = "Widzę brunatne plamy z czarnymi kropkami na dolnych liściach"
        r = answer(c, msg, self.wheat, llm=self._llm())
        self.assertEqual(r.meta["route"], "obserwacja")
        self.assertIn("Zapisać tę obserwację?", r.text)
        self.assertEqual(r.pending_action["draft"]["threat_code"], "wheat.septoria_leaf_blotch")
        self.assertEqual(r.pending_action["draft"]["date"], "2024-05-15")
        self.assertEqual(Observation.objects.count(), 0)
        c.refresh_from_db()
        r = answer(c, "tak", self.wheat, llm=FakeLLM("x"))
        self.assertIn("Zapisałem obserwację", r.text)
        self.assertEqual(Observation.objects.count(), 1)
        c.refresh_from_db()
        r = answer(c, "tak", self.wheat, llm=FakeLLM("x"))
        self.assertIn("już zapisana", r.text)
        self.assertEqual(Observation.objects.count(), 1)

    def test_yesterday_and_reassessment_with_engine(self):
        c = self.conv()
        answer(c, "Wczoraj zauważyłem mszyce na kukurydzy", self.maize, llm=self._llm(category="szkodnik"))
        c.refresh_from_db()
        self.assertEqual(State(c).draft["date"], "2024-05-14")
        with mock.patch("assistant.tools.observations.engine_predict", return_value=lambda **kw: 3):
            r = answer(c, "zapisz", self.maize, llm=FakeLLM("x"))
        self.assertEqual(r.updated_field_ids, [self.maize.id])

    def test_cancel_and_missing_field(self):
        c = self.conv()
        answer(c, "Widzę plamy na liściach", self.wheat, llm=self._llm())
        c.refresh_from_db()
        r = answer(c, "nie", self.wheat, llm=FakeLLM("x"))
        self.assertIn("nie zapisuję", r.text)
        r = answer(self.conv(), "Widzę plamy na liściach", None, llm=self._llm())
        self.assertIn("którego pola", r.text)

    def test_model_cannot_pick_unknown_field(self):
        r = answer(self.conv(), "Widzę plamy na liściach", None, llm=self._llm(field_id=987654))
        self.assertIn("którego pola", r.text)


# ----------------------------------------------------------------------------- endpoint
class MessageJsonTests(SimpleTestCase):
    def test_chart_and_pending_action_come_from_meta(self):
        from assistant.views import message_json
        when = dt.datetime(2024, 5, 15, 12, 0, tzinfo=dt.timezone.utc)
        draft = {"type": "confirm_observation", "draft": {"draft_id": "abc", "field_id": 3}}
        m = Message(role=Message.Role.ASSISTANT, text="x", citations=[], created_at=when,
                    meta={"chart": {"mark": "line"}, "pending_action": draft, "updated_field_ids": [3]})
        out = message_json(m)
        self.assertEqual((out["chart"], out["pending_action"], out["updated_field_ids"]), ({"mark": "line"}, draft, [3]))
        self.assertEqual(out["created_at"], "2024-05-15T12:00:00Z")
        user = message_json(Message(role=Message.Role.USER, text="y", citations=[], created_at=when, meta={}))
        self.assertEqual((user["chart"], user["pending_action"], user["citations"]), (None, None, []))


class ChatEndpointTests(WorldTestCase):
    def test_post_chat_contract_shape_and_history(self):
        with mock.patch("assistant.answer.default_llm", return_value=FakeLLM(cite_first)):
            resp = self.client.post("/api/chat/", {"conversation_id": None, "message": "Dlaczego to pole jest zagrożone?",
                                                   "field_id": self.wheat.id}, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body), {"conversation_id", "message"})
        self.assertEqual(set(body["message"]), {"id", "role", "text", "citations", "focus_field_id",
                                                "updated_field_ids", "chart", "pending_action", "created_at"})
        self.assertEqual(body["message"]["role"], "assistant")
        self.assertEqual((body["message"]["chart"], body["message"]["pending_action"]), (None, None))
        conv = self.client.get(f"/api/chat/conversations/{body['conversation_id']}/").json()
        self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant"])
        self.assertEqual(conv["messages"][0]["citations"], [])
        self.assertEqual(self.client.get("/api/chat/conversations/").json()[0]["id"], body["conversation_id"])

    def test_chart_is_sent_and_kept_in_history(self):
        with mock.patch("assistant.answer.default_llm", return_value=FakeLLM("Ryzyko rośnie.")):
            body = self.client.post("/api/chat/", {"message": "Pokaż wykres ryzyka septoriozy", "field_id": self.wheat.id},
                                    content_type="application/json").json()
        chart = body["message"]["chart"]
        self.assertEqual(chart["$schema"], "https://vega.github.io/schema/vega-lite/v5.json")
        self.assertIsNone(body["message"]["pending_action"])
        conv = self.client.get(f"/api/chat/conversations/{body['conversation_id']}/").json()
        user, reply = conv["messages"]
        self.assertEqual((user["chart"], user["pending_action"]), (None, None))
        self.assertEqual(reply["chart"], chart)

    def test_zapisz_button_message_saves_the_draft(self):
        draft = {"field_id": None, "date": None, "category": "choroba", "threat": None, "severity": None,
                 "note": "brunatne plamy z czarnymi kropkami", "missing": []}
        with mock.patch("assistant.answer.default_llm", return_value=FakeLLM(json.dumps(draft, ensure_ascii=False))):
            body = self.client.post("/api/chat/", {"message": "Widzę brunatne plamy z czarnymi kropkami na liściach",
                                                   "field_id": self.wheat.id}, content_type="application/json").json()
        action = body["message"]["pending_action"]
        self.assertEqual(action["type"], "confirm_observation")
        self.assertEqual(action["draft"]["field_id"], self.wheat.id)
        self.assertTrue(action["draft"]["draft_id"])
        self.assertIsNone(body["message"]["chart"])
        # the chat window's "Zapisz" button sends exactly this message
        with mock.patch("assistant.tools.observations.engine_predict", return_value=lambda **kw: 3):
            saved = self.client.post("/api/chat/", {"conversation_id": body["conversation_id"], "message": "Zapisz",
                                                    "field_id": action["draft"]["field_id"]},
                                     content_type="application/json").json()
        self.assertIn("Zapisałem obserwację", saved["message"]["text"])
        self.assertIsNone(saved["message"]["pending_action"])
        self.assertEqual(Observation.objects.count(), 1)

    def test_bad_input(self):
        self.assertEqual(self.client.post("/api/chat/", {"message": "x", "field_id": 999999},
                                          content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/api/chat/", {"message": ""}, content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/api/chat/", {"message": "x", "conversation_id": 999999},
                                          content_type="application/json").status_code, 404)

    def test_observation_draft_reaches_the_api_as_pending_action(self):
        draft = {"field_id": None, "date": None, "category": "choroba", "threat": None, "severity": None,
                 "note": "brunatne plamy z czarnymi kropkami", "missing": []}
        with mock.patch("assistant.answer.default_llm", return_value=FakeLLM(json.dumps(draft, ensure_ascii=False))):
            body = self.client.post("/api/chat/", {"message": "Widzę plamy na liściach", "field_id": self.wheat.id},
                                    content_type="application/json").json()
        action = body["message"]["pending_action"]
        self.assertEqual((action["type"], action["draft"]["field_id"]), ("confirm_observation", self.wheat.id))
        conv = self.client.get(f"/api/chat/conversations/{body['conversation_id']}/").json()
        self.assertEqual(conv["messages"][-1]["pending_action"]["type"], "confirm_observation")
        self.assertIsNone(conv["messages"][0]["pending_action"])


class ReportKindTests(SimpleTestCase):
    def test_kinds_and_facts(self):
        from assistant.orchestrator.observations import detect_kind
        today = dt.date(2025, 6, 10)
        self.assertEqual(detect_kind("Wczoraj był grad", today), ("event", {"type": "hail"}))
        self.assertEqual(detect_kind("Siałem 8 października", today), ("field_fact", {"sowing_date": "2024-10-08"}))
        self.assertEqual(detect_kind("Na tym polu nie orałem", today), ("field_fact", {"tillage": "reduced"}))
        self.assertEqual(detect_kind("Opryskałem w piątek na septoriozę", today)[0], "treatment")
        self.assertEqual(detect_kind("Sąsiad za drogą ma fuzariozę", today), ("neighbour", {"distance_m": 300}))
        self.assertEqual(detect_kind("Przeszedłem pole, jest czyste", today)[0], "absence")
        self.assertEqual(detect_kind("Widzę rdzawe plamy", today)[0], "symptoms")


class FollowUpTests(WorldTestCase):
    def test_follow_up_keeps_field_of_previous_answer(self):
        c = self.conv()
        r1 = answer(c, "Jakie jest ryzyko na polu Długie?", None, llm=FakeLLM(cite_first))
        self.assertEqual(r1.meta["route"], "pytanie_o_pole")
        c.refresh_from_db()
        r2 = answer(c, "co mogę zrobić żeby zmniejszyć ryzyko?", None, llm=FakeLLM(cite_first))
        self.assertEqual(r2.meta["route"], "pytanie_o_pole")
        self.assertEqual(r2.meta["field_id"], self.f["Pole Długie"].id)
        self.assertEqual(r2.meta["field_choice"], "conversation")


class EmptyReasoningAnswerTests(SimpleTestCase):
    def test_retry_when_reasoning_used_the_whole_budget(self):
        from types import SimpleNamespace as NS
        from assistant.orchestrator.llm import OpenAICompatLLM
        calls = []

        def create(**kw):
            calls.append(kw)
            empty = len(calls) == 1
            msg = NS(content="" if empty else "Odpowiedź.", tool_calls=None)
            return NS(choices=[NS(message=msg, finish_reason="length" if empty else "stop")],
                      usage=NS(prompt_tokens=10, completion_tokens=700, total_tokens=710))
        llm = OpenAICompatLLM("groq", "https://example.test/v1", "k", "openai/gpt-oss-120b")
        llm.client = NS(chat=NS(completions=NS(create=create)))
        r = llm.complete([{"role": "user", "content": "x"}])
        self.assertEqual(r.text, "Odpowiedź.")
        self.assertEqual([c["max_tokens"] for c in calls], [1500, 3000])
        self.assertEqual(calls[0]["reasoning_effort"], "low")


class EngineAlignmentTests(WorldTestCase):
    def test_level_comes_from_the_engine_explanation(self):
        from assistant import domain
        self.assertEqual(domain.level_from_explanation({"level": "high"}, 0.4), (3, "wysokie"))
        self.assertEqual(domain.level_from_explanation({}, 0.4), (2, "średnie"))
        self.assertEqual(domain.level(0.32)[1], "niskie")   # same cut-offs as engine/scoring.py and the map
        self.assertEqual(domain.level(0.65)[1], "średnie")
        self.assertEqual(domain.level(0.66)[1], "wysokie")

    def _draft(self, msg, category):
        llm = FakeLLM(json.dumps({"category": category, "note": msg}, ensure_ascii=False))
        return answer(self.conv(), msg, self.wheat, llm=llm).pending_action["draft"]

    def test_report_kinds_the_engine_can_use(self):
        self.assertIsNone(self._draft("Widzę dużo chwastów przy miedzy", "chwasty")["kind"])
        d = self._draft("Opryskałem to pole 5 czerwca", None)
        self.assertEqual((d["kind"], d["category"]), ("treatment", "choroba"))
        d = self._draft("Sąsiad za drogą ma fuzariozę kłosów", None)
        self.assertEqual((d["kind"], d["category"], d["facts"]), ("neighbour", "choroba", {"distance_m": 300}))


class BroaderRoutingTests(WorldTestCase):
    def test_morning_questions_and_open_follow_ups(self):
        from assistant.orchestrator.router import route
        for q in ["od czego dziś zacząć?", "Co dziś robić na polach?", "Jak wygląda sytuacja na polach?",
                  "Gdzie dziś jechać najpierw?"]:
            self.assertEqual(route(q, None, State(None)).type, "podsumowanie_farmy", q)
        s = State(None)
        s.data["last_field_id"] = self.maize.id
        for q in ["Co mam tam dziś konkretnie zrobić?", "A na co mam uważać?", "Czy powinienem się martwić?"]:
            r = route(q, None, s)
            self.assertEqual((r.type, r.field_id), ("pytanie_o_pole", self.maize.id), q)
        self.assertEqual(route("Jaka jest stolica Francji?", None, State(None)).type, "poza_zakresem")  # no LLM call
        self.assertEqual(route("Cześć", None, State(None)).type, "poza_zakresem")

    def test_threat_sources_must_mention_the_threat(self):
        from assistant.orchestrator.context import mentions
        self.assertTrue(mentions("rdzy brunatnej sprzyja wilgoć", "rdza brunatna pszenicy"))
        self.assertFalse(mentions("larwy stonki kukurydzianej", "żółta plamistość liści kukurydzy"))


class InvisibleCharsCitationTests(SimpleTestCase):
    def test_zero_width_space_inside_brackets(self):
        out, cits, unknown = citations.finalize("Tekst\u202f[\u200bpszenica_doradcy:5.1:0018].", {"pszenica_doradcy:5.1:0018": CIT})
        self.assertEqual(out, "Tekst [1].")
        out, cits, unknown = citations.finalize("Zmyślone [\u200bkukurydza_producenci:IV.2:0004].", {})
        self.assertEqual((out, unknown), ("Zmyślone.", ["kukurydza_producenci:IV.2:0004"]))


class FullwidthBracketCitationTests(SimpleTestCase):
    def test_gpt_oss_fullwidth_brackets_glued_to_the_word(self):
        allowed = {"ryzyka_zebrane:pszenica.r019": {"type": "guide", "document": "ryzyka_zebrane.xlsx"}}
        out, cits, unknown = citations.finalize(
            "Plamy wzdłuż nerwów liści【ryzyka_zebrane:pszenica.r019】. Zmyślone【kukurydza_doradcy:VI:0009】. Skala [1–9].", allowed)
        self.assertEqual(out, "Plamy wzdłuż nerwów liści [1]. Zmyślone. Skala [1–9].")
        self.assertEqual([c["ref"] for c in cits], [1])
        self.assertEqual(unknown, ["kukurydza_doradcy:VI:0009"])


class FitForTodayTests(SimpleTestCase):
    TEXT = ("Objawy to owalne plamy z chlorotyczną obwódką. Próg szkodliwości: w fazie krzewienia 10–15% roślin "
            "z objawami. W fazie strzelania w źdźbło 5% liści z objawami. W fazie kłoszenia i kwitnienia 5% kłosów "
            "z objawami. Usuń i spal resztki roślin. W szklarni zapewnij wietrzenie.")

    def test_keeps_only_thresholds_of_todays_stage(self):
        from assistant.orchestrator.context import fit_for_today
        out = fit_for_today(self.TEXT, 70)
        self.assertIn("kłoszenia i kwitnienia 5%", out)
        self.assertNotIn("krzewienia", out)
        self.assertNotIn("strzelania", out)
        self.assertIn("owalne plamy", out)
        early = fit_for_today(self.TEXT, 25)
        self.assertIn("krzewienia 10–15%", early)
        self.assertNotIn("kłoszenia", early)

    def test_drops_greenhouse_and_burning_advice(self):
        from assistant.orchestrator.context import fit_for_today
        out = fit_for_today(self.TEXT, None)
        self.assertNotIn("spal", out)
        self.assertNotIn("szklarni", out)

    def test_field_sentences_about_air_and_inspectors_are_kept(self):
        from assistant.orchestrator.context import drop_off_field
        text = ("Wysoka wilgotność powietrza (85 %) sprzyja infekcji [1]. Temperatura powietrza 18 °C sprzyja rdzy. "
                "To rozsądny krok. Przy wietrznej pogodzie nie wykonuj zabiegu. Skontaktuj się z inspektorem PIORiN.")
        self.assertEqual(drop_off_field(text), text)

    def test_greenhouse_and_burning_sentences_are_dropped(self):
        from assistant.orchestrator.context import drop_off_field
        self.assertEqual(drop_off_field("Obejrzyj liście. Przewietrz tunel foliowy. Zadbaj o wietrzenie szklarni. "
                                        "Nie zalecam palenia resztek. Rośliny w doniczkach przenieś. Zrób lustrację."),
                         "Obejrzyj liście. Zrób lustrację.")

    def test_unfinished_answer_is_cut_to_the_last_sentence(self):
        from assistant.orchestrator.flows import finish_sentence
        self.assertEqual(finish_sentence("Pełne zdanie [1]. Drugie zdanie [2]. Metodyka zaleca, przyjmując pró"),
                         "Pełne zdanie [1]. Drugie zdanie [2].")
        self.assertEqual(finish_sentence("Całe zdanie."), "Całe zdanie.")
        self.assertEqual(finish_sentence("Bardzo długie zdanie bez końca"), "Bardzo długie zdanie bez końca")



class AnswerShapeTests(SimpleTestCase):
    def test_intent_of_the_question(self):
        from assistant.orchestrator.flows import question_intent
        self.assertEqual(question_intent("co mogę zrobić żeby zmniejszyć ryzyko?"), "action")
        self.assertEqual(question_intent("Dlaczego to pole jest na czerwono i co mam zrobić?"), "why_action")
        self.assertEqual(question_intent("Jak wyglądają objawy fuzariozy?"), "symptoms")
        self.assertEqual(question_intent("Skąd to wysokie ryzyko?"), "why")

    def test_engine_threshold_only_for_todays_stage(self):
        from assistant.orchestrator.context import threshold_for_stage
        thr = "Krzewienie: 10-15 % roślin z pierwszymi objawami; strzelanie w źdźbło: 5 % liści."
        self.assertEqual(threshold_for_stage(thr, 71), "")
        self.assertEqual(threshold_for_stage(thr, 22), "Krzewienie: 10-15 % roślin z pierwszymi objawami; strzelanie w źdźbło: 5 % liści")
        self.assertEqual(threshold_for_stage(thr, 45), "strzelanie w źdźbło: 5 % liści")
        self.assertIn("kwitnienia", threshold_for_stage("Infekcja w czasie kwitnienia (BBCH 61-69); zabieg zapobiegawczo", 71))

    def test_garden_advice_removed_from_the_answer(self):
        from assistant.orchestrator.context import drop_off_field
        self.assertEqual(drop_off_field("Obejrzyj kłosy [1]. Zapewnij dobrą cyrkulację powietrza. Zadzwoń do doradcy."),
                         "Obejrzyj kłosy [1]. Zadzwoń do doradcy.")
        md = "**Obejrzyj kłosy dziś.**\n\n- lustracja kłosów [1]\n- zapewnij cyrkulację powietrza\n- zadzwoń do doradcy"
        self.assertEqual(drop_off_field(md), "**Obejrzyj kłosy dziś.**\n\n- lustracja kłosów [1]\n- zadzwoń do doradcy")

    def test_markdown_survives_the_sentence_trim(self):
        from assistant.orchestrator.flows import finish_sentence
        md = "**Najpierw lustracja.**\n\n- obejrzyj kłosy [1].\n- zadzwoń do doradcy, gdy"
        self.assertEqual(finish_sentence(md), "**Najpierw lustracja.**\n\n- obejrzyj kłosy [1].")


    def test_nested_bold_is_flattened(self):
        from assistant.orchestrator.flows import fix_bold
        self.assertEqual(fix_bold("**Lustracja **Za Stodołą** pod kątem fuzariozy dziś**."),
                         "**Lustracja Za Stodołą pod kątem fuzariozy dziś**.")
        self.assertEqual(fix_bold("- **Za Stodołą**: wysokie, **Pod Lasem** średnie"),
                         "- **Za Stodołą**: wysokie, **Pod Lasem** średnie")


# ----------------------------------------------------------------------------- fixes from docs/audit-2026-11-21.md
class AuditFixTests(WorldTestCase):
    def test_air_humidity_sentences_are_not_greenhouse_advice(self):
        """A-1: "powietrza" contains "wietrz"; "rozsądnie", "inspektor" are not seedlings or cold frames."""
        from assistant.orchestrator.context import drop_off_field
        text = ("Wysoka wilgotność powietrza (85 %) sprzyja infekcji.\n- Temperatura powietrza 18 °C sprzyja rdzy [x:1].\n"
                "Rozsądnie jest zgłosić to inspektorowi PIORiN. W szklarni wietrz pomieszczenie.")
        out = drop_off_field(text)
        self.assertIn("wilgotność powietrza", out)
        self.assertIn("Temperatura powietrza", out)
        self.assertIn("inspektorowi", out)
        self.assertNotIn("szklarni", out)

    def test_wide_bracket_citations_and_engine_ids(self):
        """A-3: gpt-oss cites as 【id】; A-11: [silnik:code] marks engine facts and is removed from the text."""
        cit = {"type": "guide", "document": "x.pdf", "page": 3}
        text, cits, _ = citations.finalize("Plamy wzdłuż nerwów【pszenica_doradcy:5.1:0018】. Wynik 0,7 [silnik:wheat.tan_spot].",
                                           {"pszenica_doradcy:5.1:0018": cit})
        self.assertEqual(text, "Plamy wzdłuż nerwów [1]. Wynik 0,7.")
        self.assertEqual(cits, [cit | {"ref": 1}])

    def test_unclosed_bold_is_closed(self):
        from assistant.orchestrator.flows import fix_bold
        self.assertEqual(fix_bold("**Deszcze zwiększają ryzyko na polu."), "**Deszcze zwiększają ryzyko na polu.**")

    def test_threat_words_match_by_stem_not_by_similarity(self):
        """A-7: "ok" and "zboża" match nothing; inflected names match; a crop in the text narrows the threats."""
        from assistant import domain
        self.assertEqual(domain.resolve_threats("ok"), [])
        self.assertEqual(domain.resolve_threats("zboża"), [])
        self.assertEqual(domain.crop_in_text("Czy mszyce zagrażają kukurydzy?"), 1130)
        self.assertEqual(domain.crop_in_text("pszenżyto"), 1150)

    def test_field_names_need_context_when_they_are_ordinary_words(self):
        """A-8: "Długie deszcze" is rain; "na polu Długie" and "pole Długie" are the field."""
        from core.models import Field
        f = Field.objects.create(name="Długie", geometry=self.wheat.geometry, area_ha=5, centroid_lat=50.0, centroid_lon=19.9,
                                 weather_grid=self.wheat.weather_grid, h3_cells=[], crop=self.wheat.crop)
        g = Field.objects.create(name="Nad Stawem", geometry=self.wheat.geometry, area_ha=5, centroid_lat=50.0,
                                 centroid_lon=19.9, weather_grid=self.wheat.weather_grid, h3_cells=[], crop=self.wheat.crop)
        ids = lambda q: [i for i, _ in router.find_fields(router.domain.fold(q), q)]
        self.assertNotIn(f.id, ids("Długie deszcze ostatnio — czy to groźne?"))
        self.assertIn(f.id, ids("Na polu Długie widzę plamy"))
        self.assertIn(f.id, ids("Jak jest na Długim?"))
        self.assertNotIn(g.id, ids("Czy nadal warto stawiać na lustrację?"))
        self.assertIn(g.id, ids("Co słychać Nad Stawem?"))

    def test_only_a_short_yes_confirms_a_pending_draft(self):
        """A-10: "tak, ale to było wczoraj" corrects the draft; "tak" confirms; "nie" cancels."""
        s = State(self.conv())
        s.set_draft({"draft_id": "d1", "field_id": self.wheat.id, "field": self.wheat.name, "date": "2024-05-14",
                     "note": "plamy na liściach"})
        self.assertEqual(router.route("tak", None, s).type, "potwierdzenie")
        self.assertEqual(router.route("nie", None, s).type, "potwierdzenie")
        r = router.route("tak, ale to było wczoraj rano", None, s)
        self.assertEqual((r.type, r.reason), ("obserwacja", "draft pending + correction"))
        self.assertEqual(r.previous_draft["draft_id"], "d1")

    def test_questions_to_the_assistant_and_thanks(self):
        """A-21, A-22: "czy pryskałeś?" is not a report; thanks get a fixed answer."""
        self.assertNotEqual(router.route("Czy pryskałeś?", None, State(None)).type, "obserwacja")
        r = router.route("Dzięki, to wszystko", self.wheat, State(None))
        self.assertEqual((r.type, r.reason), ("poza_zakresem", "thanks"))
        self.assertNotIn("Jestem asystentem", answer(self.conv(), "Dziękuję bardzo", None, llm=FakeLLM("x")).text)

    def test_routed_threat_wins_over_the_models_guess(self):
        """A-9: the router's alias match decides the threat of the draft unless the model agrees with it."""
        from assistant.orchestrator.observations import observation
        from core.models import Threat
        codes = list(Threat.objects.filter(crop_id=self.maize.crop_id).values_list("code", "name")[:2])
        (routed, _), (_, other_name) = codes
        route_ = router.Route("obserwacja", field_id=self.maize.id, threats=[routed], crop="kukurydza")
        llm = FakeLLM(json.dumps({"field_id": self.maize.id, "category": "szkodnik", "threat": other_name,
                                  "severity": "srednie", "note": "x", "date": None}))
        res = observation(route_, "widzę coś na kukurydzy", [], llm, State(self.conv()), None)
        self.assertEqual(res.pending_action["draft"]["threat_code"], routed)

    def test_chat_without_an_llm_is_503_and_stores_nothing(self):
        before = Message.objects.count()
        with mock.patch("assistant.answer.default_llm", side_effect=LLMError("no keys")):
            resp = self.client.post("/api/chat/", {"message": "Dlaczego to pole jest zagrożone?"},
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 503)
        self.assertIn("Asystent jest wyłączony", resp.json()["detail"])
        self.assertEqual(Message.objects.count(), before)
        # a greeting needs no model: answered even without one
        with mock.patch("assistant.answer.default_llm", side_effect=LLMError("no keys")):
            self.assertEqual(self.client.post("/api/chat/", {"message": "Cześć"}, content_type="application/json").status_code, 200)

    def test_llm_failure_on_a_field_question_answers_from_the_engine(self):
        """A-17: the engine's own summary instead of an error."""
        class Down:
            def complete(self, *a, **k):
                raise LLMError("limit")
        r = answer(self.conv(), "Dlaczego to pole jest zagrożone?", self.wheat, llm=Down())
        self.assertTrue(r.text.startswith("Model językowy jest chwilowo niedostępny, więc podaję samą ocenę silnika"), r.text)
        self.assertTrue(r.meta.get("engine_only"))

    def test_health_reports_the_assistant(self):
        from assistant.status import assistant_status
        with mock.patch("assistant.status.rag_ready", return_value=True), \
                mock.patch("assistant.orchestrator.llm.provider_configs", return_value=[]):
            self.assertEqual(assistant_status()["available"], False)
        with mock.patch("assistant.status.rag_ready", return_value=True), \
                mock.patch.dict("os.environ", {"ASSISTANT_LLM": "fake"}):
            self.assertEqual(assistant_status(), {"available": True, "llm": True, "rag": True, "reason": None})


class AuditRound2Tests(WorldTestCase):
    """A-24, A-26, A-28 from docs/audit-2026-11-21.md."""

    def test_crop_risk_question_without_a_field_uses_the_farm(self):
        """A-24: "Co nadal grozi pszenicy?" gets the farm's wheat risks, not only the guides."""
        from assistant.orchestrator import flows
        llm = FakeLLM("Pszenica: ryzyko średnie.")
        route_ = router.route("Co nadal grozi pszenicy?", None, State(None))
        flows.general(route_, "Co nadal grozi pszenicy?", [], llm)
        prompt = llm.calls[0]["messages"][-1]["content"] if isinstance(llm.calls[0], dict) else str(llm.calls[0])
        self.assertIn("Najpilniejsze zagrożenia gospodarstwa", prompt)
        self.assertNotIn("Kukurydza", prompt.split("Najpilniejsze")[1].split("Wszystkie pola")[0])

    def test_weather_question_without_a_field_gets_a_fields_weather(self):
        """A-24: "Czy jutro będzie padać?" answers with the weather of the most endangered field."""
        from assistant.orchestrator import flows
        llm = FakeLLM("Jutro bez opadów.")
        res = flows.general(router.route("Czy jutro będzie padać?", None, State(None)), "Czy jutro będzie padać?", [], llm)
        prompt = str(llm.calls[0])
        self.assertIn("Pogoda dla pola", prompt)
        self.assertIsNotNone(res.meta.get("field_id"))

    def test_table_passages_count_only_rows_about_the_threat(self):
        """A-26: a table row that only mentions the threat under "możliwość pomylenia" is not about it."""
        from assistant.orchestrator.context import about
        table = ("| Choroba | Objawy | Możliwość pomylenia |\n|---|---|---|\n"
                 "| Rdza brunatna | pomarańczowe skupienia | brunatna plamistość liści |")
        self.assertFalse(about(table, "Choroby liści", "brunatna plamistość liści"))
        self.assertTrue(about(table, "Choroby liści", "rdza brunatna"))
        self.assertTrue(about("Brunatna plamistość liści rozwija się przy…", "", "brunatna plamistość liści"))

    def test_crops_without_guides_are_not_guessed(self):
        """A-28a: rapeseed has no guides here: no crop for the search, a note for the model."""
        r = router.route("Jak chronić rzepak przed suchą zgnilizną?", None, State(None))
        self.assertIsNone(r.crop)

    def test_dates_in_the_farmers_words(self):
        """A-28e: relative dates and the first day + month of a sentence; "położyłem pułapki" is not lodging."""
        from assistant.orchestrator.observations import _relative_date, detect_kind, parse_pl_date
        today = dt.date(2024, 5, 29)  # a Wednesday
        self.assertEqual(_relative_date("tydzień temu widziałem plamy", today), dt.date(2024, 5, 22))
        self.assertEqual(_relative_date("2 tygodnie temu", today), dt.date(2024, 5, 15))
        self.assertEqual(_relative_date("w poniedziałek opryskałem", today), dt.date(2024, 5, 27))
        from assistant import domain
        self.assertEqual(parse_pl_date(domain.fold("3 dni, 8 października"), today), dt.date(2023, 10, 8))
        self.assertNotEqual(detect_kind("położyłem pułapki feromonowe", today)[0], "event")
        self.assertEqual(detect_kind("położyło się zboże po burzy", today)[0], "event")

    def test_dates_in_the_context_are_polish(self):
        """A-28d: the context names the weekday and the month, so the answer can too."""
        from assistant.orchestrator.context import pl_day
        self.assertEqual(pl_day("2024-05-29"), "środa, 29 maja")


class PromptBlockCitationTests(SimpleTestCase):
    def test_prompt_block_names_are_not_citations(self):
        text, cits, _ = citations.finalize("Jutro opad 7 mm [kontekst]. Warunki sprzyjają chorobom [silnik] [brak fragmentów metodyk].", {})
        self.assertEqual(text, "Jutro opad 7 mm. Warunki sprzyjają chorobom.")


class ConfirmationWordsTests(WorldTestCase):
    """A pending draft: only yes/no words confirm or cancel; "Nie widzę objawów" is a new report (kind absence)."""

    def route_with_draft(self, message):
        s = State(self.conv())
        s.set_draft({"draft_id": "d1", "field_id": self.wheat.id, "field": self.wheat.name, "date": "2024-05-14",
                     "note": "plamy"})
        return router.route(message, self.wheat, s)

    def test_long_yes_still_saves(self):
        self.assertEqual(self.route_with_draft("Tak, zapisz tę obserwację, proszę").type, "potwierdzenie")

    def test_nie_widze_objawow_is_a_report_not_a_cancel(self):
        r = self.route_with_draft("Nie widzę objawów")
        self.assertEqual(r.type, "obserwacja")
        self.assertNotEqual(r.reason, "draft pending + correction")

    def test_cancel_words(self):
        for m in ("nie", "Nie zapisuj tego", "anuluj"):
            with self.subTest(m=m):
                self.assertEqual(self.route_with_draft(m).reason, "draft pending + no")

    def test_clean_field_in_other_words_is_a_report(self):
        from assistant.orchestrator.observations import detect_kind
        r = router.route("Na polu Długie nie ma żadnych objawów", None, State(None))
        self.assertEqual(r.type, "obserwacja")
        self.assertEqual(detect_kind("Na polu Długie nie ma żadnych objawów", dt.date(2024, 5, 27))[0], "absence")
