"""Loads config.yaml (repo root) once. common/llm.py env vars still win over
these values where noted -- this file just holds the local-dev defaults."""
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
_config = None


def load_config():
    global _config
    if _config is None:
        with open(_CONFIG_PATH) as f:
            _config = yaml.safe_load(f)
    return _config
