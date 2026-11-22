# RAG nad metodykami IOR — `assistant/rag`

Warstwa wyszukiwania dla asystenta Field Under Pressure. Obejmuje parsowanie PDF i Excela, chunking, embeddingi `sdadas/mmlw-retrieval-roberta-base`, Qdrant (wektory), BM25 (Python) i hybrydę RRF. Serwer MCP importuje API z `rag/search.py`.

## Uruchomienie

Moduł jest częścią aplikacji Django `assistant` (`assistant/rag/`), ale nie zależy od Django: serwer MCP i CLI importują `assistant.rag.*` bezpośrednio. Wszystkie komendy uruchamia się z **katalogu głównego repo**.

Zależności to sekcja „AI assistant (Ola)” w `requirements.txt`. Wymaga Pythona 3.11+ (pymupdf 2.1); `.python-version` ustawia 3.12.

```bash
uv venv --seed && uv pip install -r requirements.txt    # albo: python3.12 -m venv .venv && pip install -r requirements.txt
cp .env.example .env                                     # QDRANT_HOST / QDRANT_PORT w sekcji "Assistant"
docker compose up -d                                     # db (Postgres) + qdrant (1.20.2, dashboard: http://localhost:6333/dashboard)
uv run python manage.py rag_ingest                       # 5 PDF + Excel -> chunks -> embeddingi -> Qdrant + BM25
uv run python manage.py rag_ingest --doc pszenica_doradcy --rebuild
uv run python manage.py rag_ingest --all-crops           # + 10 pozostałych PDF (jęczmień, owies, …)
uv run python manage.py rag_search "w jakiej temperaturze rozwija się septorioza paskowana" --crop pszenica --k 5
uv run python manage.py rag_search --risk pszenica "rdza brunatna"
uv run python manage.py test assistant                   # testy RAG (assistant/tests/test_rag.py) + testy czatu
uv run python assistant/eval/run_eval.py                 # ewaluacja wyszukiwania
```

`python -m assistant.rag.ingest` i `python -m assistant.rag.cli` działają tak samo jak komendy `manage.py`.

- **Ścieżki**: PDF-y i Excel są czytane z submodułu `field-under-pressure-materials/metodyki/`, czyli `settings.MATERIALS_DIR / "metodyki"`. Wygenerowane pliki trafiają do `assistant/data/` (gitignore). Obie ścieżki można nadpisać w `.env` przez `METODYKI_DIR` i `RAG_DATA_DIR` (ścieżki względne liczone od katalogu repo).
- **Konfiguracja**: `rag/config.py` czyta ten sam `.env` co Django. Zmienne: `QDRANT_HOST` / `QDRANT_PORT` (albo `QDRANT_URL`), `QDRANT_COLLECTION` (`guides_mmlw_v1`), `RAG_BM25_STEMMER` (`stempel` | `trunc6`).
- **Testy**: bez indeksu albo bez działającego Qdranta testy RAG są pomijane, a nie oblane, więc `python manage.py test` nie blokuje reszty zespołu.
- **Czas**: pierwszy ingest trwa ok. 4 min na M-series (MPS), w tym embeddingi ok. 165 s i `find_tables` ok. 60 s; oba wyniki trafiają do cache. Kolejne przebiegi trwają ok. 1 min. `docker compose down -v` kasuje też indeks w Qdrancie; wtedy wystarczy ponownie `rag_ingest`, bo embeddingi są w cache.
- `--rebuild` usuwa kolekcję i wgrywa od nowa wszystko z `chunks.jsonl`. Bez tej flagi ingest usuwa i wgrywa tylko punkty przetwarzanych dokumentów. Ingest jest idempotentny dzięki deterministycznym `chunk_id` i id `uuid5(chunk_id)`.

## Pipeline

