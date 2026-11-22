# Deploying the front end (Cloud Run)

The front end (`web/`, static files, no build step) runs as an nginx container on Cloud Run:
service `fup-web`, project `geo-earth-junction`, region `europe-central2`. The address is stable:
`https://fup-web-1039876972059.europe-central2.run.app`.

## What the image does

- Serves the files of `web/` (`index.html` and the `*.js` files; no `*.md`, no mock server).
- Serves the three libraries `index.html` loads from unpkg.com (MapLibre GL 3.6.2, Turf 7.1.0) from `/vendor/`, checked against a pinned
  SHA-256, so the demo does not depend on a third-party CDN.
- Proxies `/api/` to the API on the VM, and rewrites the API address in the front end code to `/api/v1`. The phone talks to one domain
  only: nothing else for the network of the room to block, no CORS.
- Proxies OpenStreetMap tiles through a cache (`/osm/z/x/y.png`, only tile paths are accepted). Many people look at the same area, so
  most tiles are cache hits and the public OSM servers see little load.

## Deploy

```bash
scripts/deploy_web.sh check     # read-only: account, enabled APIs, the service
scripts/deploy_web.sh enable    # once per project: run, cloudbuild, artifactregistry
scripts/deploy_web.sh deploy    # builds the image from web/ (Cloud Build) and deploys
scripts/deploy_web.sh status
```

Every `gcloud` command is printed before it runs. The script uses the gcloud configuration `geoearth` for its own commands only
(`CONFIG=...` to change it) and does not change the active one. `DRY_RUN=1` prints without running.

Defaults: `min-instances 1` (no cold start for the first scan), `max-instances 10` (a cost cap), 1 vCPU, 1 GiB (the tile cache lives in
memory), concurrency 200. Override with `MIN_INSTANCES`, `MAX_INSTANCES`, `MEMORY`, `CPU`, `CONCURRENCY`. Set `MIN_INSTANCES=0` after the
event to stop paying for an idle instance.

The first build needed `roles/cloudbuild.builds.builder` for the default compute service account
(`<project-number>-compute@developer.gserviceaccount.com`), granted once by the project owner.

## When the VM's address changes

The external IP of `fup-vm` is ephemeral (see `docker/VM.md`). The proxy target is an environment variable, so no rebuild is needed:

```bash
gcloud run services update fup-web --project geo-earth-junction --region europe-central2 \
  --update-env-vars API_UPSTREAM=https://<new-ip-with-dashes>.nip.io,FRONT_API_URL=https://<old-host>/api/v1
```

`FRONT_API_URL` is the API address written in `web/sandbox-client.js` (the text that gets replaced by `/api/v1`); change it only if that
file changes. `TILE_CACHE=0` makes the browser ask OpenStreetMap directly.

## Notes

- `index.html` and the `*.js` files are served with `Cache-Control: no-cache` (their names carry no version), `/vendor/` with a long cache.
- `/healthz` is reserved by Cloud Run and answers 404 from outside; the container serves it internally.
- The service is public (`--allow-unauthenticated`); the front end has no secrets.
