#!/usr/bin/env bash
# Public Tripwire demo on a fresh Ubuntu 24.04 EC2 instance (CPU only, no API keys, no secrets):
# website + dashboard (+ the Analyse page when the machine has the memory) on the committed demo snapshot
# (data/demo), behind Caddy with HTTPS. Needs an Elastic IP and inbound 22 / 80 / 443.
# - 8 GB RAM or more (t3.large, m7i-flex.large, c7i-flex.large): everything, including the Analyse page.
# - less (free-tier t3.micro / t3.small, 1-2 GB): website + dashboard; the Analyse page is switched off.
# Usage on the instance:  bash ec2_setup.sh
set -euo pipefail
REPO=https://github.com/deepakm0003/iiitd-deepak-meena-hackathon.git
DIR=$HOME/tripwire
MEM_GB=$(awk '/MemTotal/ {printf "%d", $2 / 1024 / 1024 + 0.5}' /proc/meminfo)
if [ "$MEM_GB" -ge 6 ]; then FULL=1; else FULL=0; fi
echo "RAM ${MEM_GB} GB -> $([ $FULL = 1 ] && echo 'full install (Analyse on)' || echo 'light install (Analyse off)')"

sudo apt-get update -y
sudo apt-get install -y git curl gpg debian-keyring debian-archive-keyring apt-transport-https

# swap as a safety margin (the NLP models need about 5 GB of RAM while loading; small machines need it too)
if ! swapon --show | grep -q /swapfile; then
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# Python 3.11 + dependencies through uv
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH=$HOME/.local/bin:$PATH
[ -d "$DIR" ] || git clone "$REPO" "$DIR"
cd "$DIR" && git pull -q
uv venv -p 3.11 .venv
if [ $FULL = 1 ]; then
  uv pip install --python .venv/bin/python torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
  uv pip install --python .venv/bin/python -r requirements-research.txt
  # our fine-tuned entity-sentiment model (GitHub release) + the open-source base models from Hugging Face
  .venv/bin/python -m tripwire fetch-models --base
  DEMO_ARGS=""
else
  uv pip install --python .venv/bin/python -r requirements.txt
  DEMO_ARGS="--no-analyze"
fi

# the demo as a service (restarts on failure and on reboot)
sudo tee /etc/systemd/system/tripwire.service > /dev/null <<UNIT
[Unit]
Description=Tripwire demo
After=network-online.target

[Service]
User=$USER
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python -m tripwire demo --host 127.0.0.1 --port 8000 --no-browser $DEMO_ARGS
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now tripwire

# Caddy reverse proxy with an automatic HTTPS certificate for <ip>.sslip.io (no domain needed)
if ! command -v caddy > /dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
  sudo apt-get update -y && sudo apt-get install -y caddy
fi
IP=$(curl -s https://checkip.amazonaws.com)
HOST="${IP//./-}.sslip.io"
printf '%s {\n  reverse_proxy 127.0.0.1:8000\n}\n' "$HOST" | sudo tee /etc/caddy/Caddyfile > /dev/null
sudo systemctl restart caddy

echo "Tripwire demo: https://$HOST  (dashboard: https://$HOST/app)"
[ $FULL = 1 ] && echo "The Analyse page loads its models on the first start (a few minutes): journalctl -u tripwire -f"
exit 0
