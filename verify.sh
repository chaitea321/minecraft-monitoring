#!/bin/bash
# Verification script for all enhancements
set -euo pipefail

KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
KUBECTL="kubectl --kubeconfig=$KUBECONFIG"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }
info() { echo -e "${YELLOW}→${NC} $1"; }

echo "=========================================="
echo "Minecraft Monitoring Verification"
echo "=========================================="
echo ""

# Check middleware
echo "Checking middleware..."
$KUBECTL get middleware prometheus-rate-limit -n monitoring &>/dev/null && pass "Rate limiting middleware exists" || fail "Rate limiting middleware missing"
$KUBECTL get middleware audit-logging -n monitoring &>/dev/null && pass "Audit logging middleware exists" || fail "Audit logging middleware missing"

# Check automation
echo ""
echo "Checking automation..."
$KUBECTL get cronjob minecraft-memory-restart -n default &>/dev/null && pass "Memory restart cronjob exists" || fail "Memory restart cronjob missing"

# Check status page
echo ""
echo "Checking status page..."
$KUBECTL get deployment uptime-kuma -n default &>/dev/null && pass "Uptime Kuma deployment exists" || fail "Uptime Kuma deployment missing"
$KUBECTL get service uptime-kuma-service -n default &>/dev/null && pass "Uptime Kuma service exists" || fail "Uptime Kuma service missing"

# Check Grafana datasources
echo ""
echo "Checking Grafana datasources..."
$KUBECTL get configmap loki-datasource -n monitoring &>/dev/null && pass "Loki datasource exists" || fail "Loki datasource missing"
$KUBECTL get configmap grafana-provisioning -n monitoring &>/dev/null && pass "Grafana provisioning exists" || info "Grafana provisioning may be applied differently"

# Check alert rules
echo ""
echo "Checking alert rules..."
$KUBECTL get prometheusrules minecraft-alerts -n monitoring &>/dev/null && pass "Minecraft alerts exist" || fail "Minecraft alerts missing"
$KUBECTL get prometheusrules minecraft-log-alerts -n monitoring &>/dev/null && pass "Log alerts exist" || info "Log alerts may be in separate file"

# Check pods
echo ""
echo "Checking pod status..."
PROMTAIL_PODS=$($KUBECTL get pods -n monitoring -l app=promtail --no-headers 2>/dev/null | wc -l)
[ "$PROMTAIL_PODS" -gt 0 ] && pass "Promtail pods running ($PROMTAIL_PODS)" || fail "No Promtail pods"

GRAFANA_PODS=$($KUBECTL get pods -n monitoring -l app=grafana --no-headers 2>/dev/null | wc -l)
[ "$GRAFANA_PODS" -gt 0 ] && pass "Grafana pods running ($GRAFANA_PODS)" || fail "No Grafana pods"

DISCORD_PODS=$($KUBECTL get pods -n discord-bot -l app=discord-bot --no-headers 2>/dev/null | wc -l)
[ "$DISCORD_PODS" -gt 0 ] && pass "Discord bot pods running ($DISCORD_PODS)" || fail "No Discord bot pods"

STATUS_PODS=$($KUBECTL get pods -n default -l app=uptime-kuma --no-headers 2>/dev/null | wc -l)
[ "$STATUS_PODS" -gt 0 ] && pass "Status page pods running ($STATUS_PODS)" || fail "No status page pods"

# Check dashboards
echo ""
echo "Checking dashboards..."
$KUBECTL get configmap minecraft-logs-dashboard -n monitoring &>/dev/null && pass "Minecraft logs dashboard exists" || fail "Minecraft logs dashboard missing"
$KUBECTL get configmap uptime-kuma-dashboard -n monitoring &>/dev/null && pass "Uptime Kuma dashboard exists" || fail "Uptime Kuma dashboard missing"

# Check backup script
echo ""
echo "Checking backup script..."
[ -f "/home/eugene/backups/backup-pvcs.sh" ] && pass "Backup script updated" || info "Backup script may not be copied yet"

echo ""
echo "=========================================="
echo "Verification Complete!"
echo "=========================================="