| moduł | wejście → wyjście | uwagi |
|---|---|---|
| `docs.py` | rejestr → `docs.json` | tytuł z największego fontu strony 1; dla 3 PDF tytuł z rejestru (`title_source`) |
| `pdf_parse.py` | PDF → `pages.jsonl` | usuwa żywą paginę i numery stron (`printed_page` odczytany albo uzupełniony z offsetu), skleja przeniesienia, buduje akapity, tabele przez `find_tables` z tekstem przypisanym do komórek, strony `skip` z powodem |
| `toc.py` | spis treści → `sections.json` | sklejanie zawiniętych wpisów, numeracja arabska i rzymska (`IV.3.1`), dopasowanie nagłówka do bloku na stronie (rapidfuzz + styl fontu); GIORiN: nagłówki z fontu |
| `chunker.py` | sekcje → `chunks.jsonl` | ≤ 450 tokenów tokenizera modelu, cel 180–280 słów, nakładka ≤ 50 słów, małe sekcje doklejane, tabele osobno z powtarzanym nagłówkiem, podnagłówki (np. nazwa choroby) w `subheading` |
| `flags.py` | — | `has_pesticide_doses`, `has_fertilizer_doses`, `is_legal` |
| `excel_parse.py` | xlsx → `risk_conditions.json` + chunki | wykrywanie nagłówków tabel, wiersz pomocniczy (`dzień | noc`), notatki, `temp_min_c`/`temp_max_c` |
| `embed.py` | — | prefiks `zapytanie: ` tylko dla zapytań; cache sha1 w `emb_cache.npz` |
| `store.py` | — | `QdrantStore` (cosine, 768, indeksy payloadu), protokół `VectorStore` |
| `bm25.py` | — | tokenizacja PL, stop-słowa, `stempel` (pystempel polimorf) lub `trunc6`; oba warianty w `bm25.pkl` |

## Schemat chunka (`chunks.jsonl`)

```json
{
  "chunk_id": "pszenica_doradcy:5.1:0007",
  "doc_id": "pszenica_doradcy", "doc_title": "Metodyka integrowanej ochrony pszenicy ozimej i jarej dla doradców",
  "crop": "pszenica", "audience": "doradcy",
  "section_path": ["5. Ograniczanie sprawców chorób", "5.1. Najważniejsze choroby"], "section_id": "5.1",
  "subheading": "Septorioza paskowana liści pszenicy",
  "pdf_page_start": 72, "pdf_page_end": 73, "printed_page_start": 70, "printed_page_end": 71,
  "kind": "text",                    // text | table | excel_row | excel_note
  "text": "…do wyświetlania i cytowania…",
  "embed_text": "{tytuł} | {ścieżka > podnagłówek} | uprawa: {crop}\n\n{tekst}",
  "n_tokens": 312, "n_words": 190,
  "flags": {"has_pesticide_doses": false, "has_fertilizer_doses": false, "is_legal": false},
  "prev_id": "…", "next_id": "…"
}
```

Chunki z Excela mają `doc_id="ryzyka_zebrane"`, `audience="zestawienie"` oraz `sheet`, `row` i `row_end` zamiast stron. `chunk_id` wygląda tak: `ryzyka_zebrane:pszenica.r019`.

Payload w Qdrant to chunk bez `embed_text`, z flagami skopiowanymi na najwyższy poziom. Indeksy keyword: `crop`, `audience`, `doc_id`, `kind`, `chunk_id`, `section_id`. Indeksy bool: `has_pesticide_doses`, `is_legal`, `has_fertilizer_doses`.

## API (`assistant/rag/search.py`)

```python
from assistant.rag.search import search, get_passage, get_page, get_risk_conditions

search(query, crop=None, audience=None, k=6, include_pesticide_doses=False,
       mode="hybrid" | "dense" | "bm25") -> list[Passage]
get_passage(chunk_id, with_neighbors=0) -> list[Passage]   # chunk ± sąsiedzi
get_page(doc_id, printed_page) -> str                       # czysty tekst strony + tabele (Markdown)
get_risk_conditions(crop, threat=None) -> list[dict]        # rekordy risk_conditions.json, fuzzy po nazwie
```

`Passage` ma pola: `chunk_id, doc_id, doc_title, crop, audience, section, printed_pages, pdf_pages, kind, text, score, citation, document, printed_page, sheet, row`.

