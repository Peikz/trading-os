#!/bin/sh
# Pull the private data repo on a timer (deploy/docker-compose.yml, service data-sync).
# Logs status only: never file names, tickers or anything from the repo.
set -eu
# The token comes from the environment through this helper; nothing is stored on disk.
# shellcheck disable=SC2016
git config --global credential.helper '!f() { echo username=x-access-token; echo "password=${GH_TOKEN}"; }; f'
while true; do
  if git -C /data pull --quiet --rebase --autostash >/dev/null 2>&1; then
    echo "$(date -u +%FT%TZ) data repo pulled"
  else
    echo "$(date -u +%FT%TZ) data repo pull failed (will retry)"
  fi
  sleep "${PULL_EVERY:-600}"
done
