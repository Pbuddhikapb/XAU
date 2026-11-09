#!/usr/bin/env bash
# ==============================================================================
# Binance XAUUSDT Production Database Backup Script
# Performs compressed pg_dump, generates SHA256 checksum, and prunes older backups.
# Scheduled to run nightly via crontab (e.g. at 00:00 UTC).
# ==============================================================================

set -euo pipefail

DB_NAME="xau_intelligence"
DB_USER="xau_user"
DB_HOST="localhost"
DB_PORT="5432"
export PGPASSWORD="xau_pass_2026"

BACKUP_DIR="/var/backups/xau_db"
if [ ! -d "$BACKUP_DIR" ] || [ ! -w "$BACKUP_DIR" ]; then
    BACKUP_DIR="${HOME}/.xau/backups"
    mkdir -p "$BACKUP_DIR"
fi

TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_backup_${TIMESTAMP}.sql.gz"
CHECKSUM_FILE="${BACKUP_FILE}.sha256"

echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] Starting automated database backup for ${DB_NAME}..."

# 1. Execute pg_dump with gzip compression
pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" | gzip -9 > "$BACKUP_FILE"

# 2. Verify compressed archive integrity
if gzip -t "$BACKUP_FILE" 2>/dev/null; then
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] Gzip archive integrity check passed."
else
    echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] ERROR: Backup archive verification failed!" >&2
    exit 1
fi

# 3. Generate SHA256 checksum
sha256sum "$BACKUP_FILE" > "$CHECKSUM_FILE"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] Backup successful: ${BACKUP_FILE} (${BACKUP_SIZE})"

# 4. Prune rolling backups older than 14 days
echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] Pruning backups older than 14 days..."
find "$BACKUP_DIR" -type f -name "${DB_NAME}_backup_*.sql.gz*" -mtime +14 -exec echo "Removing expired backup: {}" \; -delete

echo "[$(date -u +"%Y-%m-%d %H:%M:%S UTC")] Database backup routine completed."
