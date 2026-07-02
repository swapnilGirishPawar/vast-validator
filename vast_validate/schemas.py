"""Known VAST schema file naming and version helpers."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SCHEMA_DIR_NAME = "schemas"

# Common VAST versions used in production systems.
KNOWN_VAST_VERSIONS = ("2.0", "3.0", "4.0", "4.1", "4.2", "4.3")


def normalize_version(version: str) -> str:
    return version.strip()


def version_to_filename(version: str) -> str:
    """
    Convert VAST version into a schema filename convention.
    Example: 4.2 -> vast_4.2.xsd
    """
    normalized = normalize_version(version)
    return f"vast_{normalized}.xsd"


def default_schema_dir(project_root: Path) -> Path:
    return project_root / DEFAULT_SCHEMA_DIR_NAME
