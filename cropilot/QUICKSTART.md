# Quick Start

One script sets up the demo on macOS or Linux (there is no Windows script: follow the README's steps).

```bash
./start.sh              # first run
./start.sh --reset      # reload the demo scenario even if a demo date is already set
python manage.py runserver
```

Open <http://localhost:8000>. The demo itself is described in [docs/demo-script.md](docs/demo-script.md).

## What the script does

1. Finds Python 3.11+ (`python3.12`, `python3.11`, `python3`, `python`), Docker and Node.js (22+ for the frontend packages).
2. Creates `.venv` and installs `requirements.txt` (the first run downloads torch: a few minutes, several GB).
3. Creates `.env` from `.env.example` if missing. **It has no LLM keys**: the map and risks work, the chat stays off
   (greyed out, with the reason) until you add `GEMINI_API_KEY` or `GROQ_API_KEY` and restart the server.
4. Starts Postgres and Qdrant (`docker compose up -d`) and waits for the database.
5. Runs the migrations.
6. Loads the demo scenario `demo_2024` (27 May 2024, 8 real parcels near Krapkowice) from the organisers' data in
   `DATA_DIR` (README → Demo data). Without that data it says so and loads the scenario on **synthetic** weather,
   soil and crop history: everything works, but the numbers differ from the demo script.
7. The switch also precomputes the date cache, so the date arrows take about 0.3 s.
8. Builds the frontend.
9. Builds the guide index for the chat (`rag_ingest`, 2–4 min) unless the Qdrant collection and the BM25 file exist.

It never hides an error: it stops at the first failing step and shows its output. It creates an admin user only
when you ask for one: `ADMIN_PASSWORD=… ./start.sh` (or later `python manage.py createsuperuser`).

## Between demo runs

```bash
python manage.py scenario switch demo_2024 --strict-data --keep-weather --reset-chat   # about 2 min: drops reports and chats
```

Then reload the page (Ctrl+Shift+R): field ids change with every switch.

## Without LLM keys or without the guide index

| Missing | What works | What the page shows |
|---|---|---|
| LLM keys | map, risks, field panel, date control | chat greyed out: "Asystent jest wyłączony…"; header: "Połączono · asystent wyłączony" |
| guide index (Qdrant collection or `assistant/data/index/bm25.pkl`) | everything; answers come without guide citations | a "bez metodyk" badge in the chat |

`GET /api/health/` reports both: `{"assistant": {"available", "llm", "rag", "reason"}}`. Check the keys with
`python manage.py llm_models`.

## Troubleshooting

- **The database did not become ready.** `docker compose ps`; then `docker compose up -d` again and rerun the script.
- **Port 5433 is taken.** Set `POSTGRES_PORT=5434` in `.env` (docker-compose.yml reads it) and rerun.
- **Import errors after a pull.** `source .venv/bin/activate && pip install -r requirements.txt && python manage.py migrate`.
- **Reset the admin password.** `python manage.py changepassword admin`.
- **After `docker compose down -v`** (wipes the database and the guide index): `./start.sh --reset`.

## Everyday commands

| Task | Command |
|---|---|
| Run the server | `python manage.py runserver` |
| Rebuild the frontend on save | `cd frontend && npm run watch` |
| Type-check the frontend | `cd frontend && npm run typecheck` |
| Rebuild the guide index | `python manage.py rag_ingest` |
| Run the tests | `python manage.py test` |
| Move the demo date from the terminal | `python manage.py engine_set_date 2024-05-30` |

All data lives in the Docker volumes `pgdata` and `qdrant_storage`: `docker compose stop` keeps them,
`docker compose down -v` deletes them.
