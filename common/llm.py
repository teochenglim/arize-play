"""
Thin LLM wrapper used by all three patterns.

Every call goes through a LiteLLM proxy (which fronts Ollama) via its
OpenAI-compatible /chat/completions endpoint -- no direct Ollama or Anthropic
client in this file, so this module only needs to know one HTTP shape. Base
URL, model aliases, and the demo's synthetic per-token pricing all come from
config.yaml (see common/config.py), with LITELLM_BASE_URL as an env override
for k8s (where the Job points at the in-cluster service DNS name instead of
the config file's localhost default).

If the proxy isn't reachable at all (e.g. running the offline demo with
nothing else started), calls fall back to a canned response from
STUB_RESPONSES, so the whole demo still runs with $0 cost and no network.

Either way every call is wrapped in an OpenInference "LLM" span with the
attributes Arize/Phoenix expect (input, output, token counts), so the traces
you see in the UI look the same regardless of which mode you're in.
"""
import os
import sys
import time

import httpx
from openinference.semconv.trace import SpanAttributes, OpenInferenceSpanKindValues

from common.config import load_config

_config = load_config()

MODEL = os.environ.get("DEMO_MODEL", "stub")
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", _config["litellm"]["base_url"])
PRICE_PER_1M_INPUT = _config["pricing_usd_per_1m_tokens"]["input"]
PRICE_PER_1M_OUTPUT = _config["pricing_usd_per_1m_tokens"]["output"]

_warned_unreachable = False


def _stub_call(system: str, prompt: str, canned: str):
    time.sleep(0.05)  # pretend it took a moment
    input_tokens = max(1, len(system.split()) + len(prompt.split()))
    output_tokens = max(1, len(canned.split()))
    return canned, input_tokens, output_tokens


def _litellm_chat(model_role: str, messages: list):
    """POSTs one turn to LiteLLM, returns the raw assistant message dict
    plus token counts."""
    body = {"model": model_role, "messages": messages, "stream": False}
    response = httpx.post(
        f"{LITELLM_BASE_URL.rstrip('/')}/chat/completions",
        json=body,
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    message = payload["choices"][0]["message"]
    usage = payload.get("usage", {})
    return message, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def _finalize_span(span, model_name: str, text: str, in_tok: int, out_tok: int):
    cost = (in_tok / 1_000_000) * PRICE_PER_1M_INPUT + (
        out_tok / 1_000_000
    ) * PRICE_PER_1M_OUTPUT
    span.set_attribute(SpanAttributes.LLM_MODEL_NAME, model_name)
    span.set_attribute(SpanAttributes.OUTPUT_VALUE, text)
    span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_PROMPT, in_tok)
    span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_COMPLETION, out_tok)
    span.set_attribute(SpanAttributes.LLM_TOKEN_COUNT_TOTAL, in_tok + out_tok)
    span.set_attribute("llm.cost_usd", cost)
    return text, {"input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": cost}


def call_llm(
    tracer,
    span_name: str,
    system: str,
    prompt: str,
    canned_fallback: str,
    model_role: str = "agent",
):
    """Runs one LLM turn inside a traced span. Returns the text output."""
    global _warned_unreachable
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.LLM.value,
        )
        span.set_attribute(SpanAttributes.INPUT_VALUE, prompt)

        try:
            model_name = model_role
            message, in_tok, out_tok = _litellm_chat(
                model_role,
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            text = message.get("content") or ""
        except httpx.HTTPError:
            if not _warned_unreachable:
                print(
                    f"[llm] LiteLLM not reachable at {LITELLM_BASE_URL}, "
                    "falling back to stub responses",
                    file=sys.stderr,
                )
                _warned_unreachable = True
            model_name = MODEL
            text, in_tok, out_tok = _stub_call(system, prompt, canned_fallback)

        return _finalize_span(span, model_name, text, in_tok, out_tok)
