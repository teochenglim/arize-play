"""
The four evaluator types Arize/Mastra call out, minus the ceremony:

- code_evaluator     deterministic check on tool args / state (no LLM call)
- binary_evaluator   pass/fail on ONE named failure mode
- llm_judge          rubric score on open-ended output, calibrated prompt
- harness_judge      like llm_judge, but sees the FULL trace (all tool calls,
                     not just the final answer) -- for when a fixed rubric
                     on the final answer alone is too rigid

Every evaluator writes its result onto the *current span* as attributes, so
it shows up next to the run in the Phoenix UI, and returns a plain dict so
eval_report.py can also print it as a table.
"""
from openinference.semconv.trace import SpanAttributes
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


def llm_judge(tracer, span, name: str, rubric: str, output_to_judge: str):
    """Rubric-scores the final answer only. Calibrate the rubric against a
    few human-labeled examples before trusting it in production."""
    system = (
        "You are a strict evaluator. Score the AGENT OUTPUT against the RUBRIC "
        "on a 1-5 scale. Reply with exactly two lines: 'score: <1-5>' then "
        "'reason: <one sentence>'."
    )
    prompt = f"RUBRIC:\n{rubric}\n\nAGENT OUTPUT:\n{output_to_judge}"
    text, _usage = call_llm(
        tracer,
        f"judge:{name}",
        system,
        prompt,
        canned_fallback="score: 4\nreason: Grounded in the retrieved context, minor phrasing issue.",
    )
    score, reason = _parse_judge(text)
    return _attach(span, name, score, "pass" if score >= 3 else "fail", reason)


def harness_judge(tracer, span, name: str, rubric: str, full_trace_text: str, canned_fallback: str = None):
    """Like llm_judge, but the judge sees every tool call and intermediate
    step, not just the final answer -- use when the correct path is
    under-specified (agent may take 3 tools or 7 and still be right)."""
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
    )
    score, reason = _parse_judge(text)
    return _attach(span, name, score, "pass" if score >= 3 else "fail", reason)


def _parse_judge(text: str):
    score, reason = 3, text.strip()
    for line in text.splitlines():
        line = line.strip().lower()
        if line.startswith("score"):
            digits = "".join(c for c in line if c.isdigit())
            if digits:
                score = int(digits[0])
        if line.startswith("reason"):
            reason = line.split(":", 1)[-1].strip()
    return score, reason
