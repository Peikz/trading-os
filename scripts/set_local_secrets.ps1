# Store the keys the price-alert watcher needs on this PC (Emil, 22 Oct 2026), as your own
# Windows user environment variables: never in a file of the repo, never printed. Type each at
# its hidden prompt; press Enter on an empty prompt to keep the value already stored.
#   powershell -ExecutionPolicy Bypass -File scripts\set_local_secrets.ps1

$names = @(
    @{ Name = "ALPACA_API_KEY_ID"; Hint = "Alpaca API key ID (alpaca.markets dashboard, API keys)" },
    @{ Name = "ALPACA_API_SECRET_KEY"; Hint = "Alpaca secret key" },
    @{ Name = "NTFY_TOPIC"; Hint = "your ntfy topic (the name you subscribed to in the ntfy app)" }
)

foreach ($item in $names) {
    $stored = [Environment]::GetEnvironmentVariable($item.Name, "User")
    $state = if ($stored) { "stored" } else { "not set" }
    $secure = Read-Host -AsSecureString "$($item.Hint) [$state]"
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    if ($plain) {
        [Environment]::SetEnvironmentVariable($item.Name, $plain.Trim(), "User")
        Write-Host "  $($item.Name): saved"
    } else {
        Write-Host "  $($item.Name): unchanged ($state)"
    }
}
Write-Host "Done. Start the watcher with scripts\start_alerts.ps1"
