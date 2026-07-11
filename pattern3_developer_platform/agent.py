"""
PATTERN 3 -- Developer platform agent (infra/platform team, builds for other engineers)
Use case here: an AI SRE that triages log lines and opens an incident for
anything critical -- the article's own example shape ("ingest logs and
telemetry at scale... for triage and anomaly detection").

The article's advice for this pattern isn't "pick the smartest model" -- it's
"run the improvement loop from day one": trace the run, evaluate the
failure, change the harness, rerun. This script plays out that loop once,
on purpose, so you can show it live:

  run 1: harness has NO example of the "OOM-kill" failure signature
         -> agent misses it -> binary eval fails, failure mode named
  (change the harness: add one example to the system prompt)
  run 2: same logs, harness now recognises the signature -> eval passes

That's the whole loop. In production you'd do this from real production
failures, not a canned example, but the mechanics are identical.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.tracing import init_tracing
from common.llm import call_llm
from common.evaluators import binary_evaluator, harness_judge

LOGS_PATH = Path(__file__).resolve().parent / "logs.json"

incident_system = []


def load_logs():
    return json.loads(LOGS_PATH.read_text())


def create_incident(summary: str, severity: str):
    incident = {"summary": summary, "severity": severity}
    incident_system.append(incident)
    return incident


SYSTEM_V1 = (
    "You are an AI SRE. Read the LOG BATCH. If you see a critical failure, "
    "call out its severity and summary in one line prefixed 'INCIDENT:'. "
    "Otherwise reply 'no incident'."
)

# The harness change: one concrete example of the failure signature the
# agent was missing. This is the "change the harness" step -- not a bigger
# model, not more logs, just the missing context.
SYSTEM_V2 = SYSTEM_V1 + (
    "\n\nKnown critical signature: 'out-of-memory' or 'exit code 137' in an "
    "ERROR line means the container was OOM-killed -- always treat this as "
    "severity=critical and raise an incident, even if retries are ongoing."
)


def run_triage(tracer, run_label: str, system_prompt: str):
    log_text = "\n".join(load_logs())
    with tracer.start_as_current_span(f"sre_triage:{run_label}") as span:
        span.set_attribute("input.value", log_text)

        analysis, usage = call_llm(
            tracer,
            f"triage_analysis:{run_label}",
            system_prompt,
            log_text,
            canned_fallback=(
                "no incident"
                if run_label == "run1_before_harness_fix"
                else "INCIDENT: severity=critical, summary=worker-2 container OOM-killed on job 4471"
            ),
        )
        span.set_attribute("output.value", analysis)

        raised_incident = "INCIDENT:" in analysis.upper()
        if raised_incident:
            with tracer.start_as_current_span("tool:create_incident") as tool_span:
                incident = create_incident(analysis, "critical")
                tool_span.set_attribute("output.value", str(incident))

        # Step 2 of the loop: evaluate the failure. Binary, one named
        # failure mode -- per the article, prefer this over an uncalibrated
        # 1-100 scale.
        binary_result = binary_evaluator(
            span,
            "missed_critical_incident",
            passed=raised_incident,
            explanation="OOM-kill signature present in logs; incident " +
            ("was raised" if raised_incident else "was NOT raised"),
        )

        # Also show the fourth evaluator type on the same run: a judge with
        # full trace visibility, not just the final line.
        full_trace_text = f"SYSTEM:\n{system_prompt}\n\nLOGS:\n{log_text}\n\nAGENT OUTPUT:\n{analysis}"
        harness_result = harness_judge(
            tracer,
            span,
            "triage_quality",
            rubric="5 = correctly identifies the true root cause and severity; 1 = misses or misclassifies it.",
            full_trace_text=full_trace_text,
            canned_fallback=(
                "score: 1\nreason: OOM-kill signature in the ERROR line was ignored, no incident raised."
                if not raised_incident
                else "score: 5\nreason: Correctly identified the OOM-kill as a critical incident."
            ),
        )
        return analysis, usage, binary_result, harness_result


if __name__ == "__main__":
    tracer = init_tracing("pattern3-developer-platform")

    print("=== run 1: harness WITHOUT the OOM-kill example ===")
    analysis, usage, binary_result, harness_result = run_triage(tracer, "run1_before_harness_fix", SYSTEM_V1)
    print(f"agent output: {analysis}")
    print(f"eval[missed_critical_incident]: {binary_result['label']} ({binary_result['explanation']})")
    print(f"eval[triage_quality] (harness-as-judge): {harness_result['score']}/5 ({harness_result['explanation']})")

    print("\n--- change the harness: add the OOM-kill signature to the system prompt ---\n")

    print("=== run 2: harness WITH the fix, same logs ===")
    analysis, usage, binary_result, harness_result = run_triage(tracer, "run2_after_harness_fix", SYSTEM_V2)
    print(f"agent output: {analysis}")
    print(f"eval[missed_critical_incident]: {binary_result['label']} ({binary_result['explanation']})")
    print(f"eval[triage_quality] (harness-as-judge): {harness_result['score']}/5 ({harness_result['explanation']})")

    print(f"\nincidents raised this session: {len(incident_system)}")
