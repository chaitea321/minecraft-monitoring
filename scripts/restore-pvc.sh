#!/bin/bash
# PVC Restore Script for k3s homelab
# Restores a PVC from a backup file
# Requires root access (run via sudo)
#
# Usage: sudo bash restore-pvc.sh <pvc-name> <backup-file>
#
# PVC names: minecraft, grafana, prometheus, alertmanager, homepage
#
# IMPORTANT: Stop the associated workload BEFORE restoring to avoid data corruption.
# After restore, restart the workload.

set -euo pipefail

PVC_SOURCE="/var/lib/rancher/k3s/storage"
KUBECONFIG="/home/eugene/.kube/config"
KUBECTL="/usr/local/bin/kubectl"
TAR="/usr/bin/tar"
FIND="/usr/bin/find"
ZSTD="/usr/bin/zstd"

declare -A PVC_PATTERNS=(
    ["minecraft"]="*minecraft-data"
    ["grafana"]="*monitoring-grafana"
    ["prometheus"]="*prometheus-monitoring-kube-prometheus-prometheus-db*"
    ["alertmanager"]="*alertmanager-monitoring-kube-prometheus-alertmanager-db*"
    ["homepage"]="*homepage-config"
)

declare -A PVC_RESOURCE=(
    ["minecraft"]="deployment/minecraft-server"
    ["grafana"]="deployment/monitoring-grafana"
    ["prometheus"]="statefulset/prometheus-monitoring-kube-prometheus-prometheus"
    ["alertmanager"]="statefulset/alertmanager-monitoring-kube-prometheus-alertmanager"
    ["homepage"]="deployment/homepage"
)

declare -A PVC_NAMESPACE=(
    ["minecraft"]="default"
    ["grafana"]="monitoring"
    ["prometheus"]="monitoring"
    ["alertmanager"]="monitoring"
    ["homepage"]="default"
)

if [ $# -lt 2 ]; then
    echo "Usage: sudo bash $0 <pvc-name> <backup-file>"
    echo ""
    echo "PVC names: minecraft, grafana, prometheus, alertmanager, homepage"
    echo ""
    echo "Available backups:"
    for name in "${!PVC_PATTERNS[@]}"; do
        echo "  $name:"
        $FIND /home/eugene/backups/pvcs -name "${name}-*.tar.zst" -printf "    %f (%s bytes, %Tc)\n" 2>/dev/null || echo "    (none found)"
    done
    exit 1
fi

PVC_NAME="$1"
BACKUP_FILE="$2"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

if [ -z "${PVC_PATTERNS[$PVC_NAME]+x}" ]; then
    echo "ERROR: Unknown PVC name '$PVC_NAME'"
    echo "Valid names: ${!PVC_PATTERNS[*]}"
    exit 1
fi

# Find the PVC directory
pattern="${PVC_PATTERNS[$PVC_NAME]}"
pvc_dir=$($FIND "$PVC_SOURCE" -maxdepth 1 -type d -name "$pattern" 2>/dev/null | head -1 || true)

if [ -z "$pvc_dir" ]; then
    echo "ERROR: PVC directory not found for '$PVC_NAME' (pattern: $pattern)"
    exit 1
fi

pvc_parent=$(dirname "$pvc_dir")
pvc_basename=$(basename "$pvc_dir")

echo "=== PVC Restore ==="
echo "PVC:     $PVC_NAME"
echo "Source:  $pvc_dir"
echo "Backup:  $BACKUP_FILE"
echo "Size:    $(du -h "$BACKUP_FILE" | cut -f1)"
echo ""
echo "WARNING: This will OVERWRITE the current PVC data."
echo "The associated workload (${PVC_RESOURCE[$PVC_NAME]}) should be stopped first."
echo ""

# Check if workload is running
resource="${PVC_RESOURCE[$PVC_NAME]}"
namespace="${PVC_NAMESPACE[$PVC_NAME]}"
pod_count=$("$KUBECTL" --kubeconfig="$KUBECONFIG" get "$resource" -n "$namespace" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
if [ "$pod_count" != "0" ] && [ "$pod_count" != "" ]; then
    echo "WARNING: Workload $resource has $pod_count replica(s) running."
    echo "It is strongly recommended to scale it to 0 before restoring."
    echo ""
    # Bug 7 fix: check for interactive terminal before using read
    if [ -t 0 ]; then
        read -p "Scale down $resource to 0 replicas? [y/N] " scale_down
        if [[ "$scale_down" =~ ^[Yy]$ ]]; then
            echo "Scaling down $resource..."
            "$KUBECTL" --kubeconfig="$KUBECONFIG" scale "$resource" -n "$namespace" --replicas=0
            echo "Waiting for pods to terminate..."
            sleep 10
        fi
    else
        echo "NOTE: Not running interactively. Workload is NOT scaled down automatically."
        echo "Scale it down manually before proceeding, or run this script interactively."
    fi
fi

# Bug 7 fix: check for interactive terminal before using read
if [ -t 0 ]; then
    read -p "Proceed with restore? [y/N] " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Restore cancelled."
        exit 0
    fi
else
    echo "ERROR: This script requires an interactive terminal for confirmation."
    echo "Run it directly (not via pipe or cron) to proceed."
    exit 1
fi

echo "Restoring from backup..."
$TAR -I "$ZSTD" -xf "$BACKUP_FILE" -C "$pvc_dir"

echo "Restore complete for '$PVC_NAME'."
echo ""
echo "Next steps:"
echo "1. Verify the restored data looks correct"
echo "2. Restart the workload: kubectl rollout restart $resource -n $namespace"
echo "3. Monitor logs: kubectl logs -n $namespace -l app=$(kubectl get $resource -n $namespace -o jsonpath='{.spec.selector.matchLabels.app}' 2>/dev/null || echo '?')"
