# Demo 7: Which model is better?

**"Try Before You Switch"** · 🔥 Model-Swap Roulette -- swapping in a
smaller or cheaper model on a hunch, without measuring what you lose.

**File:** `pattern7_model_test/agent.py` · **Who builds this:** anyone
deciding whether a different (cheaper, faster, newer) model is good enough ·
**Run it:** `make apply` (if Phoenix isn't already up), then `make demo-07`
(about 1 minute)

**OWASP (2025):** LLM09:2025 Misinformation

## The one-sentence version

Demo 6 holds the model fixed and changes the prompt. This demo is the
mirror image: **same prompt, same questions, different models** -- graded
the same way (Correct / Grounded / Relevant), so "should we switch?" gets a
number.

## The scenario

The same HR chatbot and leave policy as demo 6, with its strict prompt
(Prompt 2: *use only the context, be brief, say "I don't know" if it isn't
there*). The same **8 questions**: 5 answerable (two need a little
reasoning), 3 deliberately unanswerable.

Three local Ollama models run through it:

| Model | Why it's in the test |
|---|---|
| `bonsai-2` | The baseline. Accurate, terse, follows the format. |
| `lfm3` | A different family. Fast, but tends to be chatty. |
| `qwen3:0.6b` | The "can we downsize?" candidate -- tiny and cheap. |

The list lives in `config.yaml` under `compare_models`. Add or swap any
model from `ollama list` and rerun; no other change needed.

## What the code does

1. **Saves the questions** as a Phoenix **Dataset** (shared with demo 6).
2. **Runs every model over every question** as its own Phoenix
   **Experiment**. LiteLLM routes each one by its `ollama/<name>` id.
3. **Grades each answer** with the same judge as demo 6: Correct, Grounded
   and Relevant, pass/fail.
4. **Prints** each question with every model's answer and ✔/✘ marks, then a
   scoreboard.

## The result

Real run:

```
                bonsai-2:latest lfm3:latest     qwen3:0.6b
  Correct       8/8  (1.00)     8/8  (1.00)     5/8  (0.62)
  Grounded      8/8  (1.00)     7/8  (0.88)     6/8  (0.75)
  Relevant      7/8  (0.88)     7/8  (0.88)     6/8  (0.75)
  Overall       23/24  (0.96)   22/24  (0.92)   17/24  (0.71)

  Winner: bonsai-2:latest
```

`bonsai-2` and `lfm3` are close; the tiny `qwen3:0.6b` drops from 8/8 to
5/8 on Correctness -- for example it answers the carry-over arithmetic
question with 19 days instead of 17. So the answer to "can we downsize to
the 0.6B model?" is **not for this task**, and you know *which* questions
it breaks on rather than guessing.

The full console output is in [outputs-demo-07.txt](outputs-demo-07.txt).

## Honest caveats

- **Close scores are noise.** `bonsai-2` vs `lfm3` (23 vs 22 out of 24) is
  one answer. Rerunning can flip it. Trust big gaps, not single points.
- **`bonsai-2` is also the judge**, so it may grade itself a little kindly,
  and the judge is occasionally too strict or too lenient. Set `judge_model`
  in `config.yaml` to a different model to remove the self-grading bias.
- **8 questions is a demo, not a benchmark.**

## Seeing it in the Phoenix UI

The closing link opens the dataset's Experiments tab: one experiment per
model, scores per question side by side, judge notes on click -- the view
you'd show someone when proposing the swap.

## Requirements

Phoenix must be running (`make apply`) -- no offline fallback. Each model
in `compare_models` must be pulled in Ollama; see the README.

## Talking point

> Switching models on a hunch is a gamble. Same prompt, same questions,
> three models: the small one fails a third of them and Phoenix shows you
> which. Run it before you ship the cheaper model, not after.
