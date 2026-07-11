#!/usr/bin/env bash
# Picks a bigger "agent" model and a small/fast "judge" model from whatever
# `ollama list` has pulled locally. Prints AGENT_MODEL=/JUDGE_MODEL= (bare
# tags, e.g. llama3.1:8b) -- scripts/configure_ollama.sh prefixes them with
# "ollama/" before writing them into the k8s ConfigMap.
set -euo pipefail

# Preference order, most-preferred first. First match found locally wins.
AGENT_PREFERENCE=(llama3.1:8b qwen3:8b mistral:latest gemma3:latest llama3.1:latest)
JUDGE_PREFERENCE=(qwen3:0.6b qwen3:1.7b llama3.2:latest phi4-mini:latest)

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
