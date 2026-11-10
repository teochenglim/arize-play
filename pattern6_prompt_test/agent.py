"""
PATTERN 6 -- Use Arize Phoenix to EVALUATE A PROMPT. Simplest possible example.

A company-policy Q&A bot. We ask it 8 questions: 5 can be answered from the
policy text, 3 cannot (a good bot must admit "I don't know" instead of making
something up). We try two prompts and grade EVERY answer three ways:

  Correctness   did it give the right answer (or admit it doesn't know)?
  Groundedness  did it stick to the policy text, with nothing invented?
  Relevance     did it answer just the question, with no padding or extra tips?

The grader is a second, fast LLM (the "judge") that returns pass/fail for each.
Phoenix pieces: DATASET (the questions), PROMPTS (both saved as versions),
EXPERIMENTS (one per prompt) -- open the link at the end to browse every row.
Demo 7 reuses all of this and swaps the MODEL instead of the prompt.
"""
import contextlib
import io
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phoenix.client as pc
from phoenix.client.types import PromptVersion

from common.config import load_config
from common.tracing import init_tracing, new_session_id, tag_session
from common.llm import call_llm
from common.evaluators import judge_answer
from common.console import bold, cyan, dim, green, header, red, section

DATASET_NAME = "policy-qa"
PROMPT_NAME = "policy-qa-system-prompt"
METRICS = [("correctness", "Correct"), ("groundedness", "Grounded"), ("relevance", "Relevant")]

CONTEXT = (
    "ACME leave policy: full-time staff get 14 days of annual leave per year. "
    "Unused leave can be carried over, up to 5 days, into the next year. "
    "Sick leave is separate: 10 days per year with a medical certificate for "
    "absences longer than 2 days. Remote work is allowed up to 3 days a week."
)
NOT_STATED = "Not stated in the policy -- the bot should say it doesn't know."

# (question, reference answer). The last three are NOT answerable from CONTEXT;
# two earlier ones need a little reasoning, which separates stronger models from weaker.
QA = [
    ("How many days of annual leave do full-time staff get?", "14 days per year."),
    ("How many unused leave days can I carry over?", "Up to 5 days."),
    ("How many days a week can I work remotely?", "Up to 3 days a week."),
    ("I carried over 3 unused days. How many annual leave days can I use this year in total?", "17 days (14 + 3 carried over)."),
    ("I'm out sick for exactly 2 days. Do I need a medical certificate?", "No -- only for absences longer than 2 days."),
    ("How big is the annual bonus?", NOT_STATED),
    ("How many weeks of parental leave do I get?", NOT_STATED),
    ("Does the company offer a dental plan?", NOT_STATED),
]

# Prompt 1 is a realistic first draft: friendly and "helpful" -- which invites
# padding and guessing. Prompt 2 is the fix.
PROMPT_1 = "You are a friendly HR assistant. Answer the employee's question helpfully and completely, adding any useful tips."
PROMPT_2 = (
    "Answer using ONLY the CONTEXT. Be brief: one or two sentences. If the "
    "context does not contain the answer, reply exactly: I don't know."
)


def one_line(text: str, width: int = 100) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def run_variant(client, dataset, tracer, system_prompt, variant, session_id, model_role="agent"):
    """Runs one Phoenix experiment (quietly) and returns
    {question: {"answer": str, "results": {metric: {score,label,explanation}}}}."""
    rows = {q: {"answer": "", "results": {}} for q, _ in QA}
    judged = {}  # one judge call per answer, shared by the three evaluators

    def task(input: dict) -> dict:
        with tracer.start_as_current_span(f"qa:{variant}") as span:
            tag_session(span, session_id, "demo-user")
            span.set_attribute("input.value", input["question"])
            answer, _ = call_llm(
                tracer, f"llm:{variant}", system_prompt,
                f"CONTEXT:\n{input['context']}\n\nQUESTION:\n{input['question']}",
                canned_fallback="14 days.", model_role=model_role,
            )
            span.set_attribute("output.value", answer)
        rows[input["question"]]["answer"] = answer
        return {"answer": answer}

    def grade(input, output, expected):
        key = (input["question"], output["answer"])
        if key not in judged:
            judged[key] = judge_answer(tracer, input["question"], input["context"], expected["reference"], output["answer"])
        return judged[key]

    def make_eval(metric):
        def evaluator(input, output, expected):
            try:
                result = grade(input, output, expected)[metric]
            except Exception as exc:  # surface instead of silently dropping the score
                result = {"score": 0, "label": "fail", "explanation": f"grader error: {type(exc).__name__}: {exc}"[:160]}
            rows[input["question"]]["results"][metric] = result
            return result
        return evaluator

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        client.experiments.run_experiment(
            dataset=dataset, task=task, evaluators={m: make_eval(m) for m, _ in METRICS},
            experiment_name=variant, print_summary=False,
        )
    return rows


def build_dataset(client):
    return client.datasets.create_dataset(
        name=DATASET_NAME,
        inputs=[{"context": CONTEXT, "question": q} for q, _ in QA],
        outputs=[{"reference": r} for _, r in QA],
        dataset_description="Company-policy questions with reference answers (the last three are unanswerable).",
    )


