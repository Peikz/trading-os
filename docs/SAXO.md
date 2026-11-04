# Saxo, read-only

Trading OS reads two things from Saxo: your **open positions** and your **working stop
orders**. With them, the position manager (the 💼 block in the pre-market and EOD pushes, and
Journal → Open positions) uses the stop that actually sits at Saxo instead of the one you
logged. Nothing ever goes the other way: the Saxo client only sends GET requests and has no
code that places, changes or cancels an order.

Status (4 Nov 2026): built from Saxo's public OpenAPI reference and tested on sample data,
not yet against your account. The first real check is step 4 below. The live sign-in
(`scripts/saxo_login.py`) was added on 4 Nov.

Until then the journal works as before: log fills on the dashboard, or import a Saxo trade
export (CSV) on Journal → Import broker fills. Send one export so its column names can be
mapped once in `config/scans.yaml → journal.csv_columns`.

## How the live sign-in works

Saxo uses a browser sign-in (OAuth authorization code grant):

- You sign in once on Saxo's own page. Saxo sends the browser back to a small address on this
  PC (`http://localhost:8799/saxo`), and `saxo_login.py`, listening there for a minute, swaps
  the code for tokens.
- The **access token lasts 20 minutes** and the **refresh token 40**. Each refresh gives a new
  pair, so the session lasts as long as something refreshes it at least every 40 minutes.
  `saxo_sync.py` refreshes by itself, and `--every 30` keeps the session alive while it runs.
  After a longer gap (the PC asleep, overnight), sign in again.
- The tokens are saved in `%LOCALAPPDATA%\trading-os\saxo_token.json`, outside both repos.
  Nothing prints a token, the code or the app secret.

## 1. A developer app at Saxo

On Saxo's developer portal (developer.saxo), sign in with your Saxo login and go to "My apps".
Check the portal for the current steps; in short:

1. Create an app for your **live** account, with:
   - **Grant type:** Code (authorization code).
   - **Redirect URL:** `http://localhost:8799/saxo`, exactly this.
   - **Access:** read only. Trading OS needs no trading permission.
2. Saxo shows the app's **AppKey**, **AppSecret** and **AuthenticationUrl**.

(For a first test on the simulation account, the portal also offers a 24-hour token: put it in
`SAXO_TOKEN` with `SAXO_ENV=sim` and skip to step 4.)

## 2. The app's settings on the PC

Store them as Windows user variables, never in a repo file and never in chat. In PowerShell:

```powershell
function Set-Secret($name) {
  $v = Read-Host -AsSecureString $name
  [Environment]::SetEnvironmentVariable($name,
    [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($v)), "User")
}
Set-Secret SAXO_APP_KEY
Set-Secret SAXO_APP_SECRET
[Environment]::SetEnvironmentVariable("SAXO_REDIRECT", "http://localhost:8799/saxo", "User")
[Environment]::SetEnvironmentVariable("SAXO_ENV", "live", "User")
```

If the app details show an AuthenticationUrl other than `https://live.logonvalidation.net`,
set it too: `[Environment]::SetEnvironmentVariable("SAXO_AUTH_URL", "<that url>", "User")`.
Open a new terminal afterwards so it sees the variables.

## 3. Sign in

In the Trading-OS folder:

```powershell
uv run python scripts/saxo_login.py
```

Your browser opens Saxo's sign-in page. Log in (with Saxo's two-factor step). The tab then says
"Signed in to Saxo", and the terminal prints when the session ends unless it's refreshed.

## 4. Test it

```powershell
uv run python scripts/saxo_sync.py --check
```

It prints `Saxo: connected · N positions · M stop orders` (counts only). If Saxo answers with
an error, the field names in `trading_os/saxo.py` may need a small fix against your account's
real replies; ask Claude with the error line.

## 5. Use it

```powershell
uv run python scripts/saxo_sync.py --data-dir ..\trading-os-data
```

saves your positions and stop orders to the data repo (`data/journal/broker/`). Then
**Save & push** on the dashboard; the next pushes use your Saxo stops (stops older than three
days are ignored).

To keep it going during the session, so the stops stay current and the sign-in stays alive:

```powershell
uv run python scripts/saxo_sync.py --data-dir ..\trading-os-data --every 30
```

Stop it with Ctrl+C. A GitHub job can't keep a 40-minute session alive between its runs, so
the sync stays on the PC (or, later, the server) and the pushes use the last saved stops.
