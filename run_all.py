"""
Runs all three patterns back to back and prints one consolidated table --
the "Arize values" for the demo: which level each eval attaches to, which
evaluator type it uses, and the score/label it produced.

Open http://localhost:6006 before running this to watch traces land live.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from pattern1_customer_facing.agent import run_session
from pattern2_internal_enterprise.agent import run_expense_request, init_tracing as _unused
from pattern3_developer_platform.agent import run_triage, SYSTEM_V1, SYSTEM_V2
from common.tracing import init_tracing

rows = []

# --- Pattern 1: customer-facing ---
results, session_cost, budget_check = run_session([
    "What's my base salary and what got deducted from my last payslip?",
    "How many leave days do I have left?",
])
for r in results:
    rows.append(["1 customer-facing", "trace", "llm_judge", "grounded_in_account_context", r["label"], r["score"]])
rows.append(["1 customer-facing", "session", "code_evaluator", "session_cost_within_budget", budget_check["label"], budget_check["score"]])

# --- Pattern 2: internal enterprise ---
tracer2 = init_tracing("pattern2-internal-enterprise")
for request_id, amount, category, description in [
    ("REQ-1001", 240.0, "travel", "Client visit taxi + flight"),
    ("REQ-1002", 1200.0, "equipment", "New laptop"),
]:
    decision, usage, eval_result = run_expense_request(tracer2, request_id, amount, category, description)
    rows.append(["2 internal enterprise", "trace", "code_evaluator", "ticket_created_before_status_complete", eval_result["label"], eval_result["score"]])

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

print(f"\nPattern 1 session cost: ${session_cost:.5f}")
print("Open http://localhost:6006 to see these same runs as traces + span annotations.")