def _marks(results) -> str:
    out = []
    for metric, label in METRICS:
        ok = results.get(metric, {}).get("label") == "pass"
        out.append((green("✔ ") if ok else red("✘ ")) + label)
    return "   ".join(out)


def show_comparison(runs):
    """runs = [(name, rows), ...] (two or more). Question-by-question view,
    then a scoreboard. Shared with demo 7."""
    names = [n for n, _ in runs]
    w = max(16, max(len(n) for n in names) + 1)
    section("What each one actually answered")
    for n, (question, reference) in enumerate(QA, 1):
        print(f"\n  {bold(f'Q{n}')} {question}")
        print(f"      {dim('right answer: ' + reference)}")
        for name, rows in runs:
            row = rows[question]
            print(f"      {bold(name.ljust(w))} says: {one_line(row['answer'])}")
            print(f"      {'':<{w + 1}}{_marks(row['results'])}")
            reason = next((r['explanation'] for r in row['results'].values() if r['label'] == 'fail'), "")
            if reason:
                print(f"      {'':<{w + 1}}{dim('judge: ' + reason)}")

    header("SCOREBOARD -- answers passed out of %d" % len(QA))
    col = max(16, w)
    print(f"  {'':<14}" + "".join(f"{n:<{col}}" for n in names))
    totals = [0] * len(runs)
    for metric, label in METRICS:
        cells = []
        for k, (_, rows) in enumerate(runs):
            c = sum(1 for r in rows.values() if r["results"][metric]["label"] == "pass")
            totals[k] += c
            cells.append(f"{c}/{len(QA)}  ({c / len(QA):.2f})")
        print(f"  {label:<14}" + "".join(f"{c:<{col}}" for c in cells))
    n = len(QA) * len(METRICS)
    print(f"  {bold('Overall'.ljust(14))}" + "".join(f"{f'{t}/{n}  ({t / n:.2f})':<{col}}" for t in totals))
    best = max(totals)
    winners = [nm for nm, t in zip(names, totals) if t == best]
    print("\n  " + (bold(f"Winner: {winners[0]}") if len(winners) == 1 else bold("Tie: " + ", ".join(winners))))


if __name__ == "__main__":
    tracer = init_tracing("pattern6-prompt-eval")
    cfg = load_config()
    client = pc.Client(base_url=cfg["phoenix"]["ui_url"])
    session_id = new_session_id()

    header("PATTERN 6 -- Which prompt is better? Let Phoenix grade them.")
    print("Scenario: an HR chatbot answers questions about this policy:\n")
    print(f"  {dim(CONTEXT)}\n")
    print(f"We ask {len(QA)} questions. {len(QA) - 3} are answerable from the policy; 3 are NOT, so a good bot")
    print("must say \"I don't know\" instead of inventing something.")
    print(f"Same model ({cfg['ollama']['agent_model'].removeprefix('ollama/')}) both times -- only the prompt changes. A judge model "
          f"({cfg['ollama']['judge_model'].removeprefix('ollama/')}) grades every answer:")
    print(f"  {bold('Correct')}   right answer, or an honest \"I don't know\"")
    print(f"  {bold('Grounded')}  only facts from the policy, nothing invented")
    print(f"  {bold('Relevant')}  answers the question, no padding or extra tips")

    section("Step 1 -- save the questions to Phoenix as a dataset")
    dataset = build_dataset(client)
    print(f"  dataset {bold(DATASET_NAME)} ({dataset.example_count} questions)")

    section("Step 2 -- save the two prompts to Phoenix as versions of one prompt")
    for prompt, tag in [(PROMPT_1, "prompt-1-friendly"), (PROMPT_2, "prompt-2-grounded")]:
        v = client.prompts.create(
            name=PROMPT_NAME,
            version=PromptVersion(
                [{"role": "system", "content": prompt}, {"role": "user", "content": "CONTEXT:\n{{context}}\n\nQUESTION:\n{{question}}"}],
                model_name="agent", model_provider="OLLAMA"),
            prompt_description=tag,
        )
        client.prompts.tags.create(prompt_version_id=v.id, name=tag)
    print(f"  {bold('Prompt 1')} (first draft): {dim(repr(PROMPT_1))}")
    print(f"  {bold('Prompt 2')} (the fix):     {dim(repr(PROMPT_2))}")

    section("Step 3 -- ask the bot every question with each prompt, and grade the answers")
    print("  Prompt 1 ...", end=" ", flush=True)
    rows1 = run_variant(client, dataset, tracer, PROMPT_1, "pattern6-prompt-1", session_id)
    print("done.  Prompt 2 ...", end=" ", flush=True)
    rows2 = run_variant(client, dataset, tracer, PROMPT_2, "pattern6-prompt-2", session_id)
    print("done.")

    show_comparison([("Prompt 1", rows1), ("Prompt 2", rows2)])
    print(f"\n{bold('Browse every row + judge notes in Phoenix:')}")
    print(f"  {cyan(client.experiments.get_dataset_experiments_url(dataset.id))}")
