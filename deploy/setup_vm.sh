#!/usr/bin/env bash
# ==============================================================================
# FixLoop GCP VM Setup & Automated Deployment Script
# Target OS: Ubuntu 22.04 LTS / 24.04 LTS (Google Compute Engine)
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo " Starting FixLoop Backend VM Setup on Google Cloud..."
echo "=========================================================="

# 1. Update system packages
echo "[1/5] Updating system packages..."
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    ufw

# 2. Install official Docker Engine & Docker Compose plugin
echo "[2/5] Installing Docker and Docker Compose..."
if ! command -v docker &> /dev/null; then
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# Enable Docker service
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true

# 3. Configure VM local firewall (UFW)
echo "[3/5] Configuring firewall rules..."
sudo ufw allow 22/tcp comment 'SSH' || true
sudo ufw allow 80/tcp comment 'HTTP / Caddy SSL' || true
sudo ufw allow 443/tcp comment 'HTTPS / Caddy SSL' || true
sudo ufw allow 8000/tcp comment 'FixLoop FastAPI Backend' || true
sudo ufw --force enable || true

# 4. Verify or generate .env file
echo "[4/5] Checking environment configuration..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "Creating .env from .env.example..."
        cp .env.example .env
        echo "--> NOTE: Remember to update NEBIUS_API_KEY in .env before running!"
    fi
fi

# 5. Build and launch containers
echo "[5/5] Building and starting FixLoop Backend container..."
if [ "${1:-}" == "--ssl" ]; then
    echo "Starting Backend with Caddy SSL reverse proxy..."
    sudo docker compose --profile ssl up -d --build
else
    echo "Starting Backend on port 8000..."
    sudo docker compose up -d --build
fi

echo "=========================================================="
echo " FixLoop Backend successfully launched!"
echo " Check status: sudo docker compose ps"
echo " View logs:    sudo docker compose logs -f"
echo " Health check: curl http://localhost:8000/health"
echo " Ready check:  curl http://localhost:8000/ready"
echo "=========================================================="
