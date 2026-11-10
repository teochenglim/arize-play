#!/usr/bin/env bash
# Picks an "agent" (baseline) and a "judge" model from whatever
# `ollama list` has pulled locally. Prints AGENT_MODEL=/JUDGE_MODEL= (bare
# tags, e.g. llama3.1:8b) -- scripts/configure_ollama.sh prefixes them with
# "ollama/" before writing them into the k8s ConfigMap.
set -euo pipefail

# Preference order, most-preferred first. First match found locally wins.
AGENT_PREFERENCE=(bonsai-2:latest qwen3:latest llama3.1:8b mistral:latest)
JUDGE_PREFERENCE=(bonsai-2:latest qwen3:latest gemma4:latest llama3.2:latest)

# Never picked, even as a last-resort fallback -- not general chat models.
EXCLUDE_PATTERN='embed|rerank|bge-|flux|z-image|minicpm-v'

mapfile -t MODELS < <(ollama list | tail -n +2 | awk '{print $1}' | grep -Ev "$EXCLUDE_PATTERN")

if [[ ${#MODELS[@]} -eq 0 ]]; then
  echo "No usable chat models found in 'ollama list'" >&2
  exit 1
fi

pick() {
  for want in "$@"; do
    for have in "${MODELS[@]}"; do
      [[ "$have" == "$want" ]] && { echo "$want"; return; }
    done
  done
  echo "${MODELS[0]}"
}

echo "AGENT_MODEL=$(pick "${AGENT_PREFERENCE[@]}")"
echo "JUDGE_MODEL=$(pick "${JUDGE_PREFERENCE[@]}")"
