"""
PATTERN 2 -- Internal enterprise agent (platform/ops team, org-scale)
Use case here: expense approval process automation -- one high-volume
workflow, per the article's "start with one high-volume workflow" advice
(enterprise search or process automation). No LLM call at all: this is a
rules-based workflow, and the article's own point is that this pattern's
risk isn't model quality, it's org friction and fragmented data systems.

The agent applies a fixed policy (travel/training under SGD 500 ->
APPROVE, else REJECT) and updates two simulated, separate enterprise
systems -- a ticketing system (audit trail) and an expense system (status)
-- standing in for real, fragmented APIs (ServiceNow, SAP, ...).

THE DELIBERATE BUG: for 'equipment' category requests, ticket creation
silently never happens -- as if that category routed to a system that
isn't properly wired, a realistic enterprise-integration gap. The expense
still gets marked COMPLETE regardless, so a plain decision log
(`REQ-1002 -> REJECT`) looks completely normal either way.

Arize catches this with a deterministic code_evaluator checking the
workflow-STATE invariant: an expense marked COMPLETE must have a ticket.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.tracing import init_tracing
from common.evaluators import code_evaluator

EXPENSES_PATH = Path(__file__).resolve().parent / "expenses.json"

# Simulated fragmented systems: a ticketing system and an expense system.
# In a real org these are different APIs (ServiceNow, SAP, ...); the point
# the article makes is your harness has to reach across all of them.
ticketing_system = {}
expense_system = {}


def load_expenses():
    return json.loads(EXPENSES_PATH.read_text())


EXPENSES = load_expenses()


def create_ticket(request_id: str, category: str) -> bool:
    """Simulates calling an external ticketing system. THE BUG: for
    'equipment' category requests, pretend the API call was never made
    (or silently failed) and return False -- every other category
    succeeds."""
    if category == "equipment":
        return False
    ticketing_system[request_id] = True
    return True


def finalize_expense(request_id: str, decision: str):
    """Simulates updating the expense system. Once called, this request's
    workflow is considered COMPLETE regardless of decision."""
    expense_system[request_id] = "COMPLETE"


def run_expense_request(tracer, expense: dict):
    request_id = expense["request_id"]
    category = expense["category"]
    amount = expense["amount_sgd"]

    with tracer.start_as_current_span(f"expense_workflow:{request_id}") as span:
        span.set_attribute("input.value", str(expense))

        decision = "APPROVE" if category in ("travel", "training") and amount < 500 else "REJECT"

        # Harness step 1: create the ticket (audit trail other teams rely on)
        with tracer.start_as_current_span("tool:create_ticket") as tool_span:
            ticket_created = create_ticket(request_id, category)
            tool_span.set_attribute("output.value", str(ticket_created))

        # Harness step 2: only now flip the expense status
        with tracer.start_as_current_span("tool:set_expense_status") as tool_span:
            finalize_expense(request_id, decision)
            status = expense_system[request_id]
            tool_span.set_attribute("output.value", status)

        span.set_attribute("output.value", decision)

        # trace-level CODE evaluator: pure workflow-state check, no LLM call
        constraint_ok = not (status == "COMPLETE" and not ticket_created)
        eval_result = code_evaluator(
            span,
            "ticket_created_before_status_complete",
            passed=constraint_ok,
            explanation=f"ticket_created={ticket_created}, status={status}",
        )
        result = {
            "request_id": request_id,
            "decision": decision,
            "ticket_created": ticket_created,
            "status": status,
            "category": category,
            "amount": amount,
        }
        return result, eval_result


if __name__ == "__main__":
    tracer = init_tracing("pattern2-internal-enterprise")
    for expense in EXPENSES:
        result, eval_result = run_expense_request(tracer, expense)
        print(f"\n{result['request_id']}: {result['category']} SGD {result['amount']} -> {result['decision']}")
        print(f"   eval[ticket_created_before_status_complete]: {eval_result['label']} ({eval_result['explanation']})")
