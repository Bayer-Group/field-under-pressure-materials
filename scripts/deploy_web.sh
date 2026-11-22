#!/usr/bin/env bash
# Deploys the front end (web/) to Cloud Run as an nginx container (see docker/web/ and docs/WEB_DEPLOY.md).
# Every gcloud command is printed before it runs, so it can also be pasted by hand.
#
#   scripts/deploy_web.sh check     read-only: account, project, enabled APIs, the service
#   scripts/deploy_web.sh enable    enable the APIs Cloud Run needs (run, cloudbuild, artifactregistry)
#   scripts/deploy_web.sh deploy    build the image from web/ and deploy the service
#   scripts/deploy_web.sh status    URL, revision and settings of the service
#
# Settings (environment): PROJECT, REGION, SERVICE, CONFIG (gcloud configuration), MIN_INSTANCES, MAX_INSTANCES, MEMORY, CPU,
# CONCURRENCY, API_UPSTREAM, FRONT_API_URL, TILE_CACHE. DRY_RUN=1 prints the commands without running them.
set -euo pipefail

PROJECT="${PROJECT:-geo-earth-junction}"
REGION="${REGION:-europe-central2}"
SERVICE="${SERVICE:-fup-web}"
CONFIG="${CONFIG:-geoearth}"
MIN_INSTANCES="${MIN_INSTANCES:-1}"
MAX_INSTANCES="${MAX_INSTANCES:-10}"
MEMORY="${MEMORY:-1Gi}"
CPU="${CPU:-1}"
CONCURRENCY="${CONCURRENCY:-200}"
API_UPSTREAM="${API_UPSTREAM:-}"
FRONT_API_URL="${FRONT_API_URL:-}"
TILE_CACHE="${TILE_CACHE:-1}"
DRY_RUN="${DRY_RUN:-0}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CLOUDSDK_ACTIVE_CONFIG_NAME="$CONFIG"   # for this script only; the active configuration is not changed

run() {
  echo "+ $*" >&2
  [ "$DRY_RUN" = "1" ] || "$@"
}

# the libraries index.html loads from unpkg.com: name, URL, SHA-256 (the image serves them from /vendor/)
VENDOR=(
  "maplibre-gl.css|https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.css|731181d400d65a8b09d842f55b70bc4dc11010b15b8549e2c65a69d233fbdd2e"
  "maplibre-gl.js|https://unpkg.com/maplibre-gl@3.6.2/dist/maplibre-gl.js|c46084df69bbaa995b301a515274a86ec53905c78459b80dccbc27a0c0b8d13b"
  "turf.min.js|https://unpkg.com/@turf/turf@7.1.0/turf.min.js|c45af4551952fa41f0493cf48c3539b1800774f2abfc031ec6af72accf18be9f"
)

cmd_check() {
  run gcloud config get-value account
  run gcloud services list --project "$PROJECT" --enabled --format="value(config.name)" --filter="config.name:(run OR cloudbuild OR artifactregistry)"
  run gcloud run services list --project "$PROJECT" --region "$REGION"
}

cmd_enable() {
  run gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project "$PROJECT"
}

stage() {
  local dir="$1" entry name url sum
  mkdir -p "$dir/site/vendor" "$dir/docker"
  # only what the browser needs (no *.md, no mock-qgis-server.cjs)
  cp "$ROOT/web/index.html" "$ROOT"/web/*.js "$dir/site/"
  for entry in "${VENDOR[@]}"; do
    IFS='|' read -r name url sum <<<"$entry"
    curl -fsSL --retry 3 -o "$dir/site/vendor/$name" "$url"
    echo "$sum  $dir/site/vendor/$name" | sha256sum -c - >/dev/null || { echo "checksum of $name does not match" >&2; exit 1; }
  done
  cp "$ROOT/docker/web/Dockerfile" "$dir/Dockerfile"
  cp "$ROOT/docker/web/40-web-config.sh" "$dir/docker/"
}

cmd_deploy() {
  local env_vars
  stage_dir="$(mktemp -d "${TMPDIR:-$HOME/.cache}/fup-web.XXXXXX")"   # global: the EXIT trap runs after this function has returned
  trap 'rm -rf "${stage_dir:-}"' EXIT
  stage "$stage_dir"
  echo "staged $(du -sh "$stage_dir" | cut -f1) in $stage_dir" >&2

  env_vars="TILE_CACHE=${TILE_CACHE}"
  [ -z "$API_UPSTREAM" ] || env_vars="$env_vars,API_UPSTREAM=${API_UPSTREAM}"
  [ -z "$FRONT_API_URL" ] || env_vars="$env_vars,FRONT_API_URL=${FRONT_API_URL}"

  run gcloud run deploy "$SERVICE" \
    --project "$PROJECT" --region "$REGION" \
    --source "$stage_dir" \
    --allow-unauthenticated \
    --port 8080 \
    --cpu "$CPU" --memory "$MEMORY" --concurrency "$CONCURRENCY" \
    --min-instances "$MIN_INSTANCES" --max-instances "$MAX_INSTANCES" \
    --timeout 60 \
    --set-env-vars "$env_vars"
  cmd_status
}

cmd_status() {
  run gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --format="value(status.url, status.latestReadyRevisionName, spec.template.spec.containerConcurrency, spec.template.metadata.annotations)"
}

case "${1:-}" in
  check)  cmd_check ;;
  enable) cmd_enable ;;
  deploy) cmd_deploy ;;
  status) cmd_status ;;
  *) sed -n '2,13p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
