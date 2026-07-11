# Design: local k8s demo (Phoenix + Ollama via LiteLLM)

Companion to `README.md`. `README.md` is the user-facing quickstart; this doc is the
"why" behind the local-k8s setup, for whoever touches `k8s/`, `scripts/`, or
`common/llm.py`/`common/tracing.py` next.

## Goal

Run the same three agent patterns (`pattern1_customer_facing`, `pattern2_internal_enterprise`,
`pattern3_developer_platform`) against a **local, real** LLM instead of canned responses,
with Phoenix and an LLM proxy running as real k8s services — while the demo agent itself
(`run_all.py`) stays a plain local process, managed with `uv`/pyenv, never containerized.
The zero-setup path (`uv run python run_all.py` with nothing else running, stub responses)
keeps working unchanged.

**Split of responsibilities:**
- **In k8s** (`kubectl apply -f k8s/`): Postgres, Phoenix, LiteLLM. Each exposed via
  NodePort, so they're reachable at `http://localhost:<nodePort>` from the host with no
  `kubectl port-forward` step.
- **On the host** (`uv run python run_all.py`, or `make demo`): the three patterns +
  `run_all.py`, talking to the NodePort-exposed services above. No Dockerfile, no image
  build, no Job — the agent code never runs inside the cluster.
- **Already on the host**: Ollama (`:11434`), reached from *inside* the LiteLLM pod via
  `host.docker.internal`.

Environment this was built and verified against: colima (`docker` runtime), k3s
(`kubectl config current-context` → `colima`), Ollama running natively on the Mac host on
`:11434`. Verified during setup:
- `host.docker.internal` resolves from inside pods and reaches the host's Ollama —
  `kubectl run hostcheck --rm -i --image=alpine -- wget -qO- http://host.docker.internal:11434/api/version`
- NodePort services are reachable from the host at `http://localhost:<nodePort>` (not via
  the k3s node's own IP, which times out from the host on this colima network setup) —
  confirmed against the cluster's pre-existing `litellm-guard` NodePort service before
  picking ports for this demo's services.

## Backend selection (`common/llm.py`)

There is exactly one real backend: **LiteLLM**, which fronts Ollama. `common/llm.py` never
talks to Ollama or Anthropic directly — it only knows LiteLLM's OpenAI-compatible
`/chat/completions` shape (via `httpx`), calling it
with `model` set to the alias `"agent"` or `"judge"`; LiteLLM's own config resolves those
aliases to real Ollama models. If the proxy isn't reachable at all (connection refused —
e.g. k8s isn't up), the call transparently falls back to a canned response from
`STUB_RESPONSES`, so the original zero-setup, $0-cost, offline path still works. The
Anthropic backend that used to exist here has been removed entirely along with the
dependency.

LiteLLM's base URL and the demo's synthetic per-token pricing (used only for pattern 1's
session-cost-budget eval — local inference is actually free) live in **`config.yaml`** at
the repo root, loaded once via `common/config.py`. Since the agent always runs on the host,
`config.yaml`'s default (`http://localhost:30401`, LiteLLM's NodePort) is what actually
gets used day to day; `LITELLM_BASE_URL` env var can still override it.

`call_llm()` takes a `model_role: str = "agent"` parameter. `evaluators.py`'s `llm_judge`
and `harness_judge` pass `model_role="judge"`, so evaluation runs on a smaller/faster
model than the agent turns — matching the blog's own distinction between generating a
response and judging one.

## Tracing (`common/tracing.py`)

Same shape as the LLM backend: `PHOENIX_COLLECTOR_ENDPOINT` env var, falling back to
`config.yaml`'s `phoenix.collector_endpoint` (`http://localhost:30317`, Phoenix's OTLP-gRPC
NodePort). The old in-process `launch_app()` fallback is gone — Phoenix is now always the
k8s Deployment, never spun up inline. `init_tracing()` prints `config.yaml`'s
`phoenix.ui_url` (`http://localhost:30606`) once per run so you know where to look.

## Why LiteLLM in front of Ollama

