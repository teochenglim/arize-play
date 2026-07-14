# Demo 2: Internal enterprise agent (expense approval)

**"The Ticket That Never Was"** · 🔥 Silent Tool Failure -- a tool call
no-ops, the workflow marches on like nothing happened: the agent equivalent
of a phantom commit.

**File:** `pattern2_internal_enterprise/agent.py` · **Who builds this:**
platform/ops teams · **One high-volume internal workflow, not a chatbot.**

**Run it:** `make demo-02`

**OWASP (2025):** LLM06:2025 Excessive Agency

## The scenario

An org-scale process — expense approvals — gets automated. No end user is
chatting with this; it's a workflow, plumbing between systems. Four requests
come in from `expenses.json`. An LLM call *is* in the loop (it applies the
approval policy per request), but it's a thin, low-stakes one — per the
article, this pattern's risk isn't model quality, it's org friction and
fragmented data systems, and the bug below proves it: the model gets its
one job right every time, the harness is what silently drops the ball.

## What the code does

1. A policy prompt — "approve if `travel`/`training` and under SGD 500,
   else reject, reply APPROVE or REJECT" — sent to the LLM per request as an
   OpenInference `LLM` span, same shape as patterns 1 and 3
   ([agent.py:98-106](pattern2_internal_enterprise/agent.py#L98-L106)). If
   the LLM backend is unreachable it falls back to the equivalent rule-based
   conditional, so the offline demo still reproduces the table below
   deterministically.
2. Two *simulated but separate* systems: a ticketing system and an expense
   system ([agent.py:35-36](pattern2_internal_enterprise/agent.py#L35-L36)) —
   standing in for real, fragmented enterprise APIs (ServiceNow, SAP, …), per
   the article.
3. **The deliberate bug** — `create_ticket()` silently skips ticket creation
   for any request in the `equipment` category, as if that category routed
   to a system that was never properly wired
   ([agent.py:47-55](pattern2_internal_enterprise/agent.py#L47-L55)). The
   expense still gets marked COMPLETE regardless
   ([agent.py:58-61](pattern2_internal_enterprise/agent.py#L58-L61)).
4. Every request's root span carries a shared `session.id` (this whole
   four-request batch is one session), a per-employee `user.id`, a
   `run.timestamp`, and its own `trace.id`
   ([agent.py:88](pattern2_internal_enterprise/agent.py#L88)) — the same
   four attributes patterns 1 and 3 use, so any single request is
   searchable in Phoenix later by whichever of the four you remember.

## Before Arize: what's invisible

The article's risk for this pattern isn't model quality — it's **org friction
and fragmented data systems**. The dangerous failure here isn't bad prose,
it's *a workflow reaching a COMPLETE state with no audit trail behind it*.
A normal decision log — `REQ-1002: equipment SGD 1200 -> REJECT` — looks
completely fine either way. Nothing about a REJECT line hints that the
ticket step silently no-opped; you cannot tell from the output whether the
invariant held.

## After Arize: what gets caught

**Trace-level `code_evaluator` — `ticket_created_before_status_complete`.**
No model call at all — a deterministic check against workflow *state*: does
a ticket exist for this request before its status is allowed to read
"COMPLETE"? Real run:

> REQ-1001: travel, SGD 240 → **APPROVE** — `ticket_created=True,
> status=COMPLETE` → **pass**
>
> REQ-1002: equipment, SGD 1200 → **REJECT** — `ticket_created=False,
> status=COMPLETE` → **fail**
>
> REQ-1003: training, SGD 450 → **APPROVE** — `ticket_created=True,
> status=COMPLETE` → **pass**
>
> REQ-1004: meals, SGD 600 → **REJECT** — `ticket_created=True,
> status=COMPLETE` → **pass**

The deliberate design choice: this eval checks the *constraint*, not a fixed
*sequence* of tool calls. The agent might legitimately check policy before or
after creating the ticket and still be correct — a code eval pinned to "call
order must be X, then Y" would false-fail a correct run. Pinning it to
workflow state instead is what makes the eval reusable as the harness
evolves, and it's exactly why it catches REQ-1002: the bug isn't in the
*order* of steps, it's in one category silently never reaching the
ticketing system at all.

## Finding this run again in Phoenix

Each request's console output ends with a copy/paste block, e.g. for
REQ-1002:

```
find this run in Phoenix (search bar, top of the Traces table):
  trace.id      = 48706db87a52604dee7fd51bda7045c7
  session.id    = 87fc051f-b32b-4980-a2c4-646cb3fd4c63
  user.id       = aisha.rahman
  run.timestamp = 2026-07-11T12:25:23.129097+00:00
```

`session.id` is the same UUID across all four requests in the batch — open
Phoenix's **Sessions** view and the whole run groups together, so you can
see REQ-1002's silent-drop sitting right next to the three requests that
worked. `user.id` filters to one employee's expense history; `trace.id`
jumps straight to this one request's trace for the deep dive.

## Talking point

> For workflow automation, the eval that matters is deterministic and free — did
> the system end up in a consistent state — not a judge's opinion of the prose.
> This one costs nothing to run and never drifts, and it caught a
> category-specific integration gap that a per-request log line never would.
