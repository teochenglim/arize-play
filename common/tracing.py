"""
One place that wires every pattern into Phoenix (Arize's OSS tracing + eval tool),
which here runs as a k8s Deployment (see k8s/12-phoenix-deployment.yaml), reached
over its NodePort at config.yaml's phoenix.collector_endpoint -- no in-process
Phoenix server, no port-forward. PHOENIX_COLLECTOR_ENDPOINT env var overrides
that default (e.g. to point at Arize AX in the cloud instead).
"""
import os
import uuid
from datetime import datetime, timezone

# Phoenix ships a docs "agent assistant" that calls out to arize.com on
# startup. Not needed for a local demo, and it just adds startup noise
# (or fails loudly) on a locked-down network -- turn it off.
os.environ.setdefault("PHOENIX_DISABLE_AGENT_ASSISTANT", "TRUE")

from openinference.semconv.trace import SpanAttributes
from phoenix.otel import register

from common.config import load_config
from common.console import cyan, dim

_config = load_config()
_tracer_provider = None
_printed_ui_url = False


def init_tracing(project_name: str):
    """Call once per pattern script. Returns a tracer for that project."""
    global _tracer_provider, _printed_ui_url

    endpoint = os.environ.get(
        "PHOENIX_COLLECTOR_ENDPOINT", _config["phoenix"]["collector_endpoint"]
    )
    if not _printed_ui_url:
        print(f"Phoenix UI: {_config['phoenix']['ui_url']}")
        _printed_ui_url = True

    _tracer_provider = register(
        project_name=project_name,
        endpoint=endpoint,
        # Phoenix's protocol auto-detection keys off the endpoint port being
        # exactly 4317; we reach it through a NodePort (30317) instead, which
        # made it silently default to http/protobuf against a grpc-only port
        # (every span export then failed with a "BadStatusLine" error). Say
        # grpc explicitly instead of relying on the port-number heuristic.
        protocol="grpc",
        auto_instrument=False,
        verbose=False,
        # run_all.py calls init_tracing() once per pattern in the same
        # process (one project per pattern), and every caller here always
        # uses the tracer object returned below, never OTel's ambient
        # global provider -- so there's nothing to lose by not contesting
        # the global slot, and it silences a harmless but noisy "Overriding
        # of current TracerProvider is not allowed" warning on the 2nd+ call.
        set_global_tracer_provider=False,
    )
    return _tracer_provider.get_tracer(project_name)


def new_session_id() -> str:
    """One id per logical conversation/batch (e.g. "the before/after-fix
    conversation with Kavya", "this expense batch run"). Pass the SAME id
    into tag_session() for every run that should group together in
    Phoenix's Sessions view -- each run stays its own trace, only the
    session.id attribute is shared across them."""
    return str(uuid.uuid4())


def tag_session(span, session_id: str, user_id: str):
    """Stamps the OpenInference `session.id` / `user.id` attributes onto
    this run's root span -- the two Phoenix's Sessions view and search bar
    key off of -- plus a `run.timestamp` and this run's own OTel `trace.id`,
    so the exact run can be found again in the Phoenix search bar by any of
    the four. Returns (trace_id, timestamp) for the caller to print."""
    timestamp = datetime.now(timezone.utc).isoformat()
    span.set_attribute(SpanAttributes.SESSION_ID, session_id)
    span.set_attribute(SpanAttributes.USER_ID, user_id)
    span.set_attribute("run.timestamp", timestamp)
    trace_id = format(span.get_span_context().trace_id, "032x")
    span.set_attribute("trace.id", trace_id)
    return trace_id, timestamp


def print_search_hint(trace_id: str, session_id: str, user_id: str, timestamp: str):
    """Prints the copy/paste block for the Phoenix search bar -- the same
    four attributes every run gets tagged with in tag_session()."""
    print(dim("  find this run in Phoenix (search bar, top of the Traces table):"))
    print(f"    {dim('trace.id')}      = {cyan(trace_id)}")
    print(f"    {dim('session.id')}    = {cyan(session_id)}")
    print(f"    {dim('user.id')}       = {cyan(user_id)}")
    print(f"    {dim('run.timestamp')} = {cyan(timestamp)}")
