# Start the Trading OS dashboard. With Tailscale installed, it is also shared privately with
# your own devices at https://<this-pc>.<your-tailnet>.ts.net (nobody else can reach it).
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\start_dashboard.ps1

$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo

if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    # --bg keeps serving in the background and survives restarts; the app itself stays on localhost.
    tailscale serve --bg 8501
    Write-Host "Shared on your tailnet. Open the https://...ts.net address above on your phone."
} else {
    Write-Host "Tailscale not installed: the dashboard is on this PC only (http://localhost:8501)."
}

uv run --group app streamlit run app/streamlit_app.py
