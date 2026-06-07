# Deploying to a Google Cloud "Always Free" VM

Runs the whole system (engine + dashboard, file sink) on one always-free GCP VM.
Total cost: $0 if you stay within the Always Free `e2-micro` limits.

## 1. Create the VM
GCP Console → **Compute Engine → VM instances → Create instance**:
- **Region:** `us-west1`, `us-central1`, or `us-east1` (only these are Always-Free eligible)
- **Machine type:** `e2-micro`
- **Boot disk:** Ubuntu 22.04 LTS (or Debian 12), **30 GB standard** (free-tier limit)
- Create. Note the **External IP**.

> GCP requires a billing account (credit card) even for the free tier. The `e2-micro`
> in those regions stays free after the $300/90-day trial ends.

## 2. Open the dashboard port (VPC firewall)
GCP Console → **VPC network → Firewall → Create firewall rule**:
- Name: `allow-dashboard`
- Targets: All instances (or a network tag you add to the VM)
- **Source IPv4 ranges:** `0.0.0.0/0` (world) — or **your own IP/32** to keep it private
- Protocols/ports: **TCP `8050`**

## 3. Install + get the code
SSH into the VM (the "SSH" button in the console), then:
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git
git clone <YOUR_REPO_URL> Project        # or scp the Project folder up
cd Project
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Add swap (important on 1 GB RAM — avoids out-of-memory)
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 5. Secrets + config
```bash
cp .env.example .env && nano .env        # paste your Binance testnet API key/secret
```
In `config/params.yaml`:
- `dashboard.host: 0.0.0.0`  (already set — required so the browser can reach it)
- `dashboard.read_only: true`  (recommended for a public link — hides the kill-switch)
- `dashboard.sink: file`  (default; everything on one VM)

## 6a. Quick run (tmux — easiest for a demo)
```bash
tmux new -s engine      # then: python -m scripts.run_live      ; detach with Ctrl-b then d
tmux new -s dash        # then: python -m scripts.run_dashboard ; detach with Ctrl-b then d
```
Open **http://EXTERNAL_IP:8050**

## 6b. Robust run (systemd — auto-restart, survives reboot)
```bash
# edit the two unit files first: set User= and the /home/<user>/Project paths
sudo cp deploy/btc-squeeze-engine.service    /etc/systemd/system/
sudo cp deploy/btc-squeeze-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now btc-squeeze-engine btc-squeeze-dashboard
sudo systemctl status btc-squeeze-dashboard      # check it's running
journalctl -u btc-squeeze-engine -f              # tail engine logs
```
For a production server, switch the dashboard unit's `ExecStart` to the gunicorn line
(`gunicorn -b 0.0.0.0:8050 dashboard.wsgi:server`) and `pip install gunicorn`.

## 7. Offline demo (optional — show the dashboard without the live engine)
```bash
python -m scripts.run_demo --symbol BTCUSDT --delay 0.3   # replays real cached data
# (run scripts.download_all --days 30 first to populate the cache)
```

## Notes
- **Testnet keys reset periodically** — regenerate at testnet.binancefuture.com and update `.env`.
- The **dashboard needs no API keys** — only the engine does.
- Lock down the firewall source to your IP if you don't want the dashboard world-readable.
- `e2-micro` is 1 GB RAM; the swap step above keeps pandas/Dash from OOM-ing.
