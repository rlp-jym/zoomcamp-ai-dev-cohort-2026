# Agent Relay

cd agent-relay

## Run locally

uv sync
uv run uvicorn main:app --reload    # http://127.0.0.1:8000/

## Test

uv run pytest -q

## Deploy to kind

docker build -t agent-relay:local .
kind create cluster --name demo
kind load docker-image agent-relay:local --name demo
kubectl apply -f k8s/
kubectl set image deployment/agent-relay agent-relay=agent-relay:local
kubectl rollout status deployment/agent-relay --timeout=180s
kubectl port-forward svc/agent-relay 8000:8000

## Run CI locally (act)

$env:Path = "$env:LOCALAPPDATA\Programs\act;$env:Path"
act --container-architecture linux/amd64

---

The workflow: tests (SQLite + PostgreSQL) then, only if they pass, builds a
unique-tag image, deploys to an ephemeral kind cluster, smoke-tests, and cleans up.
Same pipeline runs on GitHub on every push to `main`.