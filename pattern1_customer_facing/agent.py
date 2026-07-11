"""
PATTERN 1 -- Customer-facing agent (product team, real users)
Use case here: an in-app HR assistant, à la Factorial/Indeed from the article --
users bring a question, the product brings their account-scoped data.

This script plays out demo-01.md's specific first-production-risk story: an
"incomplete pre-launch eval suite" scenario where the RETRIEVER, not the
LLM, is the bug. Arize doesn't care whether retrieval is a vector DB, a SQL
query, or -- as here -- a flat-file dict lookup; it only cares about the
trace: what record got retrieved, and what the LLM said based on it.

The retriever below matches the user's first name against employees.json,
but for any balance/deduction question its fallback logic ignores that
match and instead returns the highest-tenure employee company-wide (under
the flawed assumption "senior staff have the most complex payslips"). Ask
as Kavya Menon (0 leave days) and you get Wei Jian Lim's record (19 days)
back -- the agent then confidently tells "Kavya" she has 19 days left.

Three evaluators catch this without a human ever needing to notice:
- identity_lock          (binary_evaluator) does the retrieved record's
                          name match the name the user gave?
- ground_truth_arbiter   (code_evaluator)   re-reads employees.json fresh
                          and strictly compares the number the LLM claimed
                          against the real one for whichever employee the
                          answer is actually about
- no_invented_deductions (harness_judge)    does the answer list a
                          deduction that isn't in the retrieved record?
"""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.tracing import init_tracing
from common.llm import call_llm
from common.evaluators import binary_evaluator, code_evaluator, harness_judge

EMPLOYEES_PATH = Path(__file__).resolve().parent / "employees.json"
QUESTION = "Hi, I'm Kavya Menon. What is my leave balance and deductions?"

_NAME_RE = re.compile(r"(?:(?i:i'm|i am|my name is))\s+([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*)")


def _load_employees():
    return json.loads(EMPLOYEES_PATH.read_text())


def _extract_introduced_name(query: str):
    m = _NAME_RE.search(query)
    return m.group(1).strip() if m else None


def retrieve_employee(query: str, employees: list, exact_match: bool = False):
    """The retrieval step. `exact_match=True` is the fix from demo-01.md
    Phase 6: match the introduced name exactly. `exact_match=False` (the
    default, and the bug) matches only the first name, then -- for any
    balance/deduction question -- throws that match away and returns
    whichever employee has the most tenure company-wide."""
    name = _extract_introduced_name(query)
    if not name:
        return None

    if exact_match:
        for e in employees:
            if e["employee"].lower() == name.lower():
                return e
        return None

    first_name = name.split()[0].lower()
    candidates = [e for e in employees if e["employee"].split()[0].lower().startswith(first_name)]
    if re.search(r"\bbalance\b|\bdeduction", query, re.IGNORECASE):
        return max(employees, key=lambda e: e["tenure_years"])
    return candidates[0] if candidates else None


def _find_claimed_employee(text: str, employees: list):
    """Which employee is this answer actually about? Substring match on
    the full name first (most specific), then bare first name."""
    for e in employees:
        if e["employee"].lower() in text.lower():
            return e
    first_names = {e["employee"].split()[0].lower(): e for e in employees}
    for word in re.findall(r"[A-Za-z]+", text):
        if word.lower() in first_names:
            return first_names[word.lower()]
    return None


def identity_lock(span, query: str, retrieved: dict):
    """Evaluator 1: does the retrieved record's name match who's asking?
    A code-level check, no model call -- catches a wrong-record retrieval
    immediately, before even looking at what the LLM said about it."""
    claimed_name = _extract_introduced_name(query)
    retrieved_name = retrieved.get("employee") if retrieved else None
    matched = bool(claimed_name) and retrieved_name is not None and claimed_name.lower() == retrieved_name.lower()
    return binary_evaluator(
        span,
        "identity_lock",
        passed=matched,
        explanation=f"query identity={claimed_name!r} vs retrieved_employee_record.employee={retrieved_name!r}",
    )


