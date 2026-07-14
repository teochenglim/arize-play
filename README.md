# 3 agent patterns, evaluated

A minimal, runnable version of the three production agent patterns from
Arize's post [3 production patterns for AI agents and how to evaluate each
one](https://arize.com/blog/3-production-patterns-ai-agents-how-to-evaluate-each-one/)
(Sam Bhagwat / Mastra, Arize Observe 2026).

One folder per pattern, ~100 lines each, all wired into
[Phoenix](https://phoenix.arize.com/) (Arize's open-source tracing + eval
tool). No account, no API key, no cloud LLM required to see it run -- Phoenix
and an LLM proxy ([LiteLLM](https://www.litellm.ai/)) run in local k8s,
fronting whatever models you already have pulled in
[Ollama](https://ollama.com/).

Each demo also has a nickname and a named failure mode -- useful shorthand
when talking through them live -- plus a mapping to the [OWASP Top 10 for
LLM Applications 2025](https://genai.owasp.org/llm-top-10/).

| # | Demo &middot; nickname &middot; &#128293; failure mode | Who builds it | This demo's use case | The one-liner | First production risk (per the article) | OWASP mapping |
|---|---|---|---|---|---|---|
| 1 | [demo-01.md](demo-01.md) -- "The Wrong Kavya" &middot; Context Rot | Product teams | In-app HR assistant answering from a flat-file employee lookup | Retrieval quietly returns a stale/wrong record, the LLM answers fluently and confidently on top of it -- classic context rot wearing a friendly voice | Incomplete pre-launch evals -- a flawed retriever silently attaches the wrong person's data | LLM09:2025 Misinformation + LLM02:2025 Sensitive Information Disclosure |
| 2 | [demo-02.md](demo-02.md) -- "The Ticket That Never Was" &middot; Silent Tool Failure | Platform/ops teams | Expense approval process automation | A tool call no-ops, the workflow marches on like nothing happened -- the agent equivalent of a phantom commit | Org friction; fragmented data systems | LLM06:2025 Excessive Agency |
| 3 | [demo-03.md](demo-03.md) -- "The Incident That Almost Wasn't" &middot; False Negative / Alert Fatigue | Infra/platform engineering | AI SRE triaging logs, opens incidents | "All clear" gets logged while the container burns -- a confidently wrong "nothing to see here" | Governance; standardizing the harness | LLM09:2025 Misinformation |
| 4 | [demo-04.md](demo-04.md) -- "Proof, Not Vibes" &middot; Eval Debt, Paid Down | Anyone iterating on a fix from 1-3 | Same HR bug, proven fixed (or not) via Phoenix's Datasets/Prompts/Experiments UI, across all 6 employees | A prompt fix that felt right gets run against every case at once -- vibe-shipping turned into 2/6 &rarr; 6/6 | Proving a fix works before shipping it, not just catching the break | LLM02:2025 Sensitive Information Disclosure |
| 5 | [demo-05.md](demo-05.md) -- "Nobody Reads the Card Number Twice" &middot; Output Sanitization Gap | Anyone whose assistant handles payment data | Billing assistant asked to "confirm" a card, proven not to leak the full number across 6 customers | A full card number slips into a chat log unredacted -- and the redaction that looked fixed hallucinates its own digits | An assistant being "helpful" -- no hack, no attack, just a field it should never echo in full | LLM02:2025 Sensitive Information Disclosure + LLM05:2025 Improper Output Handling |

Every run is also tagged with `session.id`, `user.id`, a `run.timestamp`,
and its own `trace.id` (OpenInference's session/user semconv attributes),
printed as a copy/paste block for the Phoenix search bar -- see
[demo-01.md](demo-01.md)'s "Finding this run again in Phoenix" section.

## Quickstart

Offline, zero setup -- runs on canned LLM responses, $0 cost, no network:

```bash
make setup   # uv sync
make demo    # uv run python run_all.py
```

Against real local models instead: Phoenix + LiteLLM run in your local k8s
cluster (tested against [colima](https://github.com/abiosoft/colima)'s
bundled k3s), LiteLLM fronts whatever's in `ollama list` on the host. The
demo agent itself stays a normal local process -- it's never containerized,
just `uv run`.

```bash
make apply       # kubectl apply -f k8s/, wait for rollout
make configure   # point arize-litellm at your local ollama models
make demo        # same command as above -- now against real models
```

Open **http://localhost:30606** while it runs to watch the traces land live
in Phoenix -- click into any span to see the eval scores attached as
attributes. See [design.md](design.md) for how the k8s side is wired
together (`kubectl apply -f k8s/` and `kubectl delete -f k8s/` work standalone
too, no Makefile required) and `Makefile` for the rest of the targets
(`apply`, `configure`, `status`, `clean`).

Demos 4 and 5 ([demo-04.md](demo-04.md), [demo-05.md](demo-05.md)) are
separate from the other three -- same Phoenix Datasets/Prompts/Experiments
workflow, two different scenarios (an identity-mismatch leak, a
credit-card leak). Both talk to Phoenix's REST API directly, which has no
offline stub fallback, so Phoenix needs to actually be up first:

```bash
make apply    # if Phoenix isn't already running
make demo-04
make demo-05
```

To send traces to Arize AX (cloud) instead of local Phoenix:

```bash
export PHOENIX_COLLECTOR_ENDPOINT=https://otlp.arize.com/v1/traces
export PHOENIX_CLIENT_HEADERS="space_id=...,api_key=..."
uv run python run_all.py
```

## What "the Arize values" means here

The article draws two distinctions that this demo makes concrete:

**Where an eval attaches** (`common/evaluators.py`, per pattern's `agent.py`):

| Level | What you score | Used in this demo for |
|---|---|---|
| Span | one tool call or model turn | `tool:create_ticket`, `tool:create_incident` |
| Trace | the full run, input to final answer | every pattern's ship-gate eval |

**Which evaluator type you reach for**:

| Type | No model call? | Used in this demo for |
|---|---|---|
| `code_evaluator` | yes | pattern 1's `ground_truth_arbiter` (re-reads `employees.json` fresh, strict number match); pattern 2's workflow-state check (ticket exists before status flips to complete) |
| `binary_evaluator` | no, but one named failure mode | pattern 1's `identity_lock` (retrieved record's name vs. the user's); pattern 3's `missed_critical_incident` |
| `harness_judge` | no, full trace context | pattern 1's `no_invented_deductions`; pattern 3's `triage_quality` (sees every log line + tool call, not just the last line) |

Run each score is attached to its span as `eval.<name>.score` /
`eval.<name>.label` / `eval.<name>.explanation` -- open Phoenix and click a
span to see them sit next to the trace they came from, exactly where the
article says an eval belongs.

## The improvement loop, played out once

Pattern 1 (`pattern1_customer_facing/agent.py`) plays out the same loop
against a deliberately flawed **retriever**, not the LLM -- see
[demo-01.md](demo-01.md) for the full story:

1. **Trace the run** -- the retriever matches "Kavya" by first name, then
   for any balance/deduction question throws that match away and returns
   the highest-tenure employee company-wide instead (Wei Jian Lim)
2. **Evaluate the failure** -- `identity_lock` and `ground_truth_arbiter`
   both come back `fail`
3. **Change the harness** -- swap the retriever's fuzzy first-name +
   tenure-fallback logic for an exact full-name match
4. **Rerun** -- same question, both evals now `pass`

```
$ uv run python pattern1_customer_facing/agent.py
=== run 1: retriever WITH the highest-tenure fallback bug ===
retrieved record: Wei Jian Lim (tenure=10y)
agent answer: Kavya Menon, you have 19 days of leave left. ...
eval[identity_lock]: fail (query identity='Kavya Menon' vs retrieved_employee_record.employee='Wei Jian Lim')
eval[ground_truth_arbiter]: fail (answer claims leave balance in [19] for Kavya Menon; ground truth = 0)

--- fix the retriever: exact full-name match instead of first-name-prefix + tenure fallback ---

=== run 2: retriever WITH the fix, same question ===
retrieved record: Kavya Menon (tenure=5y)
agent answer: Kavya Menon, you have 0 days of leave left. ...
eval[identity_lock]: pass (query identity='Kavya Menon' vs retrieved_employee_record.employee='Kavya Menon')
eval[ground_truth_arbiter]: pass (answer claims leave balance in [0] for Kavya Menon; ground truth = 0)
```

Pattern 3 (`pattern3_developer_platform/agent.py`) runs the same loop
against a missed-incident harness gap, so you can point at it live too:

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
  tracing.py     one call, wires any pattern into k8s Phoenix or Arize AX; session/user/trace-id tagging
  llm.py         LiteLLM call w/ offline stub fallback; consistent span shape either way
  evaluators.py  the four evaluator types, one small function each
  console.py     ANSI color helpers for audience-facing console output
  config.py      loads config.yaml (LiteLLM/Phoenix addresses, model tags, demo pricing)
pattern1_customer_facing/agent.py
pattern2_internal_enterprise/agent.py
pattern3_developer_platform/agent.py
pattern4_improvement_loop/agent.py       Phoenix Datasets + Prompts + Experiments, see demo-04.md
pattern5_credit_card_redaction/agent.py  same workflow as pattern 4, catching credit-card leaks -- see demo-05.md
run_all.py       runs patterns 1-3, prints the consolidated eval table (patterns 4-5 are standalone, see above)
config.yaml      LiteLLM/Phoenix NodePort addresses, Ollama model tags, per-token pricing
k8s/             Postgres + Phoenix + LiteLLM manifests -- `kubectl apply -f k8s/`
scripts/         discover_ollama_models.sh, configure_ollama.sh (called by `make configure`)
Makefile         demo, demo-01..demo-05, apply, configure, status, clean
design.md        why the k8s/LiteLLM/Ollama setup is shaped this way
```

## Deliberately left out

This is a demo of the eval/observability wiring, not a reference
architecture. It skips: real retrieval/RAG, real ticketing/expense system
APIs, staged rollout percentages, a human-labeling UI, and the
error-analysis clustering step the article calls out as step 2 of the real
loop (demo 4's dataset is hand-picked, not mined from production traces via
Phoenix's own UI, though that's the realistic next step from here). Each is
a straight line from what's here -- swap the stub systems in patterns 1/2
for real APIs, and swap `code_evaluator`/`binary_evaluator` thresholds for
ones calibrated against human labels before trusting them in production.
