"""
Runs patterns 1-3 back to back and prints one consolidated table -- the
"Arize values" for the demo: which level each eval attaches to, which
evaluator type it uses, and the score/label it produced. Then attempts
patterns 4 and 5 (the Phoenix Datasets/Prompts/Experiments workflow) as
subprocesses, so their own rich console narrative prints as-is rather than
being squeezed into table rows it doesn't fit.

Patterns 1-3 degrade to offline stub responses if LiteLLM isn't reachable
(see common/llm.py), so this script always runs start to finish either way.
Patterns 4-5 have no such fallback -- they talk to Phoenix's REST API
directly -- so this script checks Phoenix's reachability first and skips
them with a clear message instead of crashing if it's down.

Open http://localhost:30606 before running this to watch traces land live.
"""
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx

from pattern1_customer_facing.agent import run_session
from pattern2_internal_enterprise.agent import run_expense_request, EXPENSES
from pattern3_developer_platform.agent import run_triage, SYSTEM_V1, SYSTEM_V2
from common.tracing import init_tracing, new_session_id
from common.config import load_config

rows = []

# --- Pattern 1: customer-facing ---
# Same one-question test case run twice, per demo-01.md: once through the
# deliberately flawed retriever, once through the exact-match fix -- see
# run_session() in pattern1_customer_facing/agent.py. Both runs share one
# session_id (same underlying conversation, before/after the fix).
tracer1 = init_tracing("pattern1-customer-facing")
session1 = new_session_id()
for run_label, exact_match in [("run1_buggy_retriever", False), ("run2_exact_match_fix", True)]:
    retrieved, answer, usage, identity_result, arbiter_result, judge_result, trace_id, timestamp, user_id = run_session(
        tracer1, run_label, exact_match, session1
    )
    rows.append(["1 customer-facing", "trace", "binary_evaluator", f"identity_lock ({run_label})", identity_result["label"], identity_result["score"]])
    rows.append(["1 customer-facing", "trace", "code_evaluator", f"ground_truth_arbiter ({run_label})", arbiter_result["label"], arbiter_result["score"]])
    rows.append(["1 customer-facing", "trace", "harness_judge", f"no_invented_deductions ({run_label})", judge_result["label"], judge_result["score"]])

# --- Pattern 2: internal enterprise ---
# One session_id for the whole batch of requests.
tracer2 = init_tracing("pattern2-internal-enterprise")
session2 = new_session_id()
for expense in EXPENSES:
    result, eval_result, trace_id, timestamp, user_id = run_expense_request(tracer2, expense, session2)
    rows.append(["2 internal enterprise", "trace", "code_evaluator", f"ticket_created_before_status_complete ({result['request_id']})", eval_result["label"], eval_result["score"]])

# --- Pattern 3: developer platform ---
# One session_id across both harness-fix iterations.
tracer3 = init_tracing("pattern3-developer-platform")
session3 = new_session_id()
for label, system in [("run1_before_harness_fix", SYSTEM_V1), ("run2_after_harness_fix", SYSTEM_V2)]:
    analysis, usage, binary_result, harness_result, trace_id, timestamp, user_id = run_triage(
        tracer3, label, system, session3
    )
    rows.append(["3 developer platform", "trace", "binary_evaluator", f"missed_critical_incident ({label})", binary_result["label"], binary_result["score"]])
    rows.append(["3 developer platform", "trace", "harness_judge", f"triage_quality ({label})", harness_result["label"], harness_result["score"]])

# --- print consolidated table ---
headers = ["Pattern", "Eval level", "Evaluator type", "Evaluator name", "Label", "Score"]
widths = [22, 10, 16, 40, 6, 5]
print("\n" + " | ".join(h.ljust(w) for h, w in zip(headers, widths)))
print("-" * (sum(widths) + 3 * (len(widths) - 1)))
for row in rows:
    print(" | ".join(str(c).ljust(w) for c, w in zip(row, widths)))

print("Open http://localhost:30606 to see these same runs as traces + span annotations.")

# --- Patterns 4 & 5: the improvement-loop workflow ---
phoenix_url = load_config()["phoenix"]["ui_url"]
try:
    httpx.get(phoenix_url, timeout=3).raise_for_status()
    phoenix_up = True
except httpx.HTTPError:
    phoenix_up = False

if phoenix_up:
    for script in ("pattern4_improvement_loop/agent.py", "pattern5_credit_card_redaction/agent.py"):
        print(f"\n{'=' * 78}")
        # subprocess.run() writes to the inherited stdout fd directly, but
        # this script's own print()s above are fully buffered (not
        # line-buffered) whenever stdout isn't a live tty -- piped through
        # another command, redirected to a file, or captured by tooling.
        # Without an explicit flush here, the table above would show up
        # AFTER pattern 4/5's output instead of before it.
        sys.stdout.flush()
        subprocess.run(["uv", "run", "python", script], check=False)
else:
    print(f"\n[patterns 4 & 5 skipped -- Phoenix not reachable at {phoenix_url}]")
    print("Run `make apply` first, then `make demo` again, to include them.")
