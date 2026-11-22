# The database machine (GCP): how to use it

The PostGIS database runs in Docker on the virtual machine `fup-vm` in the GCP project `geo-earth-junction`
(zone `europe-central2-a`). Description of the database itself: [`README.md`](README.md).

The commands below always pass `--project geo-earth-junction --zone europe-central2-a` explicitly,
so nothing has to be configured in `gcloud` beforehand.

## What you need

1. **A regular Google account** (e.g. Gmail). You do not need to create a separate "GCP account" or enter a card.
   The machine's cost is billed to the project's billing account.
2. **Access granted by the project owner** (see "For the owner" at the end).
3. **`gcloud` on your computer** ([installation](https://cloud.google.com/sdk/docs/install)) and a one-time login:
   ```bash
   gcloud auth login
   ```
   Alternative without installing anything: **Cloud Shell**, a terminal in the browser (`console.cloud.google.com`,
   terminal icon in the top right, select project `geo-earth-junction`). `gcloud` is available there right away. It is
   enough for SSH into the machine and working on the database from there, but not for QGIS (see "Tunnel").

## Basic commands

```bash
# check the state (RUNNING = on, TERMINATED = stopped)
gcloud compute instances list --project geo-earth-junction

# start the machine
gcloud compute instances start fup-vm --zone europe-central2-a --project geo-earth-junction

# SSH into the machine (a regular shell; the first time it creates an SSH key, the key passphrase can stay empty)
gcloud compute ssh fup-vm --zone europe-central2-a --project geo-earth-junction

# stop the machine when you are not working (saves credits; data on the disk stays)
gcloud compute instances stop fup-vm --zone europe-central2-a --project geo-earth-junction
```

A stopped machine means the database is unavailable. `start` before you work, `stop` afterwards (if nobody else is using it).

## The database starts with the machine

The database container has `restart: unless-stopped`, so it comes back by itself after `start`. Check with
`sudo docker ps` after SSH-ing in (`spatial_postgis` should be `Up`).

If the container was created before this setting was added (policy `no`), fix it once on the machine, without
recreating the database:

```bash
sudo docker update --restart unless-stopped spatial_postgis
sudo docker start spatial_postgis      # only if it is not running right now
```

## Working on the database without a tunnel (directly on the machine)

After SSH-ing in you can write SQL right away, with no extra configuration and no password:

```bash
sudo docker exec -it spatial_postgis psql -U gis_user -d spatial_db
```
Inside: `\dt raw.*` (list tables), `SELECT count(*) FROM raw.weather_hourly;`, `\q` (quit).

This is enough for inspecting data, checks after loading and simple fixes.

## Tunnel: what it is for

The database port (5432) on the machine is **deliberately closed to the internet**. If it were open, anyone could try
to guess the database password. Only SSH (port 22) is open, protected by Google accounts.

A tunnel is an SSH connection that also "forwards" a port: whatever you open on your computer at `localhost:5433`
reaches the database on the machine through SSH. Programs running **on your computer** (QGIS, `psql`, the data loading
script, a locally running backend) can then connect to the database as if it were local, while the database stays
invisible from the internet.

**You need the tunnel only when you want to use the database from a program on your own computer.** For plain SQL,
SSH from the section above is enough.

### How to open the tunnel

```bash
gcloud compute ssh fup-vm --zone europe-central2-a --project geo-earth-junction -- -N -L 5433:localhost:5432
```
- The command **keeps running and prints nothing**. This is normal: the tunnel is working. Leave that window open.
- Work in a **second terminal or in QGIS**, connecting to `localhost:5433`.
- To close the tunnel: Ctrl+C in that window.
- Port 5433 is used so it does not clash with a local database on 5432.

### Connecting through the tunnel

| Parameter | Value |
| --- | --- |
| host | `localhost` |
| port | `5433` |
| database | `spatial_db` |
| user | `gis_user` |
| password | from the machine owner (it is not in the repo) |
| schema | `raw` (organizer data), `app` (farmer data) |

Test from a console (it asks for the password):
```bash
psql -h localhost -p 5433 -U gis_user spatial_db -c '\dt raw.*'
```
Without a local `psql`: `docker run --rm -it --network host postgres:15 psql -h localhost -p 5433 -U gis_user spatial_db`.

**QGIS:** Layer → Data Source Manager → PostgreSQL → New connection: host `localhost`, port `5433`, database
`spatial_db`, user and password as above.

## Backend API on the VM

The backend (FastAPI, `docker/backend.Dockerfile`) runs as the compose service `backend` next to the database and reads it over
the internal compose network, so the database port stays closed. The owner deploys it with `scripts/provision_vm.sh deploy`
(updates the code, adds `AUTH_SECRET` to the VM's `.env` if missing, builds and starts only `backend`, checks `/health`). Before the
first deploy, apply the database migrations (`docker/migrations/003`-`005`) and, for the demo logins, run
`scripts/generate_mock_farmers.py`. Endpoints and logins: `docs/serve_read_contract.md`; interactive documentation at `/docs`.

The API is served over **HTTPS** by the compose service `caddy` (automatic certificate for `PUBLIC_HOST`, which `deploy` sets to
`<external-ip-with-dashes>.nip.io`; a custom domain in `.env` is kept). Two ways to reach it:
- **Open ports 80 and 443** (the demo): `API_SOURCE_RANGES=0.0.0.0/0 scripts/provision_vm.sh firewall` (rule `fup-allow-web`, no default
  range on purpose; the database port is never opened). Then use `https://<PUBLIC_HOST>/api/v1`; it also works from a page on another
  host and from `http://localhost` (CORS allows any origin, no cookies are used).
- **SSH tunnel** (no firewall change, needs access to the project): `scripts/provision_vm.sh api-tunnel`, then use
  `http://localhost:8000/api/v1` (the backend listens only on the VM's localhost).

The external IP of the VM is ephemeral: after a stop and start the address changes (and the certificate is requested again). Do not
stop the VM before a demo; reserve a static IP or use a domain to make the address permanent. Switches in the VM's `.env`:
`DEMO_READONLY=1` (nobody saves anything, visitors get a read-only view), `SANDBOX_TTL_HOURS`, `SANDBOX_MAX_OWNERS`,
`MAX_AREAS_SANDBOX`, `MAX_AREA_HA`, `WEB_CONCURRENCY`, `SANDBOX_TEMPLATES` (comma-separated example farms a sandbox copies, empty:
all of them); apply with `scripts/provision_vm.sh deploy`. Load test:
`python scripts/load_test_api.py --base https://<PUBLIC_HOST> --users 100 --ramp 15` (100 people in 15 s: p95 0.4 s, no errors).

## Who needs the tunnel (and who does not)

Only people and programs that talk to the database **directly**: the person loading data, someone debugging the
database, a backend started on a laptop for development, QGIS reading PostGIS tables directly. The web viewer and the
QGIS plugin are meant to talk to the **backend over HTTP**, not to the database, so they do not need a tunnel once the
backend is available at an address (see the backend/VM issue).

## Password and safety

- The database password is generated on the machine and stored only in the `.env` file there. You get it from whoever set
  the machine up, through a private channel (not a general Discord channel, not an issue, not the repo).
- Do not open port 5432 in the GCP firewall and do not store passwords in the repo.
- Do not leave the machine running without a reason (it uses the trial account's credits).

## For the owner: granting a colleague access

For each Google account (replace the address):
```bash
for ROLE in roles/compute.instanceAdmin.v1 roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding geo-earth-junction \
    --member="user:COLLEAGUE_EMAIL" --role="$ROLE"
done
```
These roles allow SSH into the machine as well as starting and stopping it. To remove access:
`gcloud projects remove-iam-policy-binding geo-earth-junction --member="user:COLLEAGUE_EMAIL" --role=ROLE`.

The script `scripts/provision_vm.sh` (create, set up, tunnel) is described in [`README.md`](README.md).