def ground_truth_arbiter(span, answer: str):
    """Evaluator 2: re-reads employees.json fresh off disk (the "ground
    truth oracle") and strictly compares the number the LLM claimed
    against the real one for whichever employee the answer is actually
    about -- catches the hallucination even if the retrieval step were
    hidden from you entirely."""
    employees = _load_employees()
    claimed_employee = _find_claimed_employee(answer, employees)
    claimed_numbers = {int(n) for n in re.findall(r"(\d+)\s*day", answer, re.IGNORECASE)}

    if not claimed_employee:
        return code_evaluator(
            span, "ground_truth_arbiter", passed=False,
            explanation="could not identify which employee the answer is about",
        )

    real_balance = claimed_employee["leave_balance_days"]
    passed = real_balance in claimed_numbers
    return code_evaluator(
        span,
        "ground_truth_arbiter",
        passed=passed,
        explanation=(
            f"answer claims leave balance in {sorted(claimed_numbers)} for "
            f"{claimed_employee['employee']}; ground truth (fresh from "
            f"employees.json) = {real_balance}"
        ),
    )


def run_session(tracer, run_label: str, exact_match: bool):
    employees = _load_employees()
    with tracer.start_as_current_span(f"customer_facing_turn:{run_label}") as span:
        span.set_attribute("input.value", QUESTION)
        span.set_attribute("user_query", QUESTION)

        retrieved = retrieve_employee(QUESTION, employees, exact_match=exact_match)
        span.set_attribute("retrieved_employee_record", json.dumps(retrieved))

        introduced_name = _extract_introduced_name(QUESTION)
        system = (
            "You are an in-app HR assistant chatting with the user directly. "
            "Address them by the name they used to introduce themselves in "
            "the QUESTION. Answer using ONLY the numeric values in the "
            "RETRIEVED EMPLOYEE RECORD -- do not invent numbers, and do not "
            "mention any deduction that isn't listed in that record."
        )
        prompt = f"QUESTION:\n{QUESTION}\n\nRETRIEVED EMPLOYEE RECORD:\n{retrieved}"
        canned_fallback = (
            f"{introduced_name}, you have {retrieved['leave_balance_days']} days of leave left. "
            f"Deductions on your last payslip: {', '.join(retrieved['last_payslip_deductions'])}."
            if retrieved else f"Sorry {introduced_name}, I couldn't find your record."
        )
        answer, usage = call_llm(
            tracer,
            f"answer_from_retrieved_record:{run_label}",
            system,
            prompt,
            canned_fallback=canned_fallback,
        )
        span.set_attribute("output.value", answer)
        span.set_attribute("llm_output", answer)

        identity_result = identity_lock(span, QUESTION, retrieved)
        arbiter_result = ground_truth_arbiter(span, answer)
        judge_result = harness_judge(
            tracer,
            span,
            "no_invented_deductions",
            rubric=(
                "5 = the ANSWER mentions no deduction item that isn't listed in "
                "RETRIEVED RECORD's last_payslip_deductions. 1 = the ANSWER "
                "invents a deduction item not present in RETRIEVED RECORD."
            ),
            full_trace_text=f"RETRIEVED RECORD:\n{retrieved}\n\nANSWER:\n{answer}",
            canned_fallback="score: 5\nreason: answer only restates deductions already present in the retrieved record.",
        )
        return retrieved, answer, usage, identity_result, arbiter_result, judge_result


if __name__ == "__main__":
    tracer = init_tracing("pattern1-customer-facing")

    print("=== run 1: retriever WITH the highest-tenure fallback bug ===")
    retrieved, answer, usage, identity_result, arbiter_result, judge_result = run_session(
        tracer, "run1_buggy_retriever", exact_match=False
    )
    print(f"retrieved record: {retrieved['employee']} (tenure={retrieved['tenure_years']}y)")
    print(f"agent answer: {answer}")
    print(f"eval[identity_lock]: {identity_result['label']} ({identity_result['explanation']})")
    print(f"eval[ground_truth_arbiter]: {arbiter_result['label']} ({arbiter_result['explanation']})")
    print(f"eval[no_invented_deductions]: {judge_result['score']}/5 ({judge_result['explanation']})")

    print("\n--- fix the retriever: exact full-name match instead of first-name-prefix + tenure fallback ---\n")

    print("=== run 2: retriever WITH the fix, same question ===")
    retrieved, answer, usage, identity_result, arbiter_result, judge_result = run_session(
        tracer, "run2_exact_match_fix", exact_match=True
    )
    print(f"retrieved record: {retrieved['employee']} (tenure={retrieved['tenure_years']}y)")
    print(f"agent answer: {answer}")
    print(f"eval[identity_lock]: {identity_result['label']} ({identity_result['explanation']})")
    print(f"eval[ground_truth_arbiter]: {arbiter_result['label']} ({arbiter_result['explanation']})")
    print(f"eval[no_invented_deductions]: {judge_result['score']}/5 ({judge_result['explanation']})")
