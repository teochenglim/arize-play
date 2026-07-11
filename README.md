# 3 agent patterns, evaluated

A minimal, runnable version of the three production agent patterns from
Arize's post [3 production patterns for AI agents and how to evaluate each
one](https://arize.com/blog/3-production-patterns-ai-agents-how-to-evaluate-each-one/)
(Sam Bhagwat / Mastra, Arize Observe 2026).

One folder per pattern, ~100 lines each, all wired into
[Phoenix](https://phoenix.arize.com/) (Arize's open-source tracing + eval
tool). No docker, no account, no API key required to see it run.

| # | Pattern | Who builds it | This demo's use case | First production risk (per the article) |
|---|---|---|---|---|
| 1 | Customer-facing | Product teams | In-app HR assistant answering from account-scoped data | Inference cost at scale; incomplete pre-launch evals |
| 2 | Internal enterprise | Platform/ops teams | Expense approval process automation | Org friction; fragmented data systems |
| 3 | Developer platform | Infra/platform engineering | AI SRE triaging logs, opens incidents | Governance; standardizing the harness |

## Quickstart

```bash
pip install -r requirements.txt
python3 run_all.py
```

That's it. It launches Phoenix locally, runs all three patterns on canned
LLM responses (no API key, no network, $0 cost), evaluates each run, and
prints a consolidated table. Open **http://localhost:6006** while it runs
to watch the traces land live -- click into any span to see the eval
scores attached as attributes.

To use a real model instead of canned responses:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 run_all.py
```

Same code path, same spans -- just real `claude-haiku-4-5` calls and real
token counts instead of stub numbers.

To send traces to Arize AX (cloud) instead of local Phoenix:

```bash
export PHOENIX_COLLECTOR_ENDPOINT=https://otlp.arize.com/v1/traces
export PHOENIX_CLIENT_HEADERS="space_id=...,api_key=..."
python3 run_all.py
```

## What "the Arize values" means here

The article draws two distinctions that this demo makes concrete:

**Where an eval attaches** (`common/evaluators.py`, per pattern's `agent.py`):

| Level | What you score | Used in this demo for |
|---|---|---|
| Span | one tool call or model turn | `tool:create_ticket`, `tool:create_incident` |
| Trace | the full run, input to final answer | every pattern's ship-gate eval |
| Session | a multi-turn visit | pattern 1's cost-budget check across 2 turns |

**Which evaluator type you reach for**:

| Type | No model call? | Used in this demo for |
|---|---|---|
| `code_evaluator` | yes | pattern 1 session cost budget; pattern 2 workflow-state check (ticket exists before status flips to complete) |
| `binary_evaluator` | no, but one named failure mode | pattern 3's `missed_critical_incident` |
| `llm_judge` | no | pattern 1's `grounded_in_account_context` (final answer only) |
| `harness_judge` | no, full trace context | pattern 3's `triage_quality` (sees every log line + tool call, not just the last line) |

Run each score is attached to its span as `eval.<name>.score` /
`eval.<name>.label` / `eval.<name>.explanation` -- open Phoenix and click a
span to see them sit next to the trace they came from, exactly where the
article says an eval belongs.

## The improvement loop, played out once

Pattern 3 (`pattern3_developer_platform/agent.py`) runs the loop from the
article on purpose, so you can point at it live:

1. **Trace the run** -- harness v1 has no example of the OOM-kill failure signature
2. **Evaluate the failure** -- `missed_critical_incident` comes back `fail`
3. **Change the harness** -- one sentence added to the system prompt (not a bigger model, not more logs)
4. **Rerun** -- same logs, `missed_critical_incident` now `pass`

```
$ python3 pattern3_developer_platform/agent.py
=== run 1: harness WITHOUT the OOM-kill example ===
agent output: no incident
eval[missed_critical_incident]: fail (... incident was NOT raised)
eval[triage_quality] (harness-as-judge): 1/5

--- change the harness: add the OOM-kill signature to the system prompt ---

=== run 2: harness WITH the fix, same logs ===
agent output: INCIDENT: severity=critical, summary=worker-2 container OOM-killed on job 4471
eval[missed_critical_incident]: pass (... incident was raised)
eval[triage_quality] (harness-as-judge): 5/5
```

## Repo layout

```
common/
  tracing.py     one call, wires any pattern into local Phoenix or Arize AX
  llm.py         Claude call w/ offline stub fallback; consistent span shape either way
  evaluators.py  the four evaluator types, one small function each
pattern1_customer_facing/agent.py
pattern2_internal_enterprise/agent.py
pattern3_developer_platform/agent.py
run_all.py       runs all three, prints the consolidated eval table
```

## Deliberately left out

This is a demo of the eval/observability wiring, not a reference
architecture. It skips: real retrieval/RAG, real ticketing/expense system
APIs, staged rollout percentages, a golden-set/labeling UI, and the
error-analysis clustering step the article calls out as step 2 of the real
loop. Each is a straight line from what's here -- swap the stub systems in
patterns 1/2 for real APIs, and swap `code_evaluator`/`binary_evaluator`
thresholds for ones calibrated against human labels before trusting them
in production.
