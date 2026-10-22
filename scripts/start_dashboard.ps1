# Start the Trading OS dashboard. With Tailscale signed in, it is also shared privately with your
# own devices at http://<this-pc>.<your-tailnet>.ts.net (nobody else can reach it; Tailscale
# encrypts the traffic between your devices, so plain HTTP inside the tailnet is fine).
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\start_dashboard.ps1

$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
$port = 8501
$tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $tailscale -and (Test-Path "C:\Program Files\Tailscale\tailscale.exe")) {
    $tailscale = "C:\Program Files\Tailscale\tailscale.exe"
}

if ($tailscale) {
    # --bg keeps serving in the background and survives restarts; the app itself stays on localhost.
    & $tailscale serve --bg --http=80 $port
    Write-Host "Shared on your tailnet. Open the http://...ts.net address above on your phone."
} else {
    Write-Host "Tailscale not installed: the dashboard is on this PC only (http://localhost:$port)."
}

# Alpaca keys for the Chart page's live minute bars, if stored (scripts\set_local_secrets.ps1).
foreach ($name in "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY") {
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if ($value) { Set-Item -Path "Env:$name" -Value $value }
}

uv run --group app streamlit run app/streamlit_app.py --server.port $port --server.headless true
