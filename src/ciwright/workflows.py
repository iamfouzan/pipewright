"""Loading and parsing workflow files — shared by the rules and the profiler.

ruamel's safe loader defaults to YAML 1.2, which (unlike PyYAML's 1.1) keeps
the workflow key ``on:`` as the string "on" instead of the boolean True.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ciwright.models import ProjectInfo

_yaml = YAML(typ="safe")

# A loaded workflow: its path, its parsed dict, and its raw text. The raw text
# lets some checks use a simple, robust substring search instead of a tree walk.
LoadedWorkflow = tuple[Path, dict, str]


def load_workflows(info: ProjectInfo) -> list[LoadedWorkflow]:
    loaded: list[LoadedWorkflow] = []
    for wf in info.workflows:
        try:
            text = wf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            data = _yaml.load(text) or {}
        except YAMLError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        loaded.append((wf, data, text))
    return loaded


def triggers(data: dict) -> dict:
    """Return the ``on:`` block as a dict, however it was written."""
    raw = data.get("on", data.get(True))  # tolerate a PyYAML-style True key
    return raw if isinstance(raw, dict) else {}


def jobs_of(data: dict) -> list[dict]:
    """Return the job definitions in a workflow as a list of dicts."""
    j = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(j, dict):
        return []
    return [v for v in j.values() if isinstance(v, dict)]
