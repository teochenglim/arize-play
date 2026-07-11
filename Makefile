.DEFAULT_GOAL := help
.PHONY: help setup apply configure demo demo-01 demo-02 demo-03 demo-04 demo-05 status logs clean

help: ## Show this target list
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*## /{printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## uv sync
	uv sync

apply: ## kubectl apply -f k8s/ (postgres + phoenix + arize-litellm), wait for rollout
	kubectl apply -f k8s/
	kubectl rollout status deployment/postgres --timeout=60s
	kubectl rollout status deployment/phoenix --timeout=60s
	kubectl rollout status deployment/arize-litellm --timeout=60s

configure: ## Re-discover local Ollama models, point arize-litellm at them
	./scripts/configure_ollama.sh

demo: ## Run all 3 patterns (run_all.py) against k8s Phoenix/LiteLLM
	uv run python run_all.py

demo-01: ## Run only pattern 1 (customer-facing HR assistant)
	uv run python pattern1_customer_facing/agent.py

demo-02: ## Run only pattern 2 (expense approval workflow)
	uv run python pattern2_internal_enterprise/agent.py

demo-03: ## Run only pattern 3 (AI SRE triage loop)
	uv run python pattern3_developer_platform/agent.py

demo-04: ## Run only pattern 4 (Phoenix Prompts + Datasets + Experiments -- needs Phoenix's REST API, unlike demo-01..03 it can't fall back to offline stubs)
	uv run python pattern4_improvement_loop/agent.py

demo-05: ## Run only pattern 5 (catch credit-card leaks, same Prompts+Datasets+Experiments workflow as demo-04 -- also needs Phoenix's REST API)
	uv run python pattern5_credit_card_redaction/agent.py

status: ## Show postgres/phoenix/arize-litellm deploy, svc, and pod status
	kubectl get deploy/postgres deploy/phoenix deploy/arize-litellm svc/postgres svc/phoenix svc/arize-litellm
	kubectl get pods -l 'app in (postgres,phoenix,arize-litellm)'

logs: ## Tail arize-litellm logs
	kubectl logs -f deployment/arize-litellm

clean: ## kubectl delete -f k8s/
	kubectl delete -f k8s/
