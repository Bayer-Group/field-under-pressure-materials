#!/bin/bash
# Cropilot (Field Under Pressure hackathon) — one-command setup of the demo (docs/demo-script.md).
#
#   ./start.sh            first run: venv, dependencies, Postgres + Qdrant, migrations, the demo scenario
#                         (demo_2024, 27 May 2024), the date cache, the frontend, the guide index
#   ./start.sh --reset    the same, and reload the demo scenario even if a demo date is already set
#
# Then: python manage.py runserver   (with LLM keys in .env, or the chat stays off; the map works without them)
# Errors are never hidden: the script stops at the first failing step and shows its output.

set -euo pipefail
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
step() { echo -e "${BLUE}▸ $*${NC}"; }
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}! $*${NC}"; }
die()  { echo -e "${RED}✗ $*${NC}"; exit 1; }

RESET=0
[[ "${1:-}" == "--reset" ]] && RESET=1

echo -e "${BLUE}Cropilot — setting up the demo${NC}\n"

# --- prerequisites -------------------------------------------------------------------------------
PY=""
for candidate in python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        PY="$candidate"; break
    fi
done
[[ -n "$PY" ]] || die "Python 3.11+ not found (tried python3.12, python3.11, python3, python)."
command -v docker >/dev/null 2>&1 || die "Docker not found."
command -v node >/dev/null 2>&1 || die "Node.js not found (22+ needed by the frontend packages)."
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
(( NODE_MAJOR >= 22 )) || warn "Node.js $NODE_MAJOR found; the frontend packages want 22+."
ok "Python $($PY --version | cut -d' ' -f2), Docker, Node.js $(node --version)"

# --- Python environment ------------------------------------------------------------------------------
if [[ ! -d .venv ]]; then
    step "Creating the virtual environment (.venv)"
    "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
step "Installing Python dependencies (first run: a few minutes; torch is large)"
pip install -q -r requirements.txt

if [[ ! -f .env ]]; then
    cp .env.example .env
    warn ".env created from .env.example. It has no LLM keys: the chat stays off until you add GEMINI_API_KEY or GROQ_API_KEY."
fi

# --- services ------------------------------------------------------------------------------------------
step "Starting Postgres and Qdrant (docker compose up -d)"
docker compose up -d
DB_USER=$(grep -E '^POSTGRES_USER=' .env | cut -d= -f2- || true); DB_USER=${DB_USER:-fieldpressure}
DB_NAME=$(grep -E '^POSTGRES_DB=' .env | cut -d= -f2- || true); DB_NAME=${DB_NAME:-fieldpressure}
for _ in $(seq 1 30); do
    docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
    sleep 1
done
docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 || die "The database did not become ready."
ok "Database ready"

step "Migrations"
python manage.py migrate -v 0

if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
    step "Admin user (admin / \$ADMIN_PASSWORD)"
    python manage.py shell -c "
from django.contrib.auth import get_user_model
U = get_user_model()
import os
U.objects.filter(username='admin').exists() or U.objects.create_superuser('admin', 'admin@example.com', os.environ['ADMIN_PASSWORD'])
print('admin ready')"
fi

# --- the demo farm -------------------------------------------------------------------------------------
HAS_CLOCK=$(python manage.py shell -c "from core.models import Clock; print(int(Clock.objects.exists()))" 2>/dev/null | tail -1)
if [[ "$RESET" == 1 || "$HAS_CLOCK" != 1 ]]; then
    step "Loading the demo scenario demo_2024 (real data from DATA_DIR, risks and the date cache; about 2 min)"
    if ! python manage.py scenario switch demo_2024 --reset-chat --strict-data; then
        warn "The organisers' data is missing in DATA_DIR (README → Demo data). Loading the scenario on SYNTHETIC"
        warn "weather, soil and crop history instead: the numbers will differ from docs/demo-script.md."
        SYNTH_FLAG=""  # newer `scenario` is strict by default and needs this flag to generate data
        python manage.py scenario switch --help 2>/dev/null | grep -q -- --allow-synthetic-fallback && SYNTH_FLAG="--allow-synthetic-fallback"
        python manage.py scenario switch demo_2024 --reset-chat $SYNTH_FLAG
    fi
else
    ok "A demo date is set already (./start.sh --reset reloads the scenario)"
fi

# --- frontend --------------------------------------------------------------------------------------------
step "Building the frontend"
(cd frontend && npm install --no-audit --no-fund --silent && npm run -s build)
ok "Frontend built"

# --- guide index (RAG) -------------------------------------------------------------------------------------
if python manage.py shell -c "from assistant.status import rag_ready; import sys; sys.exit(0 if rag_ready() else 1)" >/dev/null 2>&1; then
    ok "Guide index ready (Qdrant collection + BM25)"
else
    step "Building the guide index (2-4 min on the first run)"
    python manage.py rag_ingest
fi

LLM_OK=$(python manage.py shell -c "from assistant.status import llm_ready; print(int(llm_ready()))" 2>/dev/null | tail -1)
echo ""
echo -e "${GREEN}Ready.${NC} Start the server:  ${YELLOW}python manage.py runserver${NC}  →  http://localhost:8000"
[[ "$LLM_OK" == 1 ]] || warn "No LLM keys in .env: the map and risks work, the chat is off (README → LLM keys)."
echo "API docs: http://localhost:8000/api/docs/   Demo script: docs/demo-script.md"
echo "Reset between demo runs: python manage.py scenario switch demo_2024 --strict-data --keep-weather --reset-chat"
