# The dashboard on a cloud server

The scans already run in the cloud: GitHub Actions, started on time by the cron-job.org timer.
Only the dashboard lives on the PC, so the phone can open it only while the PC is on. This
guide moves the dashboard to a small server that is always on. It stays private: like now, it
is reachable only from your own devices through Tailscale, and nothing is opened to the
internet.

Cost: a Hetzner CX22 (2 vCPU, 4 GB RAM, 40 GB disk) is about €4–5 a month. Time: about an
hour the first time. Everything the server needs is in two scripts:
[`scripts/server/install.sh`](../scripts/server/install.sh) (once) and
[`scripts/server/update.sh`](../scripts/server/update.sh) (every 10 minutes, by itself).

## 1. An SSH key on your PC (skip if you have one)

In PowerShell:

```powershell
ssh-keygen -t ed25519
```

Press Enter at each question. The public key is in `C:\Users\<you>\.ssh\id_ed25519.pub`.

## 2. The server (Hetzner)

1. Make an account at hetzner.com → **Cloud** → a new project.
2. **Security → SSH keys → Add SSH key**: paste the contents of `id_ed25519.pub`.
3. **Add server**:
   - Location: Nuremberg, Falkenstein or Helsinki (any EU one).
   - Image: **Ubuntu 24.04**.
   - Type: **Shared vCPU → x86 → CX22**.
   - Networking: public IPv4 on (needed for GitHub and the installer).
   - SSH key: the one from step 2. No password.
   - Name: `trading-os`.
4. Note the server's IP address.

## 3. A GitHub token for the server

GitHub → **Settings → Developer settings → Fine-grained tokens → Generate new token**:

- Name: `trading-os server`, expiry up to a year (note the date).
- Repository access: **Only select repositories** → `trading-os-data`.
- Permissions: **Contents: Read and write**. Nothing else.

Copy the token. You paste it once, into the installer's hidden prompt. It is never stored
in a repo or printed.

## 4. Install

From PowerShell on the PC:

```powershell
ssh root@<server-ip>
```

Then on the server:

```bash
curl -fsSL https://raw.githubusercontent.com/Peikz/trading-os/main/scripts/server/install.sh -o install.sh
bash install.sh
```

It installs everything and stops twice for you:

1. **Tailscale sign-in**: it prints a link. Open it and sign in with the same account as your
   phone and PC. The server joins your tailnet as `trading-os`.
2. **GitHub token**: paste the token from step 3 (nothing is shown) and press Enter.

At the end it prints the address, `http://trading-os.<your-tailnet>.ts.net/`. Open it on the
phone with Tailscale on, then Share → **Add to Home Screen**.

## 5. Close public SSH (recommended)

Check you can reach the server through Tailscale from the PC: `ssh root@trading-os`. Then, on
the server:

```bash
bash install.sh --lock-ssh
```

From then on the server has no open port on the internet; you reach it only from your own
devices. If you ever lock yourself out: Hetzner Console → the server → **Console** opens a
terminal in the browser.

## 6. Stop the PC's dashboard

Close its terminal (or Ctrl-C), and on the PC stop sharing it:

```powershell
tailscale serve --http=80 off
```

The PC's dashboard still works locally whenever you start `scripts\start_dashboard.ps1`; the
phone address is now the server's.

## How it runs

- **Dashboard**: a service (`trading-os-dashboard`) on `127.0.0.1:8501`, restarted by itself
  if it stops and after every reboot. Tailscale shares it on port 80 inside your tailnet.
- **Updates** (`trading-os-update.timer`, every 10 minutes): pulls the data repo, pulls the
  code, and after a code change syncs the packages and restarts the dashboard. So a change
  pushed to `main` is live on the phone within 10 minutes, and the dashboard never runs stale
  code.
- **Saving** (journal, notes, chart drawings, watchlists): **Save & push** commits to the data
  repo from the server, the same as on the PC.
- **Large study files** (10-year history, bars): downloaded from the data repo's releases on
  first use, kept in `/home/tradingos/.cache/trading-os-cache` (at most 1.5 GB).
- **Security updates**: Ubuntu installs them by itself (`unattended-upgrades`).

## Looking after it

| Task | Command (on the server) |
|---|---|
| Is it running? | `systemctl status trading-os-dashboard` |
| The dashboard's log | `journalctl -u trading-os-dashboard -n 100` |
| The update log | `journalctl -u trading-os-update -n 50` |
| Restart it | `systemctl restart trading-os-dashboard` |
| Update now | `systemctl start trading-os-update` |
| Repair the setup | `bash install.sh` (safe to run again) |

**When the GitHub token expires** (Save & push and the study files fail): make a new one as
in step 3, then on the server:

```bash
runuser -u tradingos -- gh auth login --with-token   # paste the token, then Ctrl-D
```

The server holds nothing that isn't also on GitHub, so if it ever breaks, delete it and run
steps 2 and 4 again.
