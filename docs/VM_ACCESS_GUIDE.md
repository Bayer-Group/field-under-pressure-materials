# Working with the project VM: a guide for the team

One virtual machine, `fup-vm`, runs the whole demo environment: the PostGIS database, the backend API and the HTTPS proxy. This guide
gets you from nothing to being able to look at it, change it and deploy a fix **yourself**, alone or with an AI agent, without
waiting for the owner. Background and the database itself: [`docker/VM.md`](../docker/VM.md), [`docker/README.md`](../docker/README.md).

| | |
| --- | --- |
| GCP project | `geo-earth-junction` |
| VM, zone | `fup-vm`, `europe-central2-a` |
| gcloud configuration name used by the scripts | `geoearth` |
| API (public, HTTPS) | `https://34-118-11-71.nip.io/api/v1` (docs at `/docs`) |
| On the VM | repo in `~/field-under-pressure-materials`, containers `spatial_postgis`, `spatial_backend`, `spatial_caddy` |

## 0. Do you need the VM at all?

Most of the time **no**. To use the data from the front end or QGIS you only need the public API and a sandbox token
(`docs/serve_read_contract.md`). You need the VM when you must **see the logs, look into the database, apply a migration or deploy a
fix** that your feature depends on.

## 1. What you need

1. A **Google account** (Gmail is fine). Give its e-mail to the project owner: access is granted to that exact address. No card, no
   separate "GCP account".
2. A terminal: Linux, macOS, or Windows with **WSL2** (use the Linux steps inside WSL).
3. The repo cloned (`git clone https://github.com/geoearth-junction/field-under-pressure-materials.git`).

## 2. Install and set up gcloud (once, about 10 minutes)

