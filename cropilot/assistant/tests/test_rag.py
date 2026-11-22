"""Tests of the guide search (assistant/rag). Run with the rest: `python manage.py test assistant`.

They need the index (`python manage.py rag_ingest`); search tests also need Qdrant
(`docker compose up -d qdrant`). Without them the tests are skipped, not failed, so
teammates who don't work on the assistant are not blocked.
"""
from __future__ import annotations

import unittest

from django.test import SimpleTestCase

from assistant.rag import config
from assistant.rag.excel_parse import parse_temp

CORE = ["kukurydza_doradcy", "kukurydza_producenci", "pszenica_doradcy", "pszenica_producenci", "zboza_giorin"]


def _qdrant_error() -> str | None:
    from assistant.rag.store import QdrantStore, QdrantUnavailable
    try:
        QdrantStore()
    except QdrantUnavailable as e:
        return str(e)
    return None


NO_INDEX = not config.CHUNKS_JSONL.exists()
NO_INDEX_MSG = "no RAG index: run `python manage.py rag_ingest`"


class ParseTempTests(SimpleTestCase):
    def test_ranges_and_approximations(self):
        self.assertEqual(parse_temp("4-18")["temp_min_c"], 4)
        self.assertEqual(parse_temp("4–18")["temp_max_c"], 18)
        t = parse_temp("ok 20")
        self.assertEqual((t["temp_min_c"], t["temp_max_c"], t["temp_approx"]), (20, 20, True))
        t = parse_temp("25–30°C (optimum 18–22°C)")
        self.assertEqual((t["temp_min_c"], t["temp_max_c"], t["temp_opt_min_c"], t["temp_opt_max_c"]),
                         (25, 30, 18, 22))

    def test_unclear_values_are_not_guessed(self):
        self.assertIsNone(parse_temp("Lata ciepłe")["temp_min_c"])
        self.assertIsNone(parse_temp("P. atrosepticum: 15–24°C; P. carotovorum: 25–28°C")["temp_min_c"])


@unittest.skipIf(NO_INDEX, NO_INDEX_MSG)
class ChunkTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from assistant.rag.chunker import load_chunks
        cls.chunks = load_chunks()

    def test_each_core_pdf_has_chunks(self):
        for doc_id in CORE:
            with self.subTest(doc_id=doc_id):
                self.assertTrue(any(c["doc_id"] == doc_id for c in self.chunks))

    def test_no_empty_text(self):
        self.assertTrue(all(c["text"].strip() for c in self.chunks))

    def test_token_limit(self):
        over = [c["chunk_id"] for c in self.chunks if c["n_tokens"] > config.CHUNK_MAX_TOKENS]
        self.assertEqual(over, [])

    def test_every_chunk_has_a_section(self):
        no_sec = [c["chunk_id"] for c in self.chunks
                  if c["section_path"] in ([], ["(bez sekcji)"]) and c["doc_id"] != "zboza_giorin"]
        self.assertEqual(no_sec, [])

    def test_chunk_ids_unique_and_deterministic(self):
        from assistant.rag.chunker import chunk_doc
        from assistant.rag.docs import load_docs
        from assistant.rag.pdf_parse import load_pages
        from assistant.rag.toc import load_sections

        ids = [c["chunk_id"] for c in self.chunks]
        self.assertEqual(len(ids), len(set(ids)))
        doc_id = "pszenica_producenci"
        doc, pages, sec = load_docs()[doc_id], load_pages(doc_id), load_sections()[doc_id]
        first = [c["chunk_id"] for c in chunk_doc(doc, pages, sec)]
        second = [c["chunk_id"] for c in chunk_doc(doc, pages, sec)]
        stored = [c["chunk_id"] for c in self.chunks if c["doc_id"] == doc_id]
        self.assertEqual(first, second)
        self.assertEqual(first, stored)


@unittest.skipIf(NO_INDEX, NO_INDEX_MSG)
class RiskConditionsTests(SimpleTestCase):
    def test_septoria_temperature(self):
        from assistant.rag.search import get_risk_conditions
        rows = get_risk_conditions("pszenica", "septorioza paskowana")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["temperature_raw"], "4-18")
        # inflection and typos
        self.assertEqual(get_risk_conditions("pszenica", "septoriozy paskowanej")[0]["row"], rows[0]["row"])
        self.assertEqual(get_risk_conditions("pszenica", "septorjoza paskowana")[0]["row"], rows[0]["row"])


@unittest.skipIf(NO_INDEX, NO_INDEX_MSG)
class SearchTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        err = _qdrant_error()
        if err:
            raise unittest.SkipTest(err)

    def test_septoria_in_top5(self):
        from assistant.rag.search import search
        res = search("septorioza paskowana warunki", crop="pszenica", k=5)
        self.assertTrue(any("septorioz" in p.text.lower() for p in res))
        self.assertTrue(all(p.crop in ("pszenica", "zboza") for p in res))

    def test_default_search_excludes_pesticide_doses(self):
        from assistant.rag.search import _store, search
        ids = []
        for q, crop in [("ile litrów herbicydu na hektar", "kukurydza"),
                        ("dawka fungicydu na septoriozę", "pszenica"),
                        ("dobór środka ochrony roślin i dawki", None)]:
            ids += [p.chunk_id for p in search(q, crop=crop, k=10)]
        payloads = _store().get_by_chunk_id(ids)
        self.assertEqual([c for c, p in payloads.items() if p["has_pesticide_doses"]], [])

    def test_include_pesticide_doses_flag(self):
        from assistant.rag.search import _store, search
        res = search("dobór środka ochrony roślin i dawki herbicydu", crop="kukurydza", k=10,
                     include_pesticide_doses=True)
        payloads = _store().get_by_chunk_id([p.chunk_id for p in res])
        self.assertTrue(any(p["has_pesticide_doses"] for p in payloads.values()))

    def test_citation_matches_chat_api_format(self):
        from assistant.rag.search import search
        res = search("septorioza paskowana", crop="pszenica", k=10)
        pdf = next(p for p in res if p.pdf_pages)
        cit = pdf.to_citation()
        self.assertEqual(cit["type"], "guide")
        self.assertTrue((config.METODYKI_DIR / cit["document"]).exists())
        self.assertIsInstance(cit["page"], int)
        xls = next((p for p in res if p.sheet), None)
        if xls:
            self.assertEqual(xls.to_citation()["document"], "ryzyka_zebrane.xlsx")

    def test_get_passage_with_neighbours(self):
        from assistant.rag.chunker import load_chunks
        from assistant.rag.search import get_passage
        c = next(c for c in load_chunks("pszenica_doradcy") if c["prev_id"] and c["next_id"])
        ids = [p.chunk_id for p in get_passage(c["chunk_id"], with_neighbors=1)]
        self.assertEqual(ids, [c["prev_id"], c["chunk_id"], c["next_id"]])

    def test_get_page(self):
        from assistant.rag.search import get_page
        self.assertIn("Stanowisko i płodozmian", get_page("pszenica_doradcy", 17))
