# Start the React dashboard next to Streamlit: the API and the built app on ONE port (8600), on
# this PC only (127.0.0.1). It builds web/ first when web/dist is missing or older than web/src.
# Streamlit and its port 8501 are untouched (scripts\start_dashboard.ps1).
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\start_web.ps1
# The data repo is env TRADING_OS_DATA, else ..\trading-os-data next to this checkout.

$repo = Split-Path $PSScriptRoot -Parent
$web = Join-Path $repo "web"
$port = 8600
Set-Location $repo

# Rebuild when the app is missing or a source file is newer than the build
$built = Join-Path $web "dist\index.html"
$stale = -not (Test-Path $built)
if (-not $stale) {
    $stamp = (Get-Item $built).LastWriteTime
    $newer = Get-ChildItem -Path (Join-Path $web "src"), (Join-Path $web "index.html"), (Join-Path $web "package-lock.json"), (Join-Path $web "vite.config.ts") -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -gt $stamp } | Select-Object -First 1
    $stale = $null -ne $newer
}
if ($stale) {
    Write-Host "Building web/ ..."
    Push-Location $web
    if (-not (Test-Path "node_modules")) { npm ci }
    npm run build
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Write-Error "The build failed: not starting."; exit $code }
}

# Alpaca keys for the Chart's live minute bars, if stored (scripts\set_local_secrets.ps1).
foreach ($name in "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY") {
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if ($value) { Set-Item -Path "Env:$name" -Value $value }
}

Write-Host "Trading OS (React) on http://localhost:$port"
uv run --group api python -m api.serve --port $port
