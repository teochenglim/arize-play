"""
The evaluator types this demo uses:

- code_evaluator          deterministic check on tool args / state (no LLM call)
- binary_evaluator        pass/fail on ONE named failure mode
- harness_judge           rubric score with full trace visibility (all tool
                          calls, not just the final answer) -- for when a
                          fixed rubric on the final answer alone is too rigid

Every evaluator writes its result onto the *current span* as attributes, so
it shows up next to the run in the Phoenix UI, and returns a plain dict so
run_all.py can also print it as a table.
"""
import json

from common.llm import call_llm


def _attach(span, name: str, score, label: str, explanation: str):
    span.set_attribute(f"eval.{name}.score", score)
    span.set_attribute(f"eval.{name}.label", label)
    span.set_attribute(f"eval.{name}.explanation", explanation)
    return {"evaluator": name, "score": score, "label": label, "explanation": explanation}


def code_evaluator(span, name: str, passed: bool, explanation: str):
    """No model call. E.g. 'was the ticket created before status flipped to done'."""
    return _attach(span, name, 1 if passed else 0, "pass" if passed else "fail", explanation)


def binary_evaluator(span, name: str, passed: bool, explanation: str):
    """Same shape as code_evaluator but reserved for one named failure mode,
    e.g. 'hallucinated_account_data' or 'wrong_severity'."""
    return _attach(span, name, 1 if passed else 0, "pass" if passed else "fail", explanation)


def harness_judge(tracer, span, name: str, rubric: str, full_trace_text: str, canned_fallback: str = None):
    """Like a plain rubric judge, but sees every tool call and intermediate
    step, not just the final answer -- use when the correct path is
    under-specified (agent may take 3 tools or 7 and still be right) and
    there's no simple ground-truth value to check deterministically."""
    system = (
        "You are a strict evaluator with full visibility into an agent's run: "
        "every tool call, intermediate result, and the final answer. Judge the "
        "RUN as a whole against the RUBRIC, not just the last message. Reply "
        "with exactly two lines: 'score: <1-5>' then 'reason: <one sentence>'."
    )
    prompt = f"RUBRIC:\n{rubric}\n\nFULL RUN TRACE:\n{full_trace_text}"
    text, _usage = call_llm(
        tracer,
        f"harness_judge:{name}",
        system,
        prompt,
        canned_fallback=canned_fallback
        or "score: 5\nreason: Tool sequence was unconventional but reached a correct, verifiable state.",
        model_role="judge",
    )
    score, reason = _parse_judge(text)
    return _attach(span, name, score, "pass" if score >= 3 else "fail", reason)


def _parse_judge(text: str):
    # Models asked for "two lines of plain text" occasionally reply with
    # JSON instead (e.g. {"score": 5, "reason": "..."}) -- try that first.
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "score" in data:
            return int(data["score"]), str(data.get("reason", text.strip()))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    score, reason = 3, text.strip()
    for line in text.splitlines():
        line = line.strip().strip('"').lower()
        if line.startswith("score"):
            digits = "".join(c for c in line if c.isdigit())
            if digits:
                score = int(digits[0])
        if line.startswith("reason"):
            reason = line.split(":", 1)[-1].strip()
    return score, reason
