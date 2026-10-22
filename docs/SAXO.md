# Saxo, read-only

Trading OS reads two things from Saxo: your **open positions** and your **working stop
orders**. With them, the position manager (the 💼 block in the pre-market and EOD pushes, and
Journal → Open positions) uses the stop that actually sits at Saxo instead of the one you
logged. Nothing ever goes the other way: the Saxo client only sends GET requests and has no
code that places, changes or cancels an order.

Status (22 Oct 2026): built from Saxo's public OpenAPI reference and tested on sample data,
not yet against your account. The first real check is step 3 below.

Until then the journal works as before: log fills on the dashboard, or import a Saxo trade
export (CSV) on Journal → Import broker fills. Send one export so its column names can be
mapped once in `config/scans.yaml → journal.csv_columns`.

## 1. A developer app at Saxo

Saxo's developer portal (developer.saxo) lets you register an app for your own account. Check
the portal for the current steps; in short:

1. Sign in with your Saxo login and create an app ("My apps").
2. Give it **read** access only. Trading OS needs no trading permission.
3. Saxo shows the app's key and secret, and offers a 24-hour token for the **simulation**
   account, which is the safe first test.

## 2. A token on the PC

Store it as a Windows user variable (never in a file of the repo, never in chat), in
PowerShell:

```powershell
$t = Read-Host -AsSecureString "Saxo token"
[Environment]::SetEnvironmentVariable("SAXO_TOKEN",
  [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($t)), "User")
[Environment]::SetEnvironmentVariable("SAXO_ENV", "sim", "User")   # remove for your live account
```

## 3. Test it

In a new terminal in the Trading-OS folder:

```powershell
uv run python scripts/saxo_sync.py --check
```

It prints `Saxo: connected · N positions · M stop orders` (counts only). If Saxo answers with
an error, the field names in `trading_os/saxo.py` may need a small fix against your account's
real replies; ask Claude with the error line.

## 4. Use it

```powershell
uv run python scripts/saxo_sync.py --data-dir ..\trading-os-data
```

saves your positions and stop orders to the data repo (`data/journal/broker/`). Then
**Save & push** on the dashboard; the next pushes use your Saxo stops (stops older than three
days are ignored). Once it works against your live account, it can run by itself on the
cloud server or in a GitHub job; a Saxo login lasts a limited time, so it needs signing in
again now and then.
