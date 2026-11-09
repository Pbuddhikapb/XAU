#!/usr/bin/env bash
# ==============================================================================
# Binance XAUUSDT Production Database Disaster Recovery Script
# Verifies SHA256 checksum and restores a specified backup .sql.gz archive.
# ==============================================================================

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <path_to_backup_file.sql.gz>"
    echo "Example: $0 /var/backups/xau_db/xau_intelligence_backup_20261109_000000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"
DB_NAME="xau_intelligence"
DB_USER="xau_user"
DB_HOST="localhost"
DB_PORT="5432"
export PGPASSWORD="xau_pass_2026"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file does not exist: $BACKUP_FILE" >&2
    exit 1
fi

CHECKSUM_FILE="${BACKUP_FILE}.sha256"
if [ -f "$CHECKSUM_FILE" ]; then
    echo "Verifying SHA256 checksum..."
    sha256sum -c "$CHECKSUM_FILE"
else
    echo "WARNING: Checksum file not found. Testing gzip integrity directly..."
    gzip -t "$BACKUP_FILE"
fi

echo "=== CAUTION: RESTORING DATABASE ==="
echo "Target Database: ${DB_NAME} on ${DB_HOST}:${DB_PORT}"
echo "Source Archive:  ${BACKUP_FILE}"
read -p "Are you sure you want to restore? This will overwrite existing data! (y/N): " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Restoration aborted."
    exit 0
fi

echo "Executing restore..."
gunzip -c "$BACKUP_FILE" | psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME"

echo "Database restoration completed successfully."
