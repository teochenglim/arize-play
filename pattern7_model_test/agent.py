"""
PATTERN 7 -- Use Arize Phoenix to EVALUATE MODELS. Simplest possible example.

Mirror of demo 6: the prompt (Prompt 2) and the policy questions are fixed,
the MODEL changes. config.yaml lists the models under test (`compare_models`,
all pulled via Ollama); LiteLLM routes each one by its "ollama/<name>" id.
Same pass/fail grading as demo 6: Correct, Grounded, Relevant.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phoenix.client as pc

from common.config import load_config
from common.tracing import init_tracing, new_session_id
from common.console import bold, cyan, dim, header, section
from pattern6_prompt_test.agent import CONTEXT, DATASET_NAME, PROMPT_2, QA, build_dataset, run_variant, show_comparison

if __name__ == "__main__":
    tracer = init_tracing("pattern7-model-eval")
    cfg = load_config()
    client = pc.Client(base_url=cfg["phoenix"]["ui_url"])
    session_id = new_session_id()
    models = cfg["ollama"]["compare_models"]
    judge = cfg["ollama"]["judge_model"].removeprefix("ollama/")

    header("PATTERN 7 -- Which model is better? Let Phoenix grade them.")
    print("Scenario: the same HR chatbot and policy as demo 6:\n")
    print(f"  {dim(CONTEXT)}\n")
    print(f"Same {len(QA)} questions ({len(QA) - 3} answerable, 3 not), same prompt:")
    print(f"  {dim(repr(PROMPT_2))}")
    print(f"Only the MODEL changes: {', '.join(bold(m) for m in models)}.")
    print(f"A judge model ({judge}) grades every answer: Correct / Grounded / Relevant.")

    section("Step 1 -- the questions, saved to Phoenix as a dataset")
    dataset = build_dataset(client)
    print(f"  dataset {bold(DATASET_NAME)} ({dataset.example_count} questions)")

    section("Step 2 -- ask every question to each model, and grade the answers")
    runs = []
    for model in models:
        print(f"  {model} ...", end=" ", flush=True)
        rows = run_variant(client, dataset, tracer, PROMPT_2, f"pattern7-{model}", session_id, model_role=f"ollama/{model}")
        print("done.")
        runs.append((model, rows))

    show_comparison(runs)
    print(f"\n{bold('Browse every row + judge notes in Phoenix:')}")
    print(f"  {cyan(client.experiments.get_dataset_experiments_url(dataset.id))}")
