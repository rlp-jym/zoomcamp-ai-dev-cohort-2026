#!/usr/bin/env bash
set -euo pipefail

TAG="${1:?usage: kind-smoke.sh <image-tag>}"
CLUSTER="ci-$(date +%s)"
CONTEXT="kind-${CLUSTER}"

cleanup() {
  echo "cleaning up ephemeral cluster ${CLUSTER}..."
  kind delete cluster --name "${CLUSTER}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> creating ephemeral kind cluster ${CLUSTER}"
kind create cluster --name "${CLUSTER}" --wait 60s

echo "==> loading agent-relay:${TAG} into ${CLUSTER}"
kind load docker-image "agent-relay:${TAG}" --name "${CLUSTER}"

if ! kubectl get nodes >/dev/null 2>&1; then
  if [ "${ACT:-false}" = "true" ]; then
    # Running inside an act container with no route to the published control
    # plane: connect this container to kind's docker network and point
    # kubeconfig at the control-plane node instead.
    echo "==> rewiring kubectl through the kind docker network"
    MY_ID="$(hostname)"
    docker network connect "kind" "${MY_ID}" 2>/dev/null || true
    API_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${CLUSTER}-control-plane" | awk '{print $1}')"
    if [ -z "${API_IP}" ]; then
      echo "error: could not find the control-plane node IP" >&2
      exit 1
    fi
    kubectl config set-cluster "${CONTEXT}" --server="https://${API_IP}:6443" --insecure-skip-tls-verify=true
  else
    echo "error: cannot reach the kind cluster API" >&2
    exit 1
  fi
fi

echo "==> applying k8s manifests"
kubectl apply -f k8s/

echo "==> pinning deployment to image agent-relay:${TAG}"
kubectl set image deployment/agent-relay agent-relay="agent-relay:${TAG}"

echo "==> waiting for rollout"
kubectl rollout status deployment/agent-relay --timeout=180s
kubectl wait --for=condition=available deployment/agent-relay --timeout=60s

kubectl get pods -o wide

POD="$(kubectl get pod -l app=agent-relay --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')"
if [ -z "${POD}" ]; then
  echo "error: no Running agent-relay pod found" >&2
  exit 1
fi
echo "==> smoke pod: ${POD}"
kubectl wait --for=condition=Ready "pod/${POD}" --timeout=60s
echo "==> smoke: /ready must report ready"
kubectl exec "${POD}" -- python -c "import json, sys, urllib.request; data = json.load(urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=10)); sys.exit(0 if data.get('status') == 'ready' else 1)"
echo "==> smoke: / must serve the v2 dashboard"
kubectl exec "${POD}" -- python -c "import sys, urllib.request; body = urllib.request.urlopen('http://127.0.0.1:8000/', timeout=10).read().decode(); sys.exit(0 if 'sessionStorage' in body and 'Agent Relay v2' in body else 1)"

echo "SMOKE OK agent-relay:${TAG} on ${CLUSTER}"