# Demo 3: Developer platform agent (AI SRE triage)

**File:** `pattern3_developer_platform/agent.py` · **Who builds this:**
infra/platform engineering · **Builds a harness other engineers rely on.**

**Run it:** `make demo-03` (or `make local-demo` to run all three patterns)

## The scenario

An AI SRE reads a batch of raw logs and is supposed to open an incident the
moment it sees something critical.

## What the code does

1. A fixed batch of 4 log lines with one buried failure: a worker OOM-killed,
   exit code 137, loaded fresh from
   [logs.json](pattern3_developer_platform/logs.json) each run
   ([agent.py:33-35](pattern3_developer_platform/agent.py#L33-L35)).
2. **Harness v1** — a generic system prompt: "flag critical failures"
   ([agent.py:44-48](pattern3_developer_platform/agent.py#L44-L48)).
3. **Harness v2** — v1 plus *one sentence* teaching the exact OOM-kill signature
   ([agent.py:53-57](pattern3_developer_platform/agent.py#L53-L57)). Not a
   bigger model, not more logs — the missing context, added on purpose so the
   loop below has something to fix.
4. Two evals run on *every* triage: `binary_evaluator` (`missed_critical_incident`
   — did it raise the incident, plain pass/fail) and `harness_judge`
   (`triage_quality` — sees the *entire* trace: system prompt + logs + output,
   not just the last line, scored 1–5).

## Before Arize: what's invisible

The article's advice for this pattern specifically isn't "pick a smarter
model" — it's **run the loop from day one**: trace the run, evaluate the
failure, fix the harness, rerun. Without tracing you can't see *which* log line
the agent missed or why — "no incident" just reads as a quiet log, not a miss.

## After Arize: what gets caught — and an honest surprise

The scripted story (and what you'll see if you run this offline, on canned
responses): harness v1 misses the OOM-kill, eval fails; harness v2's one added
sentence fixes it, eval passes. Clean before/after.

Here's what actually happened running it against a real local model
(`llama3.1:8b`):

> **Run 1 (harness v1, no hint), `make demo-03`:** *"INCIDENT: CRITICAL:
> Container memory exhaustion caused job failure."* →
> `missed_critical_incident`: **pass** · `triage_quality`: **5/5**
>
> **Run 2 (harness v2, with hint):** *"INCIDENT: Critical OOM-killed container
> with exit code 137."* → `missed_critical_incident`: **pass** ·
> `triage_quality`: **5/5**

Both passed. An 8B model didn't need the hint — it caught the OOM signature on
its own. That's worth saying out loud, not glossing over: swap a canned
response for a real, reasonably capable model, and the specific gap you
scripted the harness fix around may not reproduce.

That's not a failure of the demo — it's the loop doing exactly its job one
level up. The loop isn't only for catching a miss; it's also for telling you
**your test case stopped being hard enough to be worth running.** The next
step, in a real harness, is the same loop again: find or construct a *harder*
failure signature your current harness actually misses, and let the eval prove
the fix.

One more thing to point at: `triage_quality` is a `harness_judge`, not a plain
`llm_judge` — it sees the full trace (system prompt, every log line, the
output), not just the final answer. That matters here specifically because "how
many tool calls, in what order" is under-specified — a rubric graded on the
last line alone would be too rigid for a correct-but-unconventional run.

## Talking point

> The trace → evaluate → fix-the-harness → rerun loop isn't just for catching
> misses. Run it against a real model and sometimes what it tells you is that
> your test case went stale. That's still a useful result.
