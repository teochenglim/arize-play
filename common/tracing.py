"""
One place that wires every pattern into Phoenix (Arize's OSS tracing + eval tool).

No docker, no API key required to see traces. `launch_app()` starts a local
Phoenix server in-process; `register()` points OpenTelemetry at it. Open
http://localhost:6006 while any pattern script is running.

If PHOENIX_COLLECTOR_ENDPOINT is set (e.g. to Arize AX in the cloud), traces
go there instead -- same code, same spans, different destination.
"""
import os

# Phoenix ships a docs "agent assistant" that calls out to arize.com on
# startup. Not needed for a local demo, and it just adds startup noise
# (or fails loudly) on a locked-down network -- turn it off.
os.environ.setdefault("PHOENIX_DISABLE_AGENT_ASSISTANT", "TRUE")

from phoenix.otel import register

_session = None
_tracer_provider = None


def init_tracing(project_name: str):
    """Call once per pattern script. Returns a tracer for that project."""
    global _session, _tracer_provider

    if not os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"):
        # Local mode: spin up Phoenix's own server, no docker/account needed.
        from phoenix import launch_app

        if _session is None:
            _session = launch_app()
            print(f"Phoenix UI: {_session.url}")

    _tracer_provider = register(
        project_name=project_name,
        endpoint=os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"),
        auto_instrument=False,
        verbose=False,
    )
    return _tracer_provider.get_tracer(project_name)
