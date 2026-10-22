#!/usr/bin/env bash
# Every 10 minutes on the server (trading-os-update.timer, docs/SERVER.md): pull the data repo,
# pull the code, and after a code change sync the packages and restart the dashboard. A running
# dashboard keeps the code it started with, so new config keys would otherwise stop it.
# Runs as root; git and uv run as the app user. Prints status only.

set -uo pipefail

APP_USER="tradingos"
HOME_DIR="/home/${APP_USER}"
CODE="${HOME_DIR}/Trading-OS"
DATA="${HOME_DIR}/trading-os-data"
UV="${HOME_DIR}/.local/bin/uv"

as_user() { runuser -u "${APP_USER}" -- "$@"; }

if ! as_user git -C "${DATA}" pull --quiet --rebase --autostash; then
  echo "Data: pull failed (it tries again in 10 minutes)"
fi

before="$(as_user git -C "${CODE}" rev-parse HEAD)"
if ! as_user git -C "${CODE}" pull --quiet --ff-only; then
  echo "Code: pull failed (it tries again in 10 minutes)"
  exit 0
fi
after="$(as_user git -C "${CODE}" rev-parse HEAD)"

if [ "${before}" != "${after}" ]; then
  if as_user bash -c "cd '${CODE}' && '${UV}' sync --quiet --frozen --group app"; then
    systemctl restart trading-os-dashboard.service
    echo "Code: updated to ${after:0:7}, dashboard restarted"
  else
    echo "Code: package sync failed; the dashboard keeps running the old code"
  fi
fi
