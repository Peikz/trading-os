#!/usr/bin/env bash
# Trading OS dashboard on a small cloud server (Emil, 22 Oct 2026; docs/SERVER.md).
#
# Run as root on a fresh Ubuntu 24.04 server:
#   bash install.sh             # install, or re-run safely to repair or update the setup
#   bash install.sh --lock-ssh  # afterwards: SSH only through Tailscale, nothing open publicly
#
# What it does: a user `tradingos`; git, the GitHub CLI, Tailscale and uv; the code repo and a
# slim clone of the private data repo; the dashboard as a service on 127.0.0.1:8501, shared
# only with your own devices through Tailscale; a 10-minute update timer that pulls both repos
# and restarts the dashboard after a code change; a firewall that lets nothing in except SSH
# and Tailscale.
#
# You do two things while it runs: open the Tailscale sign-in link it prints, and paste a
# GitHub token at the hidden prompt (fine-grained: Contents read and write on trading-os-data).
# The token is stored only in the GitHub CLI's login on this server, never in a file of the
# repo, and never printed.

set -euo pipefail

OWNER="${TRADING_OS_OWNER:-Peikz}"
APP_USER="tradingos"
HOME_DIR="/home/${APP_USER}"
CODE="${HOME_DIR}/Trading-OS"
DATA="${HOME_DIR}/trading-os-data"
HOSTNAME_TS="${TRADING_OS_HOSTNAME:-trading-os}"
GIT_NAME="${TRADING_OS_GIT_NAME:-Trading OS server}"
GIT_EMAIL="${TRADING_OS_GIT_EMAIL:-182818002+Peikz@users.noreply.github.com}"
PORT=8501

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
as_user() { runuser -u "${APP_USER}" -- "$@"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root (sudo bash install.sh)." >&2
  exit 1
fi

if [ "${1:-}" = "--lock-ssh" ]; then
  if ! tailscale status >/dev/null 2>&1; then
    echo "Tailscale isn't up; keeping public SSH open so you can't lock yourself out." >&2
    exit 1
  fi
  say "SSH only through Tailscale from now on"
  ufw delete allow OpenSSH >/dev/null 2>&1 || true
  ufw status verbose
  echo "Log in with: ssh root@${HOSTNAME_TS}   (Tailscale SSH; your PC must be on Tailscale)"
  exit 0
fi

say "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git curl ca-certificates ufw unattended-upgrades

if ! command -v gh >/dev/null; then
  say "GitHub CLI"
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    -o /etc/apt/keyrings/githubcli-archive-keyring.gpg
  chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
  apt-get update -q
  apt-get install -y -q gh
fi

if ! command -v tailscale >/dev/null; then
  say "Tailscale"
  curl -fsSL https://tailscale.com/install.sh | sh
fi

if ! id "${APP_USER}" >/dev/null 2>&1; then
  say "User ${APP_USER}"
  useradd --create-home --shell /bin/bash "${APP_USER}"
fi

if [ ! -x "${HOME_DIR}/.local/bin/uv" ]; then
  say "uv (Python manager)"
  as_user bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
UV="${HOME_DIR}/.local/bin/uv"

say "Firewall: nothing in except SSH and Tailscale"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw allow in on tailscale0 >/dev/null
ufw --force enable >/dev/null

if ! tailscale status >/dev/null 2>&1; then
  say "Tailscale sign-in: open the link below and sign in with the same account as your phone"
  tailscale up --ssh --hostname "${HOSTNAME_TS}"
fi

if ! as_user gh auth status >/dev/null 2>&1; then
  say "GitHub sign-in"
  echo "Paste the GitHub token for this server (hidden), then press Enter."
  echo "Fine-grained token: repository ${OWNER}/trading-os-data, Contents read and write."
  read -r -s TOKEN
  echo
  printf '%s' "${TOKEN}" | as_user gh auth login --with-token --hostname github.com
  unset TOKEN
fi
as_user gh auth setup-git --hostname github.com

if [ ! -d "${CODE}/.git" ]; then
  say "Code repo"
  as_user git clone --quiet "https://github.com/${OWNER}/trading-os.git" "${CODE}"
fi

if [ ! -d "${DATA}/.git" ]; then
  say "Data repo (slim: recent history, no daily-bar files; those come from GitHub releases)"
  as_user git clone --quiet --filter=blob:none --no-checkout \
    --shallow-since="30 days ago" "https://github.com/${OWNER}/trading-os-data.git" "${DATA}"
  as_user git -C "${DATA}" sparse-checkout set --no-cone \
    '/*' '!/data/bars/' '!/data/ep_enrich/' '/data/ep_enrich/tickers.parquet'
  as_user git -C "${DATA}" checkout --quiet main
fi
as_user git -C "${DATA}" config user.name "${GIT_NAME}"
as_user git -C "${DATA}" config user.email "${GIT_EMAIL}"

say "Python packages"
as_user bash -c "cd '${CODE}' && '${UV}' sync --quiet --frozen --group app"

say "Services"
cat > /etc/systemd/system/trading-os-dashboard.service <<EOF
[Unit]
Description=Trading OS dashboard (Streamlit, local only; shared through Tailscale)
After=network-online.target
Wants=network-online.target

[Service]
User=${APP_USER}
WorkingDirectory=${CODE}
Environment=TRADING_OS_DATA=${DATA}
Environment=TRADING_OS_CACHE=${HOME_DIR}/.cache/trading-os-cache
ExecStart=${UV} run --frozen --group app streamlit run app/streamlit_app.py --server.port ${PORT} --server.address 127.0.0.1 --server.headless true
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/trading-os-update.service <<EOF
[Unit]
Description=Trading OS: pull both repos, restart the dashboard after a code change

[Service]
Type=oneshot
ExecStart=/bin/bash ${CODE}/scripts/server/update.sh
EOF

cat > /etc/systemd/system/trading-os-update.timer <<EOF
[Unit]
Description=Trading OS update every 10 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now trading-os-dashboard.service trading-os-update.timer >/dev/null
systemctl restart trading-os-dashboard.service

say "Sharing on your tailnet only"
tailscale serve --bg --http=80 "${PORT}"

for _ in $(seq 1 30); do
  if curl -fs "http://127.0.0.1:${PORT}/_stcore/health" >/dev/null; then
    break
  fi
  sleep 2
done
if curl -fs "http://127.0.0.1:${PORT}/_stcore/health" >/dev/null; then
  NAME="$(tailscale status --json | grep -o '"DNSName": *"[^"]*"' | head -1 | cut -d'"' -f4)"
  say "Done. Open http://${NAME%.}/ on your phone (Tailscale on)."
else
  say "The dashboard didn't answer yet. See: journalctl -u trading-os-dashboard -n 50"
  exit 1
fi
