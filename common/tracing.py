"""
One place that wires every pattern into Phoenix (Arize's OSS tracing + eval tool),
which here runs as a k8s Deployment (see k8s/12-phoenix-deployment.yaml), reached
over its NodePort at config.yaml's phoenix.collector_endpoint -- no in-process
Phoenix server, no port-forward. PHOENIX_COLLECTOR_ENDPOINT env var overrides
that default (e.g. to point at Arize AX in the cloud instead).
"""
import os

# Phoenix ships a docs "agent assistant" that calls out to arize.com on
# startup. Not needed for a local demo, and it just adds startup noise
# (or fails loudly) on a locked-down network -- turn it off.
os.environ.setdefault("PHOENIX_DISABLE_AGENT_ASSISTANT", "TRUE")

from phoenix.otel import register

from common.config import load_config

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
    )
    return _tracer_provider.get_tracer(project_name)
