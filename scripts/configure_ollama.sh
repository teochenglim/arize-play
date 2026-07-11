#!/usr/bin/env bash
# Re-discovers local Ollama models and points the in-cluster LiteLLM proxy at
# them: patches the arize-ollama-models ConfigMap and restarts arize-litellm
# so it picks up the change -- but only if something actually changed, so
# repeated runs (e.g. from a Makefile prerequisite) don't restart the pod
# for no reason.
set -euo pipefail
cd "$(dirname "$0")/.."

eval "$(scripts/discover_ollama_models.sh)"
API_BASE=$(uv run python -c "import yaml; print(yaml.safe_load(open('config.yaml'))['ollama']['api_base'])")

echo "Using OLLAMA_API_BASE=${API_BASE} AGENT_MODEL=ollama/${AGENT_MODEL} JUDGE_MODEL=ollama/${JUDGE_MODEL}"

APPLY_OUTPUT=$(kubectl create configmap arize-ollama-models \
  --from-literal=OLLAMA_API_BASE="${API_BASE}" \
  --from-literal=AGENT_MODEL="ollama/${AGENT_MODEL}" \
  --from-literal=JUDGE_MODEL="ollama/${JUDGE_MODEL}" \
  --dry-run=client -o yaml | kubectl apply -f -)
echo "$APPLY_OUTPUT"

if echo "$APPLY_OUTPUT" | grep -q configured; then
  echo "Models changed -- restarting arize-litellm"
  kubectl rollout restart deployment/arize-litellm
  kubectl rollout status deployment/arize-litellm --timeout=60s
else
  echo "No change -- arize-litellm left running"
fi
