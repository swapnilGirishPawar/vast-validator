"""Known VAST schema file naming and version helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

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


class SchemaCandidate(NamedTuple):
    version_text: str
    version_parts: tuple[int, ...]
    path: Path


_VERSION_RE = re.compile(r"(\d+(?:\.\d+){1,2})")


def parse_version_text(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in normalize_version(version).split("."))


def extract_version_from_schema_name(path: Path) -> str | None:
    # Supports names like:
    # vast_4.2.xsd, VAST_3.0.xsd, vast4.0.xsd, vast_2.0.1.xsd
    match = _VERSION_RE.search(path.stem)
    if not match:
        return None
    return match.group(1)


def discover_schema_candidates(schema_dir: Path) -> list[SchemaCandidate]:
    candidates: list[SchemaCandidate] = []
    if not schema_dir.exists():
        return candidates

    for xsd_file in schema_dir.glob("*.xsd"):
        version_text = extract_version_from_schema_name(xsd_file)
        if not version_text:
            continue
        candidates.append(
            SchemaCandidate(
                version_text=version_text,
                version_parts=parse_version_text(version_text),
                path=xsd_file.resolve(),
            )
        )
    return sorted(candidates, key=lambda c: c.version_parts)
