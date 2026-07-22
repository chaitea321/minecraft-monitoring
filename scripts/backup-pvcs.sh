#!/bin/bash
# PVC Backup Script for k3s homelab
# Backs up all PVCs using kubectl exec/cp (no root required)
#
# Schedule: Daily at 4:00 AM CST (10:00 UTC)
# Retention: 3 days
# Compression: zstd

set -euo pipefail

BACKUP_DIR="/home/eugene/backups/pvcs"
RETENTION_DAYS=3
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
KUBECONFIG="/home/eugene/.kube/config"
KUBECTL="/usr/local/bin/kubectl"
ZSTD="/usr/bin/zstd"
TAR="/usr/bin/tar"

# --- Cleanup trap for temporary backup pods (Bug 6 fix) ---
TEMP_PODS=()

cleanup() {
    for pod in "${TEMP_PODS[@]}"; do
        $KUBECTL --kubeconfig="$KUBECONFIG" delete pod "$pod" -n monitoring --ignore-not-found --wait=false 2>/dev/null || true
    done
}
trap cleanup EXIT

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

mkdir -p "$BACKUP_DIR"

# Clean up backups older than retention period
log "Cleaning up backups older than ${RETENTION_DAYS} days..."
old_count=$(find "$BACKUP_DIR" -name "*.tar.zst" -mtime +"$RETENTION_DAYS" -print 2>/dev/null | wc -l)
if [ "$old_count" -gt 0 ]; then
    find "$BACKUP_DIR" -name "*.tar.zst" -mtime +"$RETENTION_DAYS" -delete
    log "Deleted $old_count old backup(s)"
fi

# Pre-backup: Flush Minecraft world to disk
log "Running Minecraft save-all..."
if $KUBECTL --kubeconfig="$KUBECONFIG" exec -n default deploy/minecraft-server -c minecraft -- rcon-cli save-all >/dev/null 2>&1; then
    log "Minecraft save-all completed"
    sleep 5
else
    log "WARN: Minecraft save-all failed (server may be offline). Proceeding with backup anyway."
fi

errors=0

# Verify a backup archive is valid by testing integrity and listing contents
# (Bug 4 fix: catch truncation/corruption that zstd alone would miss)
verify_backup() {
    local backup_file="$1"
    local name="$2"

    # Test zstd integrity
    if ! $ZSTD -t "$backup_file" 2>/dev/null; then
        log "  ERROR: zstd integrity check failed for '$name'"
        return 1
    fi

    # Test tar archive can be listed (catches truncated streams)
    local file_count
    file_count=$($ZSTD -d -c "$backup_file" 2>/dev/null | $TAR -t 2>/dev/null | wc -l)
    if [ "$file_count" -lt 1 ]; then
        log "  ERROR: tar archive is empty or corrupt for '$name'"
        return 1
    fi

    log "  Verified: $file_count files in archive"
    return 0
}

# Backup a pod's volume using kubectl exec (container must have tar)
# Note: errors variable is modified here and propagates to the caller
# because bash functions run in the same shell context (not a subshell).
backup_pod() {
    local name="$1"
    local namespace="$2"
    local pod_selector="$3"
    local container="$4"
    local mount_path="$5"
    local exclude_pattern="${6:-}"
    local backup_file="$BACKUP_DIR/${name}-${TIMESTAMP}.tar.zst"

    log "Backing up '$name' from $namespace/$pod_selector:$container ($mount_path)..."

    local tar_exclude=""
    if [ -n "$exclude_pattern" ]; then
        tar_exclude="--exclude=$exclude_pattern"
    fi

    # Bug 1 fix: capture stderr to log file for debugging instead of discarding
    local stderr_log="/tmp/backup-${name}-${TIMESTAMP}.stderr"
    if $KUBECTL --kubeconfig="$KUBECONFIG" exec -n "$namespace" "$pod_selector" -c "$container" -- \
        tar -c $tar_exclude -C "$mount_path" . 2>"$stderr_log" | \
        $ZSTD -T0 -3 -o "$backup_file" 2>>"$stderr_log"; then

        if [ -f "$backup_file" ] && [ -s "$backup_file" ]; then
            # Bug 4 fix: verify archive integrity
            if verify_backup "$backup_file" "$name"; then
                size=$(du -h "$backup_file" | cut -f1)
                log "  OK: $backup_file ($size)"
            else
                log "  ERROR: Verification failed for '$name'"
                rm -f "$backup_file"
                errors=$((errors + 1))
            fi
        else
            log "  ERROR: Backup file is empty or missing for '$name'"
            rm -f "$backup_file"
            errors=$((errors + 1))
        fi
    else
        # Log stderr for debugging
        if [ -s "$stderr_log" ]; then
            log "  stderr: $(head -3 "$stderr_log")"
        fi
        log "  ERROR: Failed to backup '$name'"
        rm -f "$backup_file"
        errors=$((errors + 1))
    fi
    rm -f "$stderr_log"
}

