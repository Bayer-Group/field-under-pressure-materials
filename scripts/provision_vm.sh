#!/usr/bin/env bash
# Stawianie i obsługa maszyny wirtualnej GCP z bazą PostGIS (docker/).
#
# Użycie:
#   scripts/provision_vm.sh create [-y]   # utwórz VM (płatny zasób, pyta o potwierdzenie)
#   scripts/provision_vm.sh setup         # zainstaluj Docker, sklonuj repo, utwórz .env, uruchom PostGIS
#   scripts/provision_vm.sh tunnel        # tunel SSH do bazy: localhost:$LOCAL_PORT -> VM:5432
#   scripts/provision_vm.sh status|start|stop
#
# Konfiguracja przez zmienne środowiskowe (wartości domyślne w nawiasach):
#   GCLOUD_CONFIG (geoearth)  nazwa konfiguracji gcloud: konto, projekt, region
#   VM_NAME (fup-vm)  ZONE (europe-central2-a)  MACHINE_TYPE (e2-standard-4)  DISK_GB (100)
#   REPO_URL, BRANCH (team/geoearth-junction)  LOCAL_PORT (5433)
#   DRY_RUN=1  tylko wypisz komendy zmieniające stan, nic nie wykonuj
#
# Zasady:
#   - Port bazy (5432) NIE jest otwierany w zaporze GCP; dostęp wyłącznie tunelem SSH.
#   - Hasło bazy jest losowane na VM i zostaje tylko w ~/field-under-pressure-materials/.env na VM.
#     Odczyt (np. do QGIS): gcloud compute ssh "$VM_NAME" --command 'grep POSTGRES_PASSWORD ~/field-under-pressure-materials/.env'
#   - Skrypt nie usuwa niczego. Usunięcie VM zrobić ręcznie: gcloud compute instances delete "$VM_NAME"

set -euo pipefail

GCLOUD_CONFIG="${GCLOUD_CONFIG:-geoearth}"
VM_NAME="${VM_NAME:-fup-vm}"
ZONE="${ZONE:-europe-central2-a}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-4}"
DISK_GB="${DISK_GB:-100}"
REPO_URL="${REPO_URL:-https://github.com/geoearth-junction/field-under-pressure-materials.git}"
BRANCH="${BRANCH:-team/geoearth-junction}"
LOCAL_PORT="${LOCAL_PORT:-5433}"
DRY_RUN="${DRY_RUN:-0}"

# Konfiguracja gcloud tylko dla tego procesu (nie przełącza aktywnej konfiguracji w innych terminalach).
export CLOUDSDK_ACTIVE_CONFIG_NAME="$GCLOUD_CONFIG"

die() { echo "BŁĄD: $*" >&2; exit 1; }

# Komendy zmieniające stan: w trybie DRY_RUN tylko wypisane.
run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[DRY_RUN]'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

check_env() {
  command -v gcloud >/dev/null 2>&1 || die "brak gcloud w PATH"
  gcloud config configurations describe "$GCLOUD_CONFIG" >/dev/null 2>&1 \
    || die "brak konfiguracji gcloud '$GCLOUD_CONFIG' (gcloud config configurations list)"
  PROJECT="$(gcloud config get project 2>/dev/null || true)"
  ACCOUNT="$(gcloud config get account 2>/dev/null || true)"
  [ -n "$PROJECT" ] || die "konfiguracja '$GCLOUD_CONFIG' nie ma ustawionego projektu"
  [ -n "$ACCOUNT" ] || die "konfiguracja '$GCLOUD_CONFIG' nie ma ustawionego konta"
}

vm_exists() {
  gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --format='value(name)' >/dev/null 2>&1
}

vm_status() {
  gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --format='value(status)' 2>/dev/null || true
}

cmd_create() {
  if vm_exists; then
    echo "VM '$VM_NAME' już istnieje (status: $(vm_status)). Nic do zrobienia."
    return 0
  fi
  echo "Zostanie utworzona maszyna (płatny zasób):"
  echo "  konto:   $ACCOUNT"
  echo "  projekt: $PROJECT"
  echo "  VM:      $VM_NAME, strefa $ZONE, typ $MACHINE_TYPE, dysk ${DISK_GB} GB, Debian 12"
  if [ "${1:-}" != "-y" ] && [ "${1:-}" != "--yes" ] && [ "$DRY_RUN" != "1" ]; then
    local ans="n"
    read -r -p "Utworzyć? [y/N] " ans || ans="n"
    case "$ans" in y|Y|yes|YES) ;; *) echo "Anulowano."; return 0 ;; esac
  fi
  run gcloud compute instances create "$VM_NAME" \
    --zone "$ZONE" \
    --machine-type "$MACHINE_TYPE" \
    --image-family debian-12 --image-project debian-cloud \
    --boot-disk-size "${DISK_GB}GB" --boot-disk-type pd-balanced \
    --tags fup
  echo "Gotowe. Następny krok: scripts/provision_vm.sh setup"
}

