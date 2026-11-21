#!/usr/bin/env bash
# Create and operate the GCP virtual machine that runs the PostGIS database (docker/).
#
# Usage:
#   scripts/provision_vm.sh create [-y]   # create the VM (billable resource, asks for confirmation)
#   scripts/provision_vm.sh setup         # install Docker, clone the repo, create .env, start PostGIS
#   scripts/provision_vm.sh tunnel        # SSH tunnel to the database: localhost:$LOCAL_PORT -> VM:5432
#   scripts/provision_vm.sh deploy        # update the code on the VM and (re)start the backend API container
#   scripts/provision_vm.sh api-tunnel    # SSH tunnel to the API: localhost:$API_PORT -> VM:$API_PORT
#   API_SOURCE_RANGES=<cidr,...> scripts/provision_vm.sh firewall   # open TCP 80/443 (HTTPS in front of the API) for the given addresses only
#   scripts/provision_vm.sh status|start|stop
#
# Configuration via environment variables (defaults in parentheses):
#   GCLOUD_CONFIG (geoearth)  gcloud configuration name: account, project, region
#   VM_NAME (fup-vm)  ZONE (europe-central2-a)  MACHINE_TYPE (e2-standard-4)  DISK_GB (100)
#   REPO_URL, BRANCH (team/geoearth-junction)  LOCAL_PORT (5433)  API_PORT (8000)
#   DRY_RUN=1  only print the state-changing commands, do not run them
#
# Rules:
#   - The database port (5432) is NOT opened in the GCP firewall; access only through an SSH tunnel.
#   - The database password is generated on the VM and stays only in ~/field-under-pressure-materials/.env there.
#     To read it (e.g. for QGIS): gcloud compute ssh "$VM_NAME" --command 'grep POSTGRES_PASSWORD ~/field-under-pressure-materials/.env'
#   - The script never deletes anything. Delete the VM manually: gcloud compute instances delete "$VM_NAME"

set -euo pipefail

GCLOUD_CONFIG="${GCLOUD_CONFIG:-geoearth}"
VM_NAME="${VM_NAME:-fup-vm}"
ZONE="${ZONE:-europe-central2-a}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-4}"
DISK_GB="${DISK_GB:-100}"
REPO_URL="${REPO_URL:-https://github.com/geoearth-junction/field-under-pressure-materials.git}"
BRANCH="${BRANCH:-team/geoearth-junction}"
LOCAL_PORT="${LOCAL_PORT:-5433}"
API_PORT="${API_PORT:-8000}"
DRY_RUN="${DRY_RUN:-0}"

# gcloud configuration for this process only (does not switch the active configuration in other terminals).
export CLOUDSDK_ACTIVE_CONFIG_NAME="$GCLOUD_CONFIG"

die() { echo "ERROR: $*" >&2; exit 1; }

# State-changing commands: only printed in DRY_RUN mode.
run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[DRY_RUN]'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

check_env() {
  command -v gcloud >/dev/null 2>&1 || die "gcloud not found in PATH"
  gcloud config configurations describe "$GCLOUD_CONFIG" >/dev/null 2>&1 \
    || die "no gcloud configuration '$GCLOUD_CONFIG' (see: gcloud config configurations list)"
  PROJECT="$(gcloud config get project 2>/dev/null || true)"
  ACCOUNT="$(gcloud config get account 2>/dev/null || true)"
  [ -n "$PROJECT" ] || die "configuration '$GCLOUD_CONFIG' has no project set"
  [ -n "$ACCOUNT" ] || die "configuration '$GCLOUD_CONFIG' has no account set"
}

vm_exists() {
  gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --format='value(name)' >/dev/null 2>&1
}

vm_status() {
  gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --format='value(status)' 2>/dev/null || true
}

