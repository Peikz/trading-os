# Start the price-alert watcher on this PC (Emil, 22 Oct 2026): it checks every minute from
# 15:30 to 22:00 Copenhagen (the New York session) and waits quietly outside it. Keep the
# window open; Ctrl-C stops it. Keys: scripts\set_local_secrets.ps1 (once).
#   powershell -ExecutionPolicy Bypass -File scripts\start_alerts.ps1

$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
foreach ($name in "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "NTFY_TOPIC") {
    $value = [Environment]::GetEnvironmentVariable($name, "User")  # set after this shell opened
    if ($value) { Set-Item -Path "Env:$name" -Value $value }
}
$data = Join-Path (Split-Path $repo -Parent) "trading-os-data"
uv run python scripts/alert_watch.py --data-dir $data