- `citation` to tekst dla człowieka, np. `Metodyka integrowanej ochrony pszenicy ozimej i jarej dla doradców (doradcy), s. 70–71`.
- `passage.to_citation()` zwraca cytat w formacie API czatu (`docs/interfaces.md` → Chat → Citations), gotowy do `Reply.citations`:
  - PDF: `{"type": "guide", "document": "metodyka_-_PSZENICA_-_www.pdf", "page": 79, "printed_page": 77, "section": "5. … > 5.1. …"}`. `page` to strona PDF (1-based), więc przeglądarka otworzy `plik.pdf#page=79`. `printed_page` (numer wydrukowany w książce) i `section` to dodatkowe klucze do wyświetlenia.
  - Excel: `{"type": "guide", "document": "ryzyka_zebrane.xlsx", "sheet": "pszenica", "row": 19}`.

- **Hybryda**: top 30 z wyszukiwania wektorowego i top 30 z BM25, z tymi samymi filtrami, łączone przez RRF `w/(60+rank)`. Wagi ustawia się w `config.py`.
- **Filtry**:
  - `crop="pszenica"` przeszukuje `["pszenica", "zboza"]`.
  - `audience` zawsze dopuszcza też wiersze z Excela.
  - Domyślnie wykluczane są chunki `has_pesticide_doses`.
  - Chunki `is_legal` mają wynik mnożony przez 0,5 po fuzji.
- **Scalanie sąsiadów**: sąsiednie chunki tej samej sekcji są łączone w jeden `Passage`. Nakładka jest usuwana, a zakres stron się sumuje.
- **`get_risk_conditions`**: dopasowuje nazwę po złożeniu polskich znaków. Toleruje fleksję i literówki („septoriozy paskowanej”, „septorjoza”) dzięki `token_set_ratio` liczonemu też na 5-znakowych prefiksach słów.
- **Ładowanie zasobów**: model, klient Qdrant, BM25, strony i ryzyka ładują się leniwie, raz na proces.
- **Gdy Qdrant nie działa**: `QdrantUnavailable` z komunikatem „Qdrant nie działa na …, uruchom w katalogu repo: docker compose up -d qdrant”.

## Statystyki indeksu (5 PDF + Excel)

| dokument | strony (pominięte) | tabele | chunki (tekst / tabela) | sekcje: wpisy, dopasowane |
|---|---|---|---|---|
| kukurydza_doradcy | 248 (39) | 64 | 525 (418 / 107) | 73, 73/73 |
| kukurydza_producenci | 70 (14) | 28 | 153 (108 / 45) | 36, 34/36 |
| pszenica_doradcy | 224 (36) | 73 | 431 (285 / 146) | 48, 48/48 |
| pszenica_producenci | 70 (15) | 32 | 141 (79 / 62) | 36, 35/36 |
| zboza_giorin | 24 (4) | 2 | 47 (44 / 3) | 33 (z fontów), wszystkie |
| ryzyka_zebrane | 5 arkuszy | — | 106 (94 wiersze / 12 notatek) | — |

- **Razem**: 1403 chunki dla 5 PDF + Excela (z `--all-crops`: 3978); liczba punktów w Qdrant zawsze równa liczbie chunków.
- **Tokeny** (min / mediana / p95 / maks.): 39 / 339 / 439 / 446. Chunków powyżej 450 tokenów: 0.
- **Pokrycie sekcjami**: 100% stron z treścią.
- **Flagi**: `has_pesticide_doses` 212, `has_fertilizer_doses` 36, `is_legal` 27.

## Ewaluacja (`assistant/eval/run_eval.py`, 29 pytań + 3 pułapki)

| tryb | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| dense | 0.72 | 0.93 | 0.97 | 0.830 |
| bm25 / stempel | 0.83 | 0.97 | 1.00 | 0.899 |
| bm25 / trunc6 | 0.93 | 1.00 | 1.00 | 0.954 |
| **hybrid / stempel** (domyślny) | 0.86 | 1.00 | **1.00** | 0.925 |
| hybrid / trunc6 | 0.83 | 1.00 | 1.00 | 0.891 |