`common/llm.py` only needs to know one HTTP shape regardless of what's actually serving
the model. LiteLLM's own `config.yaml` (distinct from the repo-root one above — this one
lives in a ConfigMap and is mounted into the LiteLLM pod) is the only place that knows
about real Ollama model tags, via two named aliases:

```yaml
model_list:
  - model_name: agent
    litellm_params:
      model: os.environ/AGENT_MODEL      # e.g. ollama/llama3.1:8b
      api_base: os.environ/OLLAMA_API_BASE
  - model_name: judge
    litellm_params:
      model: os.environ/JUDGE_MODEL      # e.g. ollama/qwen3:0.6b
      api_base: os.environ/OLLAMA_API_BASE
```

That file never changes. Swapping models means patching the `arize-ollama-models`
ConfigMap (`AGENT_MODEL` / `JUDGE_MODEL` / `OLLAMA_API_BASE`) and
`kubectl rollout restart deploy/arize-litellm` — no manifest templating anywhere.
`scripts/discover_ollama_models.sh` picks sane defaults from `ollama list` output; the
ConfigMap ships with working hardcoded defaults (`llama3.1:8b` / `qwen3:0.6b`) so
`kubectl apply -f k8s/` works with zero extra steps even if discovery is never run.

The cluster already runs an unrelated `litellm-guard` (Deployment + NodePort 30400) in the
`default` namespace. Everything here also lives in `default` (no dedicated namespace —
keeps `kubectl get pods`/`svc` simple, matches where `litellm-guard` already is), but this
demo's LiteLLM is named `arize-litellm` and uses NodePort 30401 — distinct name and port,
no conflict. Phoenix's NodePorts (30606 UI, 30317 OTLP-gRPC) are similarly clear of both.

## Phoenix: Postgres-backed, not sqlite/emptyDir

Phoenix's docker image defaults to sqlite-on-disk. In k8s that would mean either losing
all trace data on every pod restart (emptyDir) or dealing with ReadWriteOnce PVC
attach/detach semantics for a single sqlite file. Instead Phoenix points at a small
Postgres deployment (`PHOENIX_SQL_DATABASE_URL=postgresql://postgres:postgres@postgres:5432/postgres`),
matching the pattern in Phoenix's own reference `docker-compose.yml`. Postgres itself
gets a 1Gi PVC (colima's k3s ships `local-path` as the default StorageClass, so this needs
no extra setup). Net effect: traces survive pod restarts and repeated demo runs.

## k8s layout

Namespace `default`; files in `k8s/` are numerically prefixed so `kubectl apply -f k8s/`
applies them in a sane order (postgres → phoenix → litellm):

```
10-postgres-deployment.yaml   11-postgres-service.yaml
12-phoenix-deployment.yaml    13-phoenix-service.yaml   (NodePort 30606, 30317)
20-litellm-config.yaml        21-litellm-models.yaml
22-litellm-deployment.yaml    23-litellm-service.yaml   (NodePort 30401)
```

`kubectl apply -f k8s/` alone brings up everything the demo needs, using the default
models. It's idempotent — re-running it is a no-op when nothing changed.

## scripts/ and Makefile

`scripts/` are small, single-purpose bash scripts meant to be called by `Makefile` targets,
not run standalone:

- `discover_ollama_models.sh` — parses `ollama list`, prints `AGENT_MODEL=`/`JUDGE_MODEL=`
  (bare tags)
- `apply_k8s.sh` — `kubectl apply -f k8s/`, waits for the postgres/phoenix/litellm rollouts
- `configure_ollama.sh` — re-runs discovery, patches the `arize-ollama-models` ConfigMap,
  restarts `deploy/arize-litellm`

`Makefile` targets: `setup` (`uv sync`), `apply`, `configure`, `demo` (`uv run python
run_all.py`), `demo-01`..`demo-05`, `status`, `clean` (`kubectl delete -f k8s/`). `demo`
itself has no `setup`/`apply` prerequisite -- it just runs `run_all.py` against whatever's
already there, so the same command is both the zero-setup offline path (nothing else
running, stub responses) and the real-models path (after `apply`/`configure`), depending on
what you ran first.
