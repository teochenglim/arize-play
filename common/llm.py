"""
Thin LLM wrapper used by all three patterns.

Runs two ways:
- ANTHROPIC_API_KEY set  -> real call to Claude (claude-haiku-4-5 by default)
- no key                 -> canned response from STUB_RESPONSES, so the whole
                            demo runs offline with $0 cost and no network

Either way every call is wrapped in an OpenInference "LLM" span with the
attributes Arize/Phoenix expect (input, output, token counts), so the traces
you see in the UI look the same regardless of which mode you're in.
"""
import os
import time
from openinference.semconv.trace import SpanAttributes, OpenInferenceSpanKindValues

MODEL = os.environ.get("DEMO_MODEL", "claude-haiku-4-5-20251001")

# Cost model just for the demo (USD per 1M tokens). Real numbers belong in
# your observability dashboard, pulled from the provider's actual pricing.
PRICE_PER_1M_INPUT = 1.00
PRICE_PER_1M_OUTPUT = 5.00

_client = None
if os.environ.get("ANTHROPIC_API_KEY"):
    import anthropic

    _client = anthropic.Anthropic()


def _stub_call(system: str, prompt: str, canned: str):
    time.sleep(0.05)  # pretend it took a moment
    input_tokens = max(1, len(system.split()) + len(prompt.split()))
    output_tokens = max(1, len(canned.split()))
    return canned, input_tokens, output_tokens


def call_llm(tracer, span_name: str, system: str, prompt: str, canned_fallback: str):
    """Runs one LLM turn inside a traced span. Returns the text output."""
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.LLM.value,
        )
        span.set_attribute(SpanAttributes.LLM_MODEL_NAME, MODEL)
        span.set_attribute(SpanAttributes.INPUT_VALUE, prompt)

        if _client is not None:
            resp = _client.messages.create(
                model=MODEL,
                max_tokens=400,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
            in_tok, out_tok = resp.usage.input_tokens, resp.usage.output_tokens
        else:
            text, in_tok, out_tok = _stub_call(system, prompt, canned_fallback)

        cost = (in_tok / 1_000_000) * PRICE_PER_1M_INPUT + (
            out_tok / 1_000_000
        ) * PRICE_PER_1M_OUTPUT

        span.set_attribute(SpanAttributes.OUTPUT_VALUE, text)
        span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_PROMPT, in_tok)
        span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_COMPLETION, out_tok)
        span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_TOTAL, in_tok + out_tok)
        span.set_attribute("llm.cost_usd", cost)
        return text, {"input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": cost}
