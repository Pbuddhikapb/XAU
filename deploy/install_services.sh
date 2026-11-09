#!/usr/bin/env bash
# ==============================================================================
# Binance XAUUSDT Production Service Installation Script
# Installs, enables, and starts systemd service units for 24/7 continuous uptime.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="${SCRIPT_DIR}/systemd"

echo "=== Installing XAU Market Intelligence Systemd Services ==="

# Check sudo access
if [ "$EUID" -ne 0 ]; then
    echo "Elevating privileges with sudo..."
    SUDO="sudo"
else
    SUDO=""
fi

# 1. Create log and backup directories
echo "Creating required production directories..."
$SUDO mkdir -p /home/ubuntu/XAU/logs
$SUDO chown -R ubuntu:ubuntu /home/ubuntu/XAU/logs
$SUDO mkdir -p /var/backups/xau_db
$SUDO chown -R ubuntu:ubuntu /var/backups/xau_db

# 2. Copy systemd service files
echo "Installing systemd unit files to /etc/systemd/system/..."
$SUDO cp "${SYSTEMD_DIR}/xau-backend.service" /etc/systemd/system/
$SUDO cp "${SYSTEMD_DIR}/xau-ingestion.service" /etc/systemd/system/
$SUDO cp "${SYSTEMD_DIR}/xau-watchdog.service" /etc/systemd/system/

# 3. Reload systemd daemon
echo "Reloading systemd daemon..."
$SUDO systemctl daemon-reload

# 4. Enable services on boot
echo "Enabling services on system boot..."
$SUDO systemctl enable xau-backend.service
$SUDO systemctl enable xau-ingestion.service
$SUDO systemctl enable xau-watchdog.service

# 5. Start services
echo "Starting services..."
$SUDO systemctl restart xau-backend.service
$SUDO systemctl restart xau-ingestion.service
$SUDO systemctl restart xau-watchdog.service

echo ""
echo "=== Systemd Services Status ==="
$SUDO systemctl status xau-backend.service --no-pager -l || true
echo "=================================================="
echo "Installation complete. Services are running 24/7."
