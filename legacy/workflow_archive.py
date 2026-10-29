"""Resolve preserved legacy workflow files for OFFLINE historical regression checks.

Provider provenance remains the original .github/workflows path. This helper
changes only filesystem fixture lookup; it grants no live workflow authority.
"""
from pathlib import Path


def legacy_workflow_path(path):
    path = Path(path)
    parts = path.parts
    for index in range(len(parts) - 1):
        if parts[index:index + 2] == (".github", "workflows"):
            archive = Path(*parts[:index], "legacy", "workflows", *parts[index + 2:])
            if archive.exists():
                return archive
            return path
    return path
