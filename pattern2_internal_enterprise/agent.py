"""
PATTERN 2 -- Internal enterprise agent (platform/ops team, org-scale)
Use case here: expense approval process automation -- one high-volume
workflow, per the article's "start with one high-volume workflow" advice
(enterprise search or process automation). The article's own point for this
pattern is that the risk isn't model quality, it's org friction and
fragmented data systems -- so an LLM call *is* in the loop here (applying
the approval policy to each request), but it's a thin, low-stakes one; the
interesting failure is still in the harness, not the model.

The agent asks an LLM to apply a fixed policy (travel/training under SGD
500 -> APPROVE, else REJECT) and then updates two simulated, separate
enterprise systems -- a ticketing system (audit trail) and an expense
system (status) -- standing in for real, fragmented APIs (ServiceNow,
SAP, ...).

THE DELIBERATE BUG: for 'equipment' category requests, ticket creation
silently never happens -- as if that category routed to a system that
isn't properly wired, a realistic enterprise-integration gap. The expense
still gets marked COMPLETE regardless, so a plain decision log
(`REQ-1002 -> REJECT`) looks completely normal either way.

Arize catches this with a deterministic code_evaluator checking the
workflow-STATE invariant: an expense marked COMPLETE must have a ticket.

Every request also gets tagged with a shared session.id (this whole batch
run is one "session"), a per-employee user.id, a run.timestamp, and its own
trace.id -- see run_expense_request() -- so any single request can be
pulled back up in the Phoenix search bar later.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.tracing import init_tracing, new_session_id, print_search_hint, tag_session
from common.llm import call_llm
from common.evaluators import code_evaluator
from common.console import bold, dim, eval_line, green, header, red, section

EXPENSES_PATH = Path(__file__).resolve().parent / "expenses.json"

# Simulated fragmented systems: a ticketing system and an expense system.
# In a real org these are different APIs (ServiceNow, SAP, ...); the point
# the article makes is your harness has to reach across all of them.
ticketing_system = {}
expense_system = {}


def load_expenses():
    return json.loads(EXPENSES_PATH.read_text())


EXPENSES = load_expenses()

POLICY_SYSTEM = (
    "You are an expense-approval policy engine. Policy: approve a request "
    "only if its category is 'travel' or 'training' AND its amount_sgd is "
    "under 500. Otherwise reject. Reply with exactly one word: APPROVE or "
    "REJECT -- no punctuation, no explanation."
)


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


def run_expense_request(tracer, expense: dict, session_id: str):
    request_id = expense["request_id"]
    category = expense["category"]
    amount = expense["amount_sgd"]
    employee = expense["employee"]
    user_id = employee.lower().replace(" ", ".")

    with tracer.start_as_current_span(f"expense_workflow:{request_id}") as span:
        trace_id, timestamp = tag_session(span, session_id, user_id)
        span.set_attribute("input.value", str(expense))

        # The policy decision itself now goes through an LLM call (an
        # OpenInference LLM span, same as patterns 1 and 3) instead of being
        # a bare Python conditional -- the rule-based conditional survives
        # only as canned_fallback for when the LLM/LiteLLM backend is
        # unreachable, so the offline demo still reproduces this file's
        # documented, deterministic REQ-1001..1004 outcomes.
        rule_based_fallback = "APPROVE" if category in ("travel", "training") and amount < 500 else "REJECT"
        raw_decision, usage = call_llm(
            tracer,
            f"policy_decision:{request_id}",
            POLICY_SYSTEM,
            f"Request:\n{json.dumps(expense)}",
            canned_fallback=rule_based_fallback,
        )
        decision = "APPROVE" if "APPROVE" in raw_decision.upper() else "REJECT"
        span.set_attribute("decision.llm_raw_output", raw_decision)

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
        return result, eval_result, trace_id, timestamp, user_id


if __name__ == "__main__":
    tracer = init_tracing("pattern2-internal-enterprise")
    # One session_id for the whole batch -- these four requests are one
    # "finance ops" session in Phoenix's Sessions view, even though each
    # request is still its own trace.
    session_id = new_session_id()

    header("PATTERN 2 -- Internal enterprise agent (expense approval workflow)")
    print(f"{bold('Batch:')} {len(EXPENSES)} requests from expenses.json, one finance-ops session\n")

    rows = []
    for expense in EXPENSES:
        section(f"{expense['request_id']} -- {expense['employee']} ({expense['department']})")
        print(f"  {dim('category:')} {expense['category']}   {dim('amount:')} SGD {expense['amount_sgd']}   {dim('note:')} {expense['description']}")

        result, eval_result, trace_id, timestamp, user_id = run_expense_request(tracer, expense, session_id)

        decision_str = green(bold(result["decision"])) if result["decision"] == "APPROVE" else red(bold(result["decision"]))
        ticket_str = green("created") if result["ticket_created"] else red("NOT created")
        print(f"  {dim('decision:')} {decision_str}   {dim('ticket:')} {ticket_str}   {dim('status:')} {result['status']}")
        print()
        eval_line("ticket_created_before_status_complete", eval_result)
        print()
        print_search_hint(trace_id, session_id, user_id, timestamp)
        rows.append(result | {"eval_label": eval_result["label"]})

    header("SUMMARY -- all requests this batch")
    for r in rows:
        badge = green("PASS") if r["eval_label"] == "pass" else red("FAIL")
        print(f"  {r['request_id']:<10} {r['category']:<10} SGD {r['amount']:<6} {r['decision']:<8} ticket={str(r['ticket_created']):<5} {badge}")
