# Demo 6: Which prompt is better?

**"Grade the Homework"** · 🔥 Vibe-Checked Prompt -- a friendly-sounding
prompt that quietly pads answers and invents facts, caught and scored
instead of eyeballed.

**File:** `pattern6_prompt_test/agent.py` · **Who builds this:** anyone
choosing between two versions of a prompt · **Run it:** `make apply` (if
Phoenix isn't already up), then `make demo-06` (about 1–2 minutes)

**OWASP (2025):** LLM09:2025 Misinformation

## The one-sentence version

Demo 4 proved a fix worked by checking one thing. This demo shows the
general move: take **two prompts**, run both on the same questions, and let
Phoenix **grade every answer** on **Correctness, Groundedness and
Relevance** so you get a score per prompt, not a feeling.

## The scenario

An HR chatbot answers questions about a four-sentence leave policy. We ask
**8 questions**: 5 can be answered from the policy (two need a little
arithmetic or reasoning), and 3 **cannot** (bonus, parental leave, dental
plan) -- a good bot must say "I don't know" instead of making something up.

| | Prompt |
|---|---|
| **Prompt 1** (first draft) | *"You are a friendly HR assistant. Answer the employee's question helpfully and completely, adding any useful tips."* |
| **Prompt 2** (the fix) | *"Answer using ONLY the CONTEXT. Be brief: one or two sentences. If the context does not contain the answer, reply exactly: I don't know."* |

Prompt 1 is a realistic first draft: nothing in it is wrong, but "helpful
and complete, add tips" invites padding and guessing.

## What gets scored

A judge model grades **every answer** with three pass/fail checks:

- **Correct** -- right answer, or an honest "I don't know" when the policy
  doesn't say.
- **Grounded** -- every fact comes from the policy text; nothing invented.
- **Relevant** -- answers the question without padding or unrelated tips.

Pass/fail rather than 1–5 on purpose: small local judges are much more
reliable at yes/no than at "is this a 3 or a 4". The score is simply
answers passed out of 8.

## What the code does

1. **Saves the 8 questions** (plus reference answers) as a Phoenix
   **Dataset**.
2. **Saves both prompts** as two tagged versions of one Phoenix **Prompt**,
   so their diff is browsable in the UI.
3. **Runs each prompt over every question** as a Phoenix **Experiment**,
   with Correct / Grounded / Relevant as three evaluators. One judge call
   per answer grades all three.
4. **Prints** every question with each prompt's actual answer, ✔/✘ per
   check with the judge's reason on failures, then a scoreboard.

## The result

Real run (`bonsai-2` as both answerer and judge):

```
                Prompt 1        Prompt 2
  Correct       8/8  (1.00)     8/8  (1.00)
  Grounded      1/8  (0.12)     8/8  (1.00)
  Relevant      0/8  (0.00)     8/8  (1.00)
  Overall       9/24  (0.38)    24/24  (1.00)

  Winner: Prompt 2
```

Both prompts mostly get the facts right -- **Correctness barely moves** --
but Prompt 1 buries every answer in friendly padding, tips and well-wishes,
which the judge fails on Groundedness and Relevance (**9/24 vs 24/24**).
That's the lesson: a prompt can look fine on "is it right?" and still be
the worse prompt. Three separate scores make that visible; one blended
score would hide it.

The full console output is in [outputs-demo-06.txt](outputs-demo-06.txt).

## Honest caveats

- **The judge is itself a small model.** In the sample run it passed one
  answer as Correct that said "19 days" when the right answer is 17 (Q4,
  Prompt 2). Small-judge noise like this is why you read the per-row notes,
  not just the totals -- and why you'd use a stronger judge for anything
  that matters.
- **8 questions is a demo, not a benchmark.** It shows the mechanism; a real
  suite would be bigger.
- **The same model answers and judges here** (`bonsai-2`), which can flatter
  its own answers. Point `judge_model` in `config.yaml` at a different model
  to remove that.

## Seeing it in the Phoenix UI

The script ends with a link to the dataset's Experiments tab: one row per
question, one column per prompt, scores in each cell, and the judge's
explanation on click. **Prompts** in the left nav shows the two prompt
versions side by side.

## Requirements

Like demos 4–5, this talks to Phoenix's REST API, which has no offline
fallback -- Phoenix must be running (`make apply`). Models come from
`ollama list`; see the README for the `ollama pull` commands.

## Talking point

> "It looks fine" isn't an eval. Same model, same questions, two prompts --
> and Phoenix tells you one is 24/24 and the other is 9/24, and exactly
> which answers failed and why. Change the prompt, rerun, compare.
