# The React dashboard on a server (Docker, Tailscale only)

This kit runs the new dashboard (`api/` + `web/`) on one small always-on server. It is the
Docker alternative to [docs/SERVER.md](../docs/SERVER.md) (which runs the Streamlit dashboard
as a systemd service); both keep the same rule: **reachable only from your own devices through
Tailscale, nothing open to the internet.**

What runs (`deploy/docker-compose.yml`):

| Service | What it does |
|---|---|
| `tailscale` | Joins your tailnet as `<TS_HOSTNAME>`. The only way in. |
| `caddy` | Serves the built React app and sends `/api/*` to the API. Shares the Tailscale container's network, so it listens only on the tailnet. No `ports:` are published. |
| `api` | FastAPI over the data repo clone (`api/main.py`). Writes only what the Streamlit dashboard writes (journal, plans, grades, notes, watchlists, alerts, drawings, screens) and pushes it on *Save & push*. Places no orders, sends no pushes, uses no AI. |
| `web` | Builds `web/` to static files once, copies them into a volume, exits. |
| `data-sync` | Pulls the private data repo every 10 minutes (`PULL_EVERY`), so new runs appear without a restart. |
| `alerts` | Price alerts (`scripts/alert_server.py`): from 09:25 New York to the close of each regular NYSE session (13:00 on an early close; weekends and XNYS holidays skipped), the same watcher as the GitHub job, then commits and pushes what fired. **Off** until `ALERTS_ENABLED=true` (see [Price alerts on the server](#price-alerts-on-the-server)). Places no orders. |

The API, `data-sync` and `alerts` share one data repo clone. Every git pull and push takes the
clone's lock (`.git/trading-os-git.lock`, `trading_os/gitlock.py`; `data-sync.sh` uses
`flock` on the same file), so two of them never run git at once.

Everything below uses placeholders: `<server-ip>`, `<your-tailnet>`, `<owner>`. Never commit
real values; secrets live only in `deploy/.env` on the server.

Cost: a Hetzner CX22-class box (2 vCPU, 4 GB RAM, 40 GB disk) is about €4–5 a month.

## 1. The server

1. Hetzner Cloud → a new project → **Security → SSH keys**: add your public key.
2. **Add server**: Ubuntu 24.04, Shared vCPU x86 **CX22** (or the current equivalent), any EU
   location, public IPv4 on (needed to reach GitHub and Docker Hub), your SSH key, no password.
3. **Firewalls → Create firewall**: inbound rule **SSH (22) only**, for now. Attach it to the
   server. (Step 6 removes even that.)

## 2. Base packages

```bash
ssh root@<server-ip>
apt-get update && apt-get -y upgrade
apt-get install -y git ca-certificates curl
curl -fsSL https://get.docker.com | sh
```

## 3. Tokens (both pasted only into `deploy/.env` on the server)

- **GitHub**: Settings → Developer settings → Fine-grained tokens → Generate. Repository access:
  only `trading-os-data`. Permissions: **Contents: Read and write**. Expiry up to a year
  (note the date).
- **Tailscale**: admin console → Settings → Keys → **Generate auth key**: not reusable,
  pre-approved. It is used once; the `tailscale-state` volume keeps the login afterwards.

## 4. The code and the data

```bash
mkdir -p /opt/trading-os && cd /opt/trading-os
git clone https://github.com/<owner>/trading-os.git
read -rsp "GitHub token: " GH_TOKEN && echo
git -c credential.helper='!f() { echo username=x-access-token; echo "password='"$GH_TOKEN"'"; }; f' \
  clone --filter=blob:limit=5m https://github.com/<owner>/trading-os-data.git
chown -R 1000:1000 /opt/trading-os/trading-os-data   # the containers run as uid 1000
unset GH_TOKEN
```

The token is not saved in the clone's config: git gets it from the one-off helper above, and
the `data-sync` service passes it the same way from `deploy/.env`.

## 5. Configure and start

```bash
cd /opt/trading-os/trading-os/deploy
cp .env.example .env && chmod 600 .env
nano .env        # TS_AUTHKEY, TS_HOSTNAME, GH_TOKEN, DATA_DIR=/opt/trading-os/trading-os-data
docker compose up -d --build
docker compose ps    # web: exited (0) is expected; the rest: running
docker compose logs --tail 20 api data-sync
```

Open `http://<TS_HOSTNAME>.<your-tailnet>.ts.net/` on the phone or PC with Tailscale on. On
the iPhone: Share → **Add to Home Screen**. A push link to Today with `?t=…` works the same
way (`http://<TS_HOSTNAME>.<your-tailnet>.ts.net/?t=…#/today`).

Check that nothing is public: from a machine **without** Tailscale,
`curl -m 5 http://<server-ip>/` must time out. `docker compose ps` must show no
`0.0.0.0:` port mappings.

## 6. Close public SSH

Install Tailscale on the host too (`curl -fsSL https://tailscale.com/install.sh | sh` then
`tailscale up --ssh`), check `ssh root@<host-tailscale-name>` works from your PC, then delete
the SSH rule from the Hetzner firewall. The server now accepts nothing from the internet.

## Price alerts on the server

Today the price alerts run in GitHub Actions (`.github/workflows/alerts.yml`), started twice a
session by the cron-job.org timer. The `alerts` service does the same job on the server in one
process, and is **off** until you switch it on. Never run both: each would push every alert,
so you would get two of each and two commits of what fired. Do these steps in order, on a
weekday evening or a weekend (outside 09:25–16:00 New York).

1. **Keys on the server.** In `deploy/.env` set `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`
   and `NTFY_TOPIC` to the same values as the code repo's Actions secrets of the same names.
   `GH_TOKEN` is already there (it pushes what fired). Keep `ALERTS_ENABLED=false` for now.
2. **Check the service.** It should log that it is off and when the next watch is:

   ```bash
   cd /opt/trading-os/trading-os/deploy
   docker compose up -d --build alerts
   docker compose logs --tail 5 alerts        # "Alerts server: off; next watch ..."
   ```

   Don't test with `alert_watch.py --once` here: even with `--no-push` it records what it
   finds as fired in the clone, and the service would then commit that and skip those alerts.
3. **Switch the GitHub job off.** Two places, both by hand:
   - At cron-job.org, disable the two jobs titled `trading-os: alerts 09:25 ET` and
     `trading-os: alerts 12:45 ET` (they start `alerts.yml`). Disabling, not deleting, keeps
     the way back open.
   - Later, in a commit to the code repo: remove the two `alerts` `TimerJob` entries in
     `trading_os/timer.py` (`scripts/timer_setup.py` would otherwise re-create the jobs at
     cron-job.org, and the System health page would report them as missed), and then
     `alerts.yml` itself, or keep it as a `workflow_dispatch`-only fallback.
4. **Switch the server on.** In `deploy/.env` set `ALERTS_ENABLED=true`, then
   `docker compose up -d alerts`. `docker compose logs --tail 5 alerts` now says `on`.
5. **The first session.** At 09:25 New York the log says `watching until 16:00 NY`, then
   `watching N {...}` every 5 minutes; after the close `Data: committed and pushed` (or
   `nothing new to commit`). The data repo's history shows `alerts <date>: fired (server)`.

To go back: `ALERTS_ENABLED=false` and `docker compose up -d alerts`, then re-enable the two
cron-job.org jobs. A failed watch restarts after a minute; missing keys stop the container
(`docker compose ps` shows it restarting, and its log says which).

## Updating

```bash
cd /opt/trading-os/trading-os && git pull
cd deploy && docker compose up -d --build
```

The data updates itself (`data-sync`). What you write in the dashboard (journal, plans, grades,
notes, watchlists, alerts, chart drawings, screens) lands in the server's clone; **Save & push**
in the header commits and pushes it to the data repo, through the same `GH_TOKEN` (a
credential helper set in `docker-compose.yml`; the token is never written to disk).
**Pull latest** pulls at once instead of waiting for `data-sync`.

The **Scans** page is view-only on the server: `config/scans.yaml` is part of the API image,
not a writable checkout of the code repo, and `GH_TOKEN` only reaches the data repo. Edit
scans on the PC (Streamlit), commit, then update the server as above.

## Troubleshooting

- **Charts say "No daily bars"**: the API fetches the data repo's `bars-2y` release with the
  `gh` CLI and `GH_TOKEN`; check the token's expiry and `docker compose logs api`.
- **"No data folder"**: `DATA_DIR` in `.env` must be the clone's absolute path, and the clone
  must contain `data/`.
- **Can't save a screen**: the clone must be owned by uid 1000 (step 4's `chown`).
- **Stop everything**: `docker compose down` (volumes and the data clone are kept).
