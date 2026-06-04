# Resource limit DaemonSets for kube-system components
# These are daemonsets that run with limited resources to prevent runaway processes

---
# Helm install command (for traefik, svclb, local-path, metrics-server)
kubectl apply -f https://raw.githubusercontent.com/helm/helm/main/cmd/helm/hack/install-helm.sh 2>/dev/null || true
helm repo add traefik https://traefik.github.io/charts 2>/dev/null || true