- **Pułapki o dawki**: w top 5 przy domyślnych filtrach nie ma żadnego chunka `has_pesticide_doses`.
- **Zastrzeżenie**: zestaw jest łagodny. Trafieniem jest dowolny chunk z właściwego dokumentu zawierający frazę, a pytania używają słownictwa z tekstu, co faworyzuje BM25. Do porównywania wariantów warto dodać pytania parafrazowane i potoczne (np. „żółte paski na liściach”), z węższym `contains`.

## Znane ograniczenia i heurystyki do dopracowania

- **Żywa pagina**: linie w pasie 7% góry i dołu strony, powtarzające się na ≥ 3 stronach (tytuł rozdziału nie powtarza się na 30% stron). Numer strony szukam w pasie 12%, bo w kukurydzy stoi na 8,6% od dołu.
- **Dzielenie wyrazów**: `słowo-\nmała litera` jest zawsze sklejane, więc łamany złożony wyraz („młynarsko-\npiekarniczym”) traci myślnik.
- **Akapity**: dzielone według wcięcia, krótkiej linii z kropką, odstępu w pionie i zmiany stylu. Kontynuacja z poprzedniej strony (`cont`) jest doklejana. Etykiety wykresów usuwam heurystycznie (krótkie, mniejszy font).
- **Tabele**: `find_tables` uruchamiam tylko na stronach z ≥ 8 liniami siatki, więc tabele bez linii zostają tekstem. Wielowierszowe nagłówki powtarzam tylko pierwszym wierszem. Ciąg dalszy tabeli („Tabela 27. Cd.”) dziedziczy nagłówek poprzedniej, jeśli liczba kolumn się zgadza.
- **TOC**: 3 wpisy niedopasowane w wersjach dla producentów (sekcja zaczyna się wtedy na stronie wyliczonej z offsetu). Podnagłówki spoza TOC to heurystyka stylu: pogrubienie lub inna rodzina fontu, ≤ 12 słów, jedno zdanie.
- **GIORiN**: brak numerów stron, więc cytat ma postać „s. PDF n”. Opisy śnieci cuchnącej i karłowej są w jednej sekcji.
- **Kodowanie znaków**: mapa cp1250→cp1252 naprawia krzaki („Poznañ”, „redakcj¹”). Krzaki występują tylko na stronach redakcyjnych wersji dla producentów.
- **Flagi**: `has_pesticide_doses` pochodzi w praktyce z tytułu sekcji najniższego poziomu (212/212). Regex dawek w sąsiedztwie słów herbicyd/fungicyd/środek… wyklucza ciecz użytkową, nawożenie i wysiew. Sekcja „Dobór techniki stosowania środka” nie jest flagowana. Sekcje „Metody określania liczebności i progi szkodliwości” pod „Chemiczne metody” też nie, bo progi są potrzebne.
- **Excel**:
  - `threat_type="inne"` dla niejednoznacznych nagłówków („Agrofag”, „Szkodnik / choroba”).
  - Temperatury z kilkoma zakresami w jednej komórce dają `null`.
  - „ok 20” daje `temp_approx=true`.
  - Jednostka temperatury w arkuszu pszenicy nie jest podana (zakładamy °C, ale tylko w polach `*_c`; `temperature_raw` zostaje bez zmian).
- **`--all-crops`** (wszystkie 15 PDF są w indeksie: 3978 chunków, 0 ponad 450 tokenów):
  - `jeczmien_doradcy` ma spis „kolumnowy” (numery stron osobną kolumną), obsługiwany osobnym trybem w `toc.py`: 38/42 wpisów dopasowanych.
  - `owies_doradcy`: 8 z 38 wpisów niedopasowanych (nagłówki wersalikami). Sekcje zaczynają się wtedy na stronie wyliczonej z offsetu.
  - Pytania ewaluacyjne dotyczą tylko pszenicy, kukurydzy i zbóż.