cmd_create() {
  if vm_exists; then
    echo "VM '$VM_NAME' already exists (status: $(vm_status)). Nothing to do."
    return 0
  fi
  echo "A virtual machine will be created (billable resource):"
  echo "  account: $ACCOUNT"
  echo "  project: $PROJECT"
  echo "  VM:      $VM_NAME, zone $ZONE, type $MACHINE_TYPE, disk ${DISK_GB} GB, Debian 12"
  if [ "${1:-}" != "-y" ] && [ "${1:-}" != "--yes" ] && [ "$DRY_RUN" != "1" ]; then
    local ans="n"
    read -r -p "Create it? [y/N] " ans || ans="n"
    case "$ans" in y|Y|yes|YES) ;; *) echo "Cancelled."; return 0 ;; esac
  fi
  run gcloud compute instances create "$VM_NAME" \
    --zone "$ZONE" \
    --machine-type "$MACHINE_TYPE" \
    --image-family debian-12 --image-project debian-cloud \
    --boot-disk-size "${DISK_GB}GB" --boot-disk-type pd-balanced \
    --tags fup
  if [ "$DRY_RUN" = "1" ]; then
    echo "DRY_RUN: nothing was created."
  else
    echo "Done. Next step: scripts/provision_vm.sh setup"
  fi
}

cmd_setup() {
  vm_exists || die "VM '$VM_NAME' does not exist (run create first)"
  [ "$(vm_status)" = "RUNNING" ] || die "VM '$VM_NAME' is not running (status: $(vm_status)); run: start"
  if [ "$DRY_RUN" = "1" ]; then
    echo "[DRY_RUN] ssh to $VM_NAME: install Docker, clone $REPO_URL ($BRANCH), create .env with a random password, docker compose up -d postgis"
    return 0
  fi
  # Script executed on the VM. Variables are passed explicitly; the password is generated on the spot.
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
  echo "ERROR: branch '$BRANCH' has no docker/initdb (merge the database PR or set BRANCH)." >&2
  exit 1
fi

if [ -f .env ]; then
  echo ".env already exists: left unchanged."
else
  cp example.env .env
  PASS="$(openssl rand -base64 24 | tr -d '/+=\n')"
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${PASS}/" .env
  chmod 600 .env
  echo "Created .env with a random password (not printed)."
fi

sudo docker compose --env-file .env -f docker/docker-compose.yml up -d postgis

set -a; . ./.env; set +a
for _ in $(seq 1 30); do
  sudo docker exec spatial_postgis pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1 && break
  sleep 2
done
sudo docker exec spatial_postgis psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\dt raw.*'
REMOTE
  echo "Done. Database access: scripts/provision_vm.sh tunnel"
}

cmd_deploy() {
  vm_exists || die "VM '$VM_NAME' does not exist (run create first)"
  [ "$(vm_status)" = "RUNNING" ] || die "VM '$VM_NAME' is not running (status: $(vm_status)); run: start"
  if [ "$DRY_RUN" = "1" ]; then
    echo "[DRY_RUN] ssh to $VM_NAME: update $BRANCH, ensure AUTH_SECRET in .env, docker compose up -d --build backend, health check"
    return 0
  fi
  gcloud compute ssh "$VM_NAME" --zone "$ZONE" --command "BRANCH='$BRANCH' API_PORT='$API_PORT' bash -s" <<'REMOTE'
set -euo pipefail
DIR="$HOME/field-under-pressure-materials"
cd "$DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"
[ -f .env ] || { echo "ERROR: no .env (run setup first)." >&2; exit 1; }
if ! grep -q '^AUTH_SECRET=.\+' .env; then
  sed -i '/^AUTH_SECRET=/d' .env
  echo "AUTH_SECRET=$(openssl rand -hex 32)" >> .env
  echo "Added AUTH_SECRET to .env (not printed)."
fi
grep -q '^BACKEND_PORT=' .env || echo "BACKEND_PORT=$API_PORT" >> .env
# Public host name for HTTPS: <external-ip-with-dashes>.nip.io, unless a custom domain is already set in .env
CUR="$(grep '^PUBLIC_HOST=' .env | cut -d= -f2- || true)"
case "$CUR" in
  ""|*.nip.io)
    IP="$(curl -fsS -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip)"
    sed -i '/^PUBLIC_HOST=/d' .env
    echo "PUBLIC_HOST=$(echo "$IP" | tr . -).nip.io" >> .env ;;
