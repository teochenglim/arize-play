# Demo 1: Customer-facing agent (in-app HR assistant)

**File:** `pattern1_customer_facing/agent.py` · **Who builds this:**
product teams · **Users bring a question, the product brings their
account-scoped data.**

**Run it:** `make demo-01` (or `make local-demo` to run all three patterns)

## The scenario

An in-app HR assistant answers "what's my leave balance" style questions.
There's no vector DB, no SQL — just `employees.json` sitting next to the
script, loaded straight into a Python list. Arize doesn't care whether
retrieval is a vector DB, a SQL query, or a flat-file dict lookup; it only
cares about the trace: what record got fetched, and what the model said
based on it. That's what makes this bug reproducible with zero
infrastructure.

## What the code does

1. `employees.json` holds six employees, including **Kavya Menon** (0 leave
   days left) and **Wei Jian Lim** (10 years' tenure, 19 leave days left)
   ([employees.json](pattern1_customer_facing/employees.json)).
2. **The retriever, with a bug on purpose** — `retrieve_employee()` pulls the
   name out of the question ("I'm Kavya Menon") and matches it by first
   name. But for any question containing "balance" or "deduction", it
   throws that match away and returns whichever employee has the *highest
   tenure company-wide* instead — under the flawed assumption that senior
   staff have the most complex payslips
   ([agent.py:54-74](pattern1_customer_facing/agent.py#L54-L74)).
3. The wrong record gets written straight into the trace as a
   `retrieved_employee_record` span attribute, next to the original
   `user_query` — so the mismatch is visible before the LLM ever runs
   ([agent.py:138-142](pattern1_customer_facing/agent.py#L138-L142)).
4. The LLM answers using *only* the retrieved record's numbers, but
   addresses the user by the name *they* gave — so it confidently tells
   "Kavya" she has Wei Jian's 19 days
   ([agent.py:144-164](pattern1_customer_facing/agent.py#L144-L164)).
5. Three evals run on every turn: `identity_lock`, `ground_truth_arbiter`,
   `no_invented_deductions` (all below).
6. Every turn's root span is tagged with a `session.id` (shared by run 1 and
   run 2 -- same underlying conversation, before/after the fix), a `user.id`
   (the name the caller introduced themselves with), a `run.timestamp`, and
   the run's own OTel `trace.id` -- see `tag_session()` in
   [common/tracing.py](common/tracing.py) and its call site at
   [agent.py:145](pattern1_customer_facing/agent.py#L145).

## Before Arize: what's invisible

The agent's reply reads perfectly fine on its own: *"Kavya Menon, you have
19 days of leave left. Deductions on your last payslip: CPF employee 20%,
SDL 0.25%, Season parking SGD 120."* Fluent, specific, on-topic — nothing
about the text signals that every number in it belongs to someone else. A
support rep skimming a chat log would have no reason to doubt it.

## After Arize: what gets caught

**`identity_lock` (`binary_evaluator`, trace-level).** Extracts the name
the user gave from `user_query` and compares it to
`retrieved_employee_record.employee` — no model call, just a string
comparison. Real run:

> query identity='Kavya Menon' vs retrieved_employee_record.employee='Wei Jian Lim'
> → **fail**

**`ground_truth_arbiter` (`code_evaluator`, trace-level).** Re-reads
`employees.json` fresh off disk — the immutable ground-truth oracle — finds
whichever employee the final answer is actually about, and strictly
compares the number the LLM claimed against the real one:

> answer claims leave balance in [19] for Kavya Menon; ground truth (fresh
> from employees.json) = 0 → **fail**

This one catches the hallucination even if you never looked at the
retrieved record at all — it only trusts the flat file, not the trace.

**`no_invented_deductions` (`harness_judge`, trace-level).** A cheap judge
model checks whether the answer lists any deduction not present in the
retrieved record. On this run it passes (5/5) — the bug is in *which*
record got retrieved, not in the model inventing extra line items on top
of it. Worth showing precisely because it's a clean pass: it proves the
other two evals are catching a *retrieval* failure, not just any
old-fashioned hallucination.

## The fix, and the rerun

Swap `retrieve_employee()`'s fuzzy first-name-plus-tenure-fallback for an
exact full-name match, and rerun the exact same question:

> retrieved record: **Kavya Menon** (tenure=5y)
> agent answer: *"Kavya Menon, you have 0 days of leave left. Deductions on
> your last payslip: CPF employee 20%, SDL 0.25%."*
> eval[identity_lock]: **pass**
> eval[ground_truth_arbiter]: **pass**

Both evals jump from fail to pass with no change to the LLM, the prompt, or
the model — because the LLM was never the bug.

## Finding this run again in Phoenix

Each run's console output ends with a copy/paste block:

```
find this run in Phoenix (search bar, top of the Traces table):
  trace.id      = 38dd5af4f7d1cef03b4a7a4beec1e75e
  session.id    = dd1ca8f6-1bf6-409a-9c27-6ed096f75a9a
  user.id       = kavya.menon
  run.timestamp = 2026-07-11T12:24:49.168208+00:00
```

- **`trace.id`** — paste the 32-hex value straight into the search bar to
  jump to this exact run's trace.
- **`session.id`** — the same UUID on both run 1 and run 2 (buggy vs. fixed
  retriever): open Phoenix's **Sessions** view and this pair groups together
  as one conversation, so you can flip between the before/after runs
  side by side.
- **`user.id`** — `kavya.menon` here; in a multi-tenant deployment this is
  how you'd filter to "every trace for this one user."
- **`run.timestamp`** — ISO-8601, for "what happened around 2pm" style
  audit questions.

## Talking point

> Arize doesn't need to know your retrieval is a vector DB to catch a
> retrieval bug — it needs the trace. A fluent, confident, wrong answer
> looks identical to a correct one in a chat log; it only becomes visible
> once you write down what was actually retrieved and check it against a
> ground truth the model never gets to touch.