cmd_setup() {
  vm_exists || die "VM '$VM_NAME' nie istnieje (najpierw: create)"
  [ "$(vm_status)" = "RUNNING" ] || die "VM '$VM_NAME' nie działa (status: $(vm_status)); uruchom: start"
  if [ "$DRY_RUN" = "1" ]; then
    echo "[DRY_RUN] ssh do $VM_NAME: instalacja Dockera, klon $REPO_URL ($BRANCH), .env z losowym hasłem, docker compose up -d postgis"
    return 0
  fi
  # Skrypt wykonywany na VM. Zmienne przekazane jawnie; hasło generowane na miejscu.
  gcloud compute ssh "$VM_NAME" --zone "$ZONE" \
    --command "REPO_URL='$REPO_URL' BRANCH='$BRANCH' bash -s" <<'REMOTE'
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl
  curl -fsSL https://get.docker.com | sudo sh
fi
for pkg in git openssl; do
  command -v "$pkg" >/dev/null 2>&1 || sudo apt-get install -y "$pkg"
done
sudo usermod -aG docker "$USER" || true

DIR="$HOME/field-under-pressure-materials"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin "$BRANCH"
  git -C "$DIR" checkout "$BRANCH"
  git -C "$DIR" pull --ff-only origin "$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO_URL" "$DIR"
fi
cd "$DIR"

if [ ! -d docker/initdb ]; then
  echo "BŁĄD: w gałęzi '$BRANCH' nie ma docker/initdb (zmerguj PR z bazą albo ustaw BRANCH)." >&2
  exit 1
fi

if [ -f .env ]; then
  echo ".env już istnieje: bez zmian."
else
  cp example.env .env
  PASS="$(openssl rand -base64 24 | tr -d '/+=\n')"
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${PASS}/" .env
  chmod 600 .env
  echo "Utworzono .env z losowym hasłem (nie jest wyświetlane)."
fi

sudo docker compose --env-file .env -f docker/docker-compose.yml up -d postgis

set -a; . ./.env; set +a
for _ in $(seq 1 30); do
  sudo docker exec spatial_postgis pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1 && break
  sleep 2
done
sudo docker exec spatial_postgis psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\dt fup.*'
REMOTE
  echo "Gotowe. Dostęp do bazy: scripts/provision_vm.sh tunnel"
}

cmd_tunnel() {
  vm_exists || die "VM '$VM_NAME' nie istnieje"
  echo "Tunel: localhost:${LOCAL_PORT} -> ${VM_NAME}:5432 (Ctrl+C kończy). W QGIS/psql: host localhost, port ${LOCAL_PORT}."
  if [ "$DRY_RUN" = "1" ]; then
    echo "[DRY_RUN] gcloud compute ssh $VM_NAME --zone $ZONE -- -N -L ${LOCAL_PORT}:localhost:5432"
    return 0
  fi
  exec gcloud compute ssh "$VM_NAME" --zone "$ZONE" -- -N -L "${LOCAL_PORT}:localhost:5432"
}

cmd_status() {
  if vm_exists; then
    gcloud compute instances list --filter="name=$VM_NAME" \
      --format='table(name,zone.basename(),machineType.basename(),status,networkInterfaces[0].accessConfigs[0].natIP:label=EXTERNAL_IP)'
  else
    echo "VM '$VM_NAME' nie istnieje w projekcie $PROJECT."
  fi
}

cmd_power() {
  vm_exists || die "VM '$VM_NAME' nie istnieje"
  run gcloud compute instances "$1" "$VM_NAME" --zone "$ZONE"
}

usage() { sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; }

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    create|setup|tunnel|status|start|stop) check_env ;;
    ""|-h|--help|help) usage; exit 0 ;;
    *) usage >&2; die "nieznana komenda: $cmd" ;;
  esac
  case "$cmd" in
    create) cmd_create "$@" ;;
    setup)  cmd_setup ;;
    tunnel) cmd_tunnel ;;
    status) cmd_status ;;
    start)  cmd_power start ;;
    stop)   cmd_power stop ;;
  esac
}

main "$@"