Install ([official guide](https://cloud.google.com/sdk/docs/install)):

```bash
# Linux / WSL2
curl https://sdk.cloud.google.com | bash && exec -l $SHELL
# macOS
brew install --cask google-cloud-sdk
```

Log in with the account the owner granted (a browser opens; on a machine without a browser add `--no-launch-browser`):

```bash
gcloud auth login
```

Create a **separate configuration** for this project, so that your other GCP projects stay untouched. Use exactly the name
`geoearth`: `scripts/provision_vm.sh` uses it by default.

```bash
gcloud config configurations create geoearth          # this also activates it
gcloud config set account YOUR_EMAIL@gmail.com
gcloud config set project geo-earth-junction
gcloud config set compute/zone europe-central2-a
gcloud config set compute/region europe-central2
gcloud config configurations activate default         # go back to your usual one (optional)
```

From now on, either add `--configuration=geoearth` to a `gcloud` command or set it for the shell:
`export CLOUDSDK_ACTIVE_CONFIG_NAME=geoearth`. The repo scripts do it for you. **Do not change the active configuration of
somebody else's other projects.**

## 3. Check that it works

```bash
gcloud compute instances list --configuration=geoearth        # fup-vm  RUNNING
scripts/provision_vm.sh status                                # the same through the project script
gcloud compute ssh fup-vm --zone europe-central2-a --configuration=geoearth   # a shell on the VM; "exit" to leave
```

The first `ssh` creates an SSH key for you (leave the passphrase empty) and may take a minute before the key is accepted.

| You see | Meaning and what to do |
| --- | --- |
| `Required 'compute.instances.get' permission` or `403` | the owner has not granted your account yet, or you logged in with another e-mail (`gcloud auth list`) |
| `Permission denied (publickey)` right after the first try | wait a minute and retry; if it persists, tell the owner |
| `Could not fetch resource` / wrong project | `gcloud config list --configuration=geoearth` must show your account and `geo-earth-junction` |
| `gcloud: command not found` | restart the terminal; on WSL2 install gcloud inside WSL, not in Windows |
| the VM is `TERMINATED` | **do not start it on your own initiative without telling the team**; see section 6 |

## 4. Everyday use

```bash
# the state of the machine and the containers
scripts/provision_vm.sh status
gcloud compute ssh fup-vm --zone europe-central2-a --configuration=geoearth \
  --command 'sudo docker ps --format "{{.Names}}: {{.Status}}"'

# logs: the backend, and who called the API (Caddy access log; it survives backend redeploys)
gcloud compute ssh fup-vm --zone europe-central2-a --configuration=geoearth \
  --command 'sudo docker logs --tail 100 spatial_backend'
gcloud compute ssh fup-vm --zone europe-central2-a --configuration=geoearth \
  --command 'sudo docker logs spatial_caddy 2>&1 | grep http.log.access | tail -20'

# the database from your laptop (QGIS, psql, a backend run locally): open the tunnel in one terminal and leave it open
scripts/provision_vm.sh tunnel                 # localhost:5433 -> the database on the VM

# the API without the public address (a debug option)
scripts/provision_vm.sh api-tunnel
```

**Database password.** It lives only in `~/field-under-pressure-materials/.env` on the VM. Never print it into a chat, an issue or a
log, never commit it. Put it into an environment variable without showing it:

```bash
export PGPASSWORD="$(gcloud compute ssh fup-vm --zone europe-central2-a --configuration=geoearth \
  --command "grep '^POSTGRES_PASSWORD=' ~/field-under-pressure-materials/.env | cut -d= -f2-" 2>/dev/null)"
psql -h localhost -p 5433 -U gis_user -d spatial_db          # with the tunnel open
```

Without a tunnel, directly on the VM: `sudo docker exec -it spatial_postgis psql -U gis_user -d spatial_db`.

## 5. How to put your change on the VM (the rules that keep the shared environment working)

The VM is **one shared environment**. Several people changing it at once is the main thing that can go wrong, so:

1. **Develop and test locally first.** Run the backend on your laptop against the database through the tunnel (`DATABASE_URL`, see
   `backend/AGENTS.md`). This does not touch the VM at all.
2. **Never edit files on the VM.** `deploy` runs `git pull --ff-only` there; a hand edit breaks it. Change the repo, push, deploy.
3. **Deploy only merged code**, from the team branch: `scripts/provision_vm.sh deploy` (updates the code, rebuilds and restarts the
   backend and Caddy, checks `/health`; about a minute, the API is briefly unavailable).
4. If you must try an unmerged branch on the VM, **say so in the team chat first**, then
   `BRANCH=your-branch scripts/provision_vm.sh deploy`, test, and **put `team/geoearth-junction` back right after** (plain `deploy`).
   Somebody else's test may be running.
5. **Database changes are migrations**, never hand-typed `ALTER`/`DELETE` on shared data: a file `docker/migrations/00N_name.sql`
   (idempotent, see the existing ones), the same change in `docker/initdb/`, applied once with `psql -f` through the tunnel
   (`psql ... -v ON_ERROR_STOP=1 -f docker/migrations/00N_name.sql` from the repo root). Say which one you applied.
6. `scripts/generate_mock_farmers.py` **deletes and recreates all mock data** (and running sandboxes). Ask the owner before you run it.
7. A bug in the data of the demo (wrong colour, missing parcel) is fixed in the generator or the API and redeployed, not by editing
   rows by hand, so the next regeneration does not bring it back.

## 6. Do not

- **Stop, delete or resize the VM** (`stop`, `delete`). The address of the API is tied to the external IP, which changes after a stop
  and start (the certificate is requested again, and everybody's configuration breaks). Ask the owner.
- Open port 5432 or any other port in the firewall, change IAM roles, or touch billing.
- `docker compose down -v`, `docker volume rm`, `docker system prune`, `DROP`, `TRUNCATE` or an unbounded `DELETE` on the database.
- Change the active gcloud configuration of your other projects, or put credentials, `.env` or tokens into the repo or the chat.
- Run heavy loops against the public API (the load test `scripts/load_test_api.py` is for agreed moments only).

## 7. Working with an agent (Claude Code or similar)

The agent uses **your** gcloud login on your machine, so it can do what you can. Give it the rules before the first command: put
this in your personal, **not committed** `CLAUDE.local.md` (or the equivalent of your tool):

```markdown
## VM (GCP) rules
- Read docs/VM_ACCESS_GUIDE.md and docker/VM.md before touching the VM.
- Use `--configuration=geoearth` (or CLOUDSDK_ACTIVE_CONFIG_NAME=geoearth) on every gcloud command; never switch the active config.
- Reads (list, status, docker ps, logs, SELECT) are fine. ASK ME FIRST before: deploy, any migration or write to the database,
  restart of a container, anything that stops, deletes or resizes the VM, firewall, IAM, billing.
- NEVER: docker compose down -v, volume removal, DROP/TRUNCATE/unbounded DELETE, opening port 5432, printing .env or passwords.
- Deploy only team/geoearth-junction; for a branch ask me and the team first and put team back afterwards.
- Database password only via an environment variable, never in output.
```

A good prompt for a typical job: *"My feature needs a fix in the API that I merged. Read docs/VM_ACCESS_GUIDE.md, check the state of
the VM and its containers, deploy the team branch, and show me the health check and the last backend log lines."*

## 8. If something breaks

1. `scripts/provision_vm.sh status`, then the backend and Caddy logs (section 4), then `curl https://34-118-11-71.nip.io/health`.
2. A bad deploy: `scripts/provision_vm.sh deploy` again from the last good commit (`BRANCH=...` with the commit's branch), or tell the
   owner. The database is not touched by `deploy`, and its data is on a Docker volume that survives container restarts.
3. Say it in the team chat. A short note ("deployed X at 14:20, the backend restarted") saves everybody an hour.

## For the owner

Grant access for each e-mail (the two roles are enough for SSH, deploy and tunnels; OS Login is not enabled on the project, so
`gcloud compute ssh` puts the person's key into the metadata):

```bash
for EMAIL in colleague1@gmail.com colleague2@gmail.com; do
  for ROLE in roles/compute.instanceAdmin.v1 roles/iam.serviceAccountUser; do
    gcloud projects add-iam-policy-binding geo-earth-junction --member="user:$EMAIL" --role="$ROLE" --condition=None
  done
done
# remove: gcloud projects remove-iam-policy-binding geo-earth-junction --member="user:EMAIL" --role=ROLE
# check who has what: gcloud projects get-iam-policy geo-earth-junction --flatten="bindings[]" --format="table(bindings.role, bindings.members)"
```

**What this really gives.** `instanceAdmin.v1` can also stop and delete the VM. Anybody who can SSH to the VM can read the access token
of the VM's service account from the metadata server, and the default compute service account of this project has the **Editor** role
(`roles/editor`): in practice each teammate with SSH gets Editor-level power over the project (create resources, spend credits,
delete things; not change IAM). Two ways to narrow it, both the owner's decision: (a) remove the Editor role from the VM's service
account (the VM does not call GCP APIs): `gcloud projects remove-iam-policy-binding geo-earth-junction
--member=serviceAccount:<number>-compute@developer.gserviceaccount.com --role=roles/editor`; (b) switch to OS Login with
`roles/compute.osAdminLogin` plus `roles/compute.viewer` (they can work on the VM but cannot stop or delete it). Until then the rules
of section 6 are the protection.

Also open: a budget alert on the billing account (the billing API is not enabled in this project), a stable address for the API (a
static IP or a domain) and who may start and stop the VM (issue #22).
