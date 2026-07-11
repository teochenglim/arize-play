"""
PATTERN 2 -- Internal enterprise agent (platform/ops team, org-scale)
Use case here: expense approval process automation -- one high-volume
workflow, per the article's "start with one high-volume workflow" advice
(enterprise search or process automation).

First production risks per the article: org friction and fragmented data
systems, not model quality. So the eval that matters most here isn't "is the
prose nice" -- it's "did the workflow touch the right systems in the right
order." That's a CODE evaluator: deterministic, no model call, checked
against workflow STATE rather than a fixed sequence of tool calls (the agent
might check policy first or last and still be correct).

Constraint encoded: an approval ticket must exist in the ticketing system
BEFORE the request's status is allowed to flip to "complete".
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.tracing import init_tracing
from common.llm import call_llm
from common.evaluators import code_evaluator

POLICY = "Expenses under SGD 500 auto-approve if the category is 'travel' or 'training'."

# Simulated fragmented systems: a ticketing system and an expense system.
# In a real org these are different APIs (ServiceNow, SAP, ...); the point
# the article makes is your harness has to reach across all of them.
ticketing_system = {}
expense_system = {}


def create_ticket(request_id: str, decision: str):
    ticketing_system[request_id] = {"decision": decision}
    return ticketing_system[request_id]


def set_expense_status(request_id: str, status: str):
    expense_system[request_id] = {"status": status}
    return expense_system[request_id]


def run_expense_request(tracer, request_id: str, amount: float, category: str, description: str):
    system = (
        "You process expense requests against POLICY. Reply with exactly one "
        "word: APPROVE or REJECT."
    )
    prompt = f"POLICY:\n{POLICY}\n\nREQUEST:\namount=SGD {amount}, category={category}, note={description}"

    with tracer.start_as_current_span("expense_workflow") as span:
        span.set_attribute("input.value", prompt)

        decision_text, usage = call_llm(
            tracer,
            "policy_decision",
            system,
            prompt,
            canned_fallback="APPROVE" if amount < 500 and category in ("travel", "training") else "REJECT",
        )
        decision = "APPROVE" if "APPROVE" in decision_text.upper() else "REJECT"

        # Harness step 1: create the ticket (audit trail other teams rely on)
        with tracer.start_as_current_span("tool:create_ticket") as tool_span:
            ticket = create_ticket(request_id, decision)
            tool_span.set_attribute("output.value", str(ticket))

        # Harness step 2: only now flip the expense status
        with tracer.start_as_current_span("tool:set_expense_status") as tool_span:
            status = "complete" if decision == "APPROVE" else "rejected"
            expense = set_expense_status(request_id, status)
            tool_span.set_attribute("output.value", str(expense))

        span.set_attribute("output.value", decision)

        # trace-level CODE evaluator: pure workflow-state check, no LLM call
        ticket_exists = request_id in ticketing_system
        status_is_complete = expense_system.get(request_id, {}).get("status") == "complete"
        constraint_ok = (not status_is_complete) or ticket_exists
        eval_result = code_evaluator(
            span,
            "ticket_created_before_status_complete",
            passed=constraint_ok,
            explanation=(
                f"ticket_exists={ticket_exists}, status={expense_system.get(request_id, {}).get('status')}"
            ),
        )
        return decision, usage, eval_result


if __name__ == "__main__":
    tracer = init_tracing("pattern2-internal-enterprise")
    requests = [
        ("REQ-1001", 240.0, "travel", "Client visit taxi + flight"),
        ("REQ-1002", 1200.0, "equipment", "New laptop"),
    ]
    for request_id, amount, category, description in requests:
        decision, usage, eval_result = run_expense_request(tracer, request_id, amount, category, description)
        print(f"\n{request_id}: {category} SGD {amount} -> {decision}")
        print(f"   cost=${usage['cost_usd']:.5f}")
        print(f"   eval[ticket_created_before_status_complete]: {eval_result['label']} ({eval_result['explanation']})")
