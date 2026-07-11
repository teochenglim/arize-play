"""
PATTERN 1 -- Customer-facing agent (product team, real users)
Use case here: an in-app HR assistant, à la Factorial/Indeed from the article --
users bring a question, the product brings their account-scoped data.

First production risks per the article: inference COST at scale, and an
ACCURACY eval suite that's incomplete pre-launch because you don't yet know
the full breadth of questions real users will ask.

What this script evaluates and at what level:
- trace  : is the answer grounded in the account data we gave it? (llm_judge)
- session: did this user's whole conversation stay under a cost budget? (code_evaluator)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.tracing import init_tracing
from common.llm import call_llm
from common.evaluators import llm_judge, code_evaluator

# Account-scoped context the platform brings -- this is the "context
# engineering, not model shopping" point from the article. A generic
# chatbot has no access to this; that's the whole value proposition.
ACCOUNT_CONTEXT = {
    "employee": "Priya Nair",
    "base_salary_sgd": 96000,
    "last_payslip_deductions": ["CPF employee 20%", "SDL 0.25%"],
    "leave_balance_days": 6,
}

SESSION_COST_BUDGET_USD = 0.05


def answer_question(tracer, question: str):
    system = (
        "You are an in-app HR assistant. Answer ONLY using the ACCOUNT CONTEXT "
        "provided. Do not invent numbers. If the context doesn't cover the "
        "question, say so."
    )
    prompt = f"ACCOUNT CONTEXT:\n{ACCOUNT_CONTEXT}\n\nQUESTION:\n{question}"
    with tracer.start_as_current_span("customer_facing_turn") as span:
        span.set_attribute("input.value", question)
        answer, usage = call_llm(
            tracer,
            "answer_from_account_context",
            system,
            prompt,
            canned_fallback=(
                "Your base salary is SGD 96,000/year. Last payslip deductions were "
                "CPF employee (20%) and SDL (0.25%). You have 6 leave days left."
            ),
        )
        span.set_attribute("output.value", answer)

        # trace-level eval: grounded in the account context we supplied
        judge_result = llm_judge(
            tracer,
            span,
            "grounded_in_account_context",
            rubric=(
                "5 = every number in the answer traces back to ACCOUNT CONTEXT. "
                "1 = the answer invents figures not present in ACCOUNT CONTEXT."
            ),
            output_to_judge=answer,
        )
        return answer, usage, judge_result


def run_session(questions):
    tracer = init_tracing("pattern1-customer-facing")
    session_cost = 0.0
    results = []
    with tracer.start_as_current_span("customer_session") as session_span:
        for q in questions:
            answer, usage, judge_result = answer_question(tracer, q)
            session_cost += usage["cost_usd"]
            results.append({"question": q, "answer": answer, **usage, **judge_result})

        # session-level eval: pure code, no model call -- did we blow the budget?
        budget_check = code_evaluator(
            session_span,
            "session_cost_within_budget",
            passed=session_cost <= SESSION_COST_BUDGET_USD,
            explanation=f"session cost ${session_cost:.5f} vs budget ${SESSION_COST_BUDGET_USD}",
        )
    return results, session_cost, budget_check


if __name__ == "__main__":
    questions = [
        "What's my base salary and what got deducted from my last payslip?",
        "How many leave days do I have left?",
    ]
    results, session_cost, budget_check = run_session(questions)
    for r in results:
        print(f"\nQ: {r['question']}\nA: {r['answer']}")
        print(f"   eval[grounded_in_account_context]: score={r['score']} label={r['label']} ({r['explanation']})")
        print(f"   tokens in/out={r['input_tokens']}/{r['output_tokens']} cost=${r['cost_usd']:.5f}")
    print(f"\nSESSION cost=${session_cost:.5f}  budget_eval={budget_check['label']} ({budget_check['explanation']})")