esac
sudo docker compose --env-file .env -f docker/docker-compose.yml up -d --build backend caddy
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/health"; then
    echo; echo "API (HTTPS, needs the firewall rule): https://$(grep '^PUBLIC_HOST=' .env | cut -d= -f2-)/api/v1"
    exit 0
  fi
  sleep 2
done
echo "ERROR: the backend did not answer on port ${API_PORT}; see: sudo docker logs spatial_backend" >&2
exit 1
REMOTE
  echo "Done. From outside the API needs the firewall rule: API_SOURCE_RANGES=0.0.0.0/0 scripts/provision_vm.sh firewall (or use api-tunnel)"
}

cmd_firewall() {
  [ -n "${API_SOURCE_RANGES:-}" ] || die "set API_SOURCE_RANGES (comma-separated CIDR ranges allowed to reach the API; 0.0.0.0/0 for everybody); there is no default on purpose"
  if gcloud compute firewall-rules describe fup-allow-web >/dev/null 2>&1; then
    echo "Firewall rule fup-allow-web already exists; left unchanged:"
    gcloud compute firewall-rules describe fup-allow-web --format='value(sourceRanges.list(),allowed[].map().firewall_rule().list())'
    return 0
  fi
  echo "Opening TCP 80 and 443 (HTTPS in front of the API) of VMs tagged 'fup' to: $API_SOURCE_RANGES (the database port 5432 stays closed)"
  run gcloud compute firewall-rules create fup-allow-web --direction=INGRESS --action=allow \
    --rules="tcp:80,tcp:443" --source-ranges="$API_SOURCE_RANGES" --target-tags=fup \
    --description="HTTPS in front of the backend API of field-under-pressure (demo)"
}

cmd_api_tunnel() {
  vm_exists || die "VM '$VM_NAME' does not exist"
  echo "Tunnel: localhost:${API_PORT} -> ${VM_NAME}:${API_PORT} (Ctrl+C to stop). The API is then at http://localhost:${API_PORT}/api/v1 and the docs at /docs."
  if [ "$DRY_RUN" = "1" ]; then
    echo "[DRY_RUN] gcloud compute ssh $VM_NAME --zone $ZONE -- -N -L ${API_PORT}:localhost:${API_PORT}"
    return 0
  fi
  exec gcloud compute ssh "$VM_NAME" --zone "$ZONE" -- -N -L "${API_PORT}:localhost:${API_PORT}"
}

cmd_tunnel() {
  vm_exists || die "VM '$VM_NAME' does not exist"
  echo "Tunnel: localhost:${LOCAL_PORT} -> ${VM_NAME}:5432 (Ctrl+C to stop). In QGIS/psql use host localhost, port ${LOCAL_PORT}."
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
    echo "VM '$VM_NAME' does not exist in project $PROJECT."
  fi
}

cmd_power() {
  vm_exists || die "VM '$VM_NAME' does not exist"
  run gcloud compute instances "$1" "$VM_NAME" --zone "$ZONE"
}

usage() { sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; }

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    create|setup|deploy|firewall|api-tunnel|tunnel|status|start|stop) check_env ;;
    ""|-h|--help|help) usage; exit 0 ;;
    *) usage >&2; die "unknown command: $cmd" ;;
  esac
  case "$cmd" in
    create) cmd_create "$@" ;;
    setup)  cmd_setup ;;
    deploy) cmd_deploy ;;
    firewall) cmd_firewall ;;
    api-tunnel) cmd_api_tunnel ;;
    tunnel) cmd_tunnel ;;
    status) cmd_status ;;
    start)  cmd_power start ;;
    stop)   cmd_power stop ;;
  esac
}

main "$@"