# Backup a PVC using a temporary busybox pod + kubectl exec
# (Bug 3 fix: avoids kubectl logs which truncates binary streams >16KB)
# Uses a long-running pod (sleep) so we can exec tar into it, streaming
# directly through the exec pipe instead of the container logging subsystem.
backup_pvc_pod() {
    local name="$1"
    local namespace="$2"
    local pvc_name="$3"
    local mount_path="$4"
    local exclude_pattern="${5:-}"
    local backup_file="$BACKUP_DIR/${name}-${TIMESTAMP}.tar.zst"
    local pod_name="backup-${name}-${TIMESTAMP}"
    local tmp_manifest="/tmp/${pod_name}.yaml"

    log "Backing up '$name' from PVC $namespace/$pvc_name ($mount_path)..."

    local tar_exclude=""
    if [ -n "$exclude_pattern" ]; then
        tar_exclude="--exclude=${exclude_pattern}"
    fi

    # Create a temporary pod manifest
    cat > "$tmp_manifest" <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${pod_name}
  namespace: ${namespace}
spec:
  containers:
  - name: backup
    image: busybox:1.37
    command: ["sh", "-c", "sleep 300"]
    # REQUIRED: the monitoring namespace has a ResourceQuota covering
    # limits.cpu/memory and requests.cpu/memory, and there is no LimitRange
    # there to supply defaults (manifests/limitranges.yaml only covers
    # kube-system). Without this block admission rejects the pod outright:
    #   pods "backup-..." is forbidden: failed quota: monitoring-quota:
    #   must specify limits.cpu for: backup; ...
    resources:
      requests:
        cpu: 10m
        memory: 32Mi
      limits:
        cpu: 200m
        memory: 128Mi
    volumeMounts:
    - name: data
      mountPath: ${mount_path}
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: ${pvc_name}
  restartPolicy: Never
  terminationGracePeriodSeconds: 5
EOF

    # Create the pod
    if ! $KUBECTL --kubeconfig="$KUBECONFIG" create -f "$tmp_manifest" 2>/dev/null; then
        log "  ERROR: Failed to create backup pod for '$name'"
        rm -f "$tmp_manifest"
        errors=$((errors + 1))
        return
    fi

    # Register for cleanup on EXIT (Bug 6 fix)
    TEMP_PODS+=("$pod_name")

    # Wait for pod to be ready
    if ! $KUBECTL --kubeconfig="$KUBECONFIG" wait --namespace="$namespace" --for=condition=Ready "pod/$pod_name" --timeout=30s 2>/dev/null; then
        log "  ERROR: Backup pod did not become ready for '$name'"
        rm -f "$tmp_manifest"
        errors=$((errors + 1))
        return
    fi

    # Exec tar into the pod and compress locally (Bug 3 fix: direct pipe, no logs)
    local stderr_log="/tmp/backup-${name}-${TIMESTAMP}.stderr"
    if $KUBECTL --kubeconfig="$KUBECONFIG" exec -n "$namespace" "$pod_name" -c backup -- \
        tar -c $tar_exclude -C "$mount_path" . 2>"$stderr_log" | \
        $ZSTD -T0 -3 -o "$backup_file" 2>>"$stderr_log"; then

        if [ -f "$backup_file" ] && [ -s "$backup_file" ]; then
            # Bug 4 fix: verify archive integrity
            if verify_backup "$backup_file" "$name"; then
                size=$(du -h "$backup_file" | cut -f1)
                log "  OK: $backup_file ($size)"
            else
                log "  ERROR: Verification failed for '$name'"
                rm -f "$backup_file"
                errors=$((errors + 1))
            fi
        else
            log "  ERROR: Backup file is empty or missing for '$name'"
            rm -f "$backup_file"
            errors=$((errors + 1))
        fi
    else
        if [ -s "$stderr_log" ]; then
            log "  stderr: $(head -3 "$stderr_log")"
        fi
        log "  ERROR: Failed to backup '$name'"
        rm -f "$backup_file"
        errors=$((errors + 1))
    fi
    rm -f "$stderr_log" "$tmp_manifest"
}

# --- Backups ---

# Minecraft - /data contains world, configs, plugins
backup_pod "minecraft" "default" "deploy/minecraft-server" "minecraft" "/data" ""

# Grafana - /var/lib/grafana contains SQLite DB, dashboards, plugins
# NOTE: the Helm release is "kube-prometheus-stack", not "monitoring-*". The
# old deploy/monitoring-grafana name has not existed for months, so this
# backup failed silently every night since the release was renamed.
backup_pod "grafana" "monitoring" "deploy/kube-prometheus-stack-grafana" "grafana" "/var/lib/grafana" ""

# Prometheus - /prometheus contains TSDB data; exclude WAL (rebuildable)
# Uses temporary pod because Prometheus container is distroless (no tar binary)
# NOTE: instance label is kube-prometheus-stack-prometheus (see rename above).
PROMETHEUS_PVC=$($KUBECTL --kubeconfig="$KUBECONFIG" get pvc -n monitoring -l app.kubernetes.io/instance=kube-prometheus-stack-prometheus -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [ -n "$PROMETHEUS_PVC" ]; then
    backup_pvc_pod "prometheus" "monitoring" "$PROMETHEUS_PVC" "/prometheus" "wal"
else
    log "ERROR: Could not find Prometheus PVC"
    errors=$((errors + 1))
fi

# AlertManager - /alertmanager contains silences, notification log
# NOTE: same rename -- the StatefulSet is
# alertmanager-kube-prometheus-stack-alertmanager.
backup_pod "alertmanager" "monitoring" "statefulset/alertmanager-kube-prometheus-stack-alertmanager" "alertmanager" "/alertmanager" ""

# Homepage - /app/config contains YAML configs
backup_pod "homepage" "default" "deploy/homepage" "homepage" "/app/config" ""

# Summary
total_size=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
backup_count=$(find "$BACKUP_DIR" -name "*.tar.zst" -print 2>/dev/null | wc -l)
log "Backup complete: $backup_count backup(s) in $BACKUP_DIR (total: $total_size)"

if [ "$errors" -gt 0 ]; then
    log "WARNING: $errors backup(s) failed"
    exit 1
fi

exit 0
