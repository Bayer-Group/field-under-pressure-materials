# Deployment

The demo runs on one virtual machine on Google Cloud: `fup-vm` in the project `geo-earth-junction`, zone `europe-central2-a`.
Docker Compose runs three services: `postgis` (the database), `backend` (FastAPI) and `caddy` (HTTPS in front of the backend).
The database port is never opened to the internet; only SSH and the HTTPS API are reachable.

Step-by-step instructions for access, the tunnel and granting access are in
[`docker/VM.md`](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/docker/VM.md);
the database itself is described in
[`docker/README.md`](https://github.com/geoearth-junction/field-under-pressure-materials/blob/team/geoearth-junction/docker/README.md).

## Access

You need a Google account added to the project by its owner, and `gcloud` (or Cloud Shell in the browser):

```bash
gcloud auth login
gcloud compute ssh fup-vm --zone europe-central2-a --project geo-earth-junction
```

On the machine, SQL needs no password: `sudo docker exec -it spatial_postgis psql -U gis_user -d spatial_db`.

## Database migrations

A new database is created from `docker/initdb/` in order. An existing database is brought up to date with the scripts in
`docker/migrations/`, applied once each, in number order:

| Migration | Adds |
| --- | --- |
| `001_raw_layers` | brings a database created before the layering to the `raw` / `app` layout |
| `002_app_farmer_input` | the `app` schema for farmer input |
| `003_curated` | the `curated` layer |
| `004_serve` | the `serve` views and the demo clock |
| `005_demo_users` | demonstration logins |
| `006_sprays_confirmed` | the answer "no sprays this season" |
| `007_parcel_locations` | place names of parcels |
| `008_grid_cells` | grid cells tiling the plane |
| `009_sandbox_counter` | the sandbox counter |
| `010_user_accounts` | user accounts |
| `011_spray_window` | the hourly weather view of the spray window |

Each migration states what it requires and whether it is safe to run again. To apply one on the VM (Linux, macOS or Cloud
Shell; on Windows see the note under "Deploying the backend"):

```bash
gcloud compute ssh fup-vm --zone europe-central2-a --project geo-earth-junction \
  --command "sudo docker exec -i spatial_postgis psql -U gis_user -d spatial_db -v ON_ERROR_STOP=1" \
  < docker/migrations/011_spray_window.sql
```

## Deploying the backend

```bash
BRANCH=team/geoearth-junction scripts/provision_vm.sh deploy
```

The script updates the repository on the VM to `BRANCH` (default `team/geoearth-junction`), adds a random `AUTH_SECRET` to the
VM's `.env` if it is missing, rebuilds and restarts `backend` and `caddy`, and waits for `/health`. The API is then at
`https://<external-ip-with-dashes>.nip.io/api/v1`. `DRY_RUN=1` prints what it would do without doing it.

Things to know:

- **Run it as the owner of the checkout.** The script works in the `$HOME` of the user who connects over SSH, where `setup`
  cloned the repository. Another team member's SSH user has no checkout there, so the deploy stops; ask the owner to deploy.
- **Deploying a feature branch changes the shared demo.** Everybody using the public API gets that branch until the next deploy.
- **Apply migrations before deploying** code that needs them.
- **Windows:** `gcloud compute ssh` on Windows (PuTTY's `plink`) can drop the beginning of a script sent on standard input, so
  the remote script fails with an error such as `y: command not found`. Run the deploy from Linux, macOS or Cloud Shell instead.

## Other commands of `scripts/provision_vm.sh`

| Command | Does |
| --- | --- |
| `create`, `setup` | creates the VM, installs Docker, clones the repository, creates `.env` with a random password, starts PostGIS |
| `start`, `stop`, `status` | controls the VM (stop it when nobody works, the disk keeps the data) |
| `tunnel` | SSH tunnel to the database: `localhost:5433` |
| `api-tunnel` | SSH tunnel to the API: `localhost:8000` |
| `firewall` | opens ports 80 and 443 for the API (`API_SOURCE_RANGES` is required, there is no default) |

The external IP is ephemeral: after a stop and start the address, and so the `nip.io` host name, changes. Switches such as
`DEMO_READONLY=1` and the sandbox limits are set in the VM's `.env` and applied with `deploy`.
