"""
Runs all three patterns back to back and prints one consolidated table --
the "Arize values" for the demo: which level each eval attaches to, which
evaluator type it uses, and the score/label it produced.

Open http://localhost:30606 before running this to watch traces land live.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pattern1_customer_facing.agent import run_session
from pattern2_internal_enterprise.agent import run_expense_request, EXPENSES
from pattern3_developer_platform.agent import run_triage, SYSTEM_V1, SYSTEM_V2
from common.tracing import init_tracing

rows = []

# --- Pattern 1: customer-facing ---
# Same one-question test case run twice, per demo-01.md: once through the
# deliberately flawed retriever, once through the exact-match fix -- see
# run_session() in pattern1_customer_facing/agent.py.
tracer1 = init_tracing("pattern1-customer-facing")
for run_label, exact_match in [("run1_buggy_retriever", False), ("run2_exact_match_fix", True)]:
    retrieved, answer, usage, identity_result, arbiter_result, judge_result = run_session(tracer1, run_label, exact_match)
    rows.append(["1 customer-facing", "trace", "binary_evaluator", f"identity_lock ({run_label})", identity_result["label"], identity_result["score"]])
    rows.append(["1 customer-facing", "trace", "code_evaluator", f"ground_truth_arbiter ({run_label})", arbiter_result["label"], arbiter_result["score"]])
    rows.append(["1 customer-facing", "trace", "harness_judge", f"no_invented_deductions ({run_label})", judge_result["label"], judge_result["score"]])

# --- Pattern 2: internal enterprise ---
tracer2 = init_tracing("pattern2-internal-enterprise")
for expense in EXPENSES:
    result, eval_result = run_expense_request(tracer2, expense)
    rows.append(["2 internal enterprise", "trace", "code_evaluator", f"ticket_created_before_status_complete ({result['request_id']})", eval_result["label"], eval_result["score"]])

# --- Pattern 3: developer platform ---
tracer3 = init_tracing("pattern3-developer-platform")
for label, system in [("run1_before_harness_fix", SYSTEM_V1), ("run2_after_harness_fix", SYSTEM_V2)]:
    analysis, usage, binary_result, harness_result = run_triage(tracer3, label, system)
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
