# Demo 2: Internal enterprise agent (expense approval)

**File:** `pattern2_internal_enterprise/agent.py` · **Who builds this:**
platform/ops teams · **One high-volume internal workflow, not a chatbot.**

**Run it:** `make demo-02` (or `make local-demo` to run all three patterns)

## The scenario

An org-scale process — expense approvals — gets automated. No end user is
chatting with this, and there's no LLM call at all: it's a rules-based
workflow, plumbing between systems. Four requests come in from
`expenses.json`.

## What the code does

1. A policy rule: expenses under SGD 500 in `travel`/`training` auto-approve
   ([agent.py:72](pattern2_internal_enterprise/agent.py#L72)).
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

## Talking point

> For workflow automation, the eval that matters is deterministic and free — did
> the system end up in a consistent state — not a judge's opinion of the prose.
> This one costs nothing to run and never drifts, and it caught a
> category-specific integration gap that a per-request log line never would.
