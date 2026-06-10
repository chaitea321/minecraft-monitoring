#!/bin/bash
# Backup Integrity Verification Script
# Tests that backup archives are valid and contain expected files.
# Does NOT test actual PVC restore (requires sudo on host).
#
# Schedule: Weekly via system crontab (Sunday 5 AM CST)

set -euo pipefail

BACKUP_DIR="/home/eugene/backups/pvcs"
ZSTD="/usr/bin/zstd"
TAR="/usr/bin/tar"
FIND="/usr/bin/find"
KUBECONFIG="/home/eugene/.kube/config"
KUBECTL="/usr/local/bin/kubectl"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

errors=0
checked=0

# Expected files per backup (non-empty check — at least 1 file matching pattern)
declare -A EXPECTED_FILES=(
    ["minecraft"]="level.dat"
    ["grafana"]="grafana.db"
    ["prometheus"]="chunks_head"
    ["alertmanager"]="silences"
    ["homepage"]="services.yaml"
)

log "=== Backup Integrity Verification ==="
log "Backup directory: $BACKUP_DIR"

# Check backup directory exists
if [ ! -d "$BACKUP_DIR" ]; then
    log "ERROR: Backup directory does not exist: $BACKUP_DIR"
    exit 1
fi

# Check each backup type
for name in minecraft grafana prometheus alertmanager homepage; do
    # Find latest backup for this service
    latest=$($FIND "$BACKUP_DIR" -name "${name}-*.tar.zst" -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)

    if [ -z "$latest" ] || [ ! -f "$latest" ]; then
        log "WARN: No backup found for '$name'"
        continue
    fi

    checked=$((checked + 1))
    size=$(du -h "$latest" | cut -f1)
    log "Checking '$name': $(basename "$latest") ($size)..."

    # Test 1: zstd integrity
    if ! $ZSTD -t "$latest" 2>/dev/null; then
        log "  FAIL: zstd integrity check failed"
        errors=$((errors + 1))
        continue
    fi
    log "  PASS: zstd integrity OK"

    # Test 2: tar can list contents
    file_count=$($ZSTD -d -c "$latest" 2>/dev/null | $TAR -t 2>/dev/null | wc -l)
    if [ "$file_count" -lt 1 ]; then
        log "  FAIL: tar archive is empty"
        errors=$((errors + 1))
        continue
    fi
    log "  PASS: archive contains $file_count files"

    # Test 3: expected file exists in archive
    expected="${EXPECTED_FILES[$name]:-}"
    if [ -n "$expected" ]; then
        if $ZSTD -d -c "$latest" 2>/dev/null | $TAR -t 2>/dev/null | grep -q "$expected"; then
            log "  PASS: expected file '$expected' found"
        else
            log "  FAIL: expected file '$expected' NOT found in archive"
            errors=$((errors + 1))
            continue
        fi
    fi

    log "  OK: '$name' backup verified"
done

# Check backup age (warn if older than 2 days)
log ""
log "=== Backup Freshness ==="
for name in minecraft grafana prometheus alertmanager homepage; do
    latest=$($FIND "$BACKUP_DIR" -name "${name}-*.tar.zst" -printf "%T@ %p\n" 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
    if [ -n "$latest" ] && [ -f "$latest" ]; then
        age_days=$(( ($(date +%s) - $(stat -c %Y "$latest")) / 86400 ))
        if [ "$age_days" -gt 2 ]; then
            log "WARN: '$name' backup is $age_days days old"
        else
            log "OK: '$name' backup is $age_days day(s) old"
        fi
    fi
done

# Summary
log ""
log "=== Summary ==="
log "Checked: $checked backup(s)"
log "Failed:  $errors"

if [ "$errors" -gt 0 ]; then
    log "RESULT: FAILED"
    exit 1
fi

log "RESULT: PASSED"
exit 0
