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
| `api` | FastAPI over the data repo clone (`api/main.py`). Read-only, except your saved screens (`data/screens/my_screens.json`). Places no orders, sends no pushes, uses no AI. |
| `web` | Builds `web/` to static files once, copies them into a volume, exits. |
| `data-sync` | Pulls the private data repo every 10 minutes (`PULL_EVERY`), so new runs appear without a restart. |

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

## Updating

```bash
cd /opt/trading-os/trading-os && git pull
cd deploy && docker compose up -d --build
```

The data updates itself (`data-sync`). Saved screens stay on the server's clone; pushing them
to GitHub (the Streamlit sidebar's *Save & push*) is phase 2 of the React dashboard.

## Troubleshooting

- **Charts say "No daily bars"**: the API fetches the data repo's `bars-2y` release with the
  `gh` CLI and `GH_TOKEN`; check the token's expiry and `docker compose logs api`.
- **"No data folder"**: `DATA_DIR` in `.env` must be the clone's absolute path, and the clone
  must contain `data/`.
- **Can't save a screen**: the clone must be owned by uid 1000 (step 4's `chown`).
- **Stop everything**: `docker compose down` (volumes and the data clone are kept).
