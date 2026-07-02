"""Core VAST XML validation logic using lxml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from lxml import etree

from .schemas import (
    KNOWN_VAST_VERSIONS,
    default_schema_dir,
    discover_schema_candidates,
    parse_version_text,
    version_to_filename,
)


@dataclass(slots=True)
class ValidationError:
    line: int
    column: int
    message: str
    domain: str | None = None
    error_type: str | None = None


@dataclass(slots=True)
class ValidationResult:
    is_valid: bool
    vast_version: str | None
    schema_path: Path | None
    schema_resolution_note: str | None = None
    errors: list[ValidationError] = field(default_factory=list)


class VastValidationException(Exception):
    """Raised for validation setup and parsing errors."""


def _parse_xml(xml_path: Path) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False, recover=False)
    try:
        return etree.parse(str(xml_path), parser)
    except (etree.XMLSyntaxError, OSError) as exc:
        raise VastValidationException(f"Unable to parse XML file '{xml_path}': {exc}") from exc


def _extract_vast_version(xml_tree: etree._ElementTree) -> str | None:
    root = xml_tree.getroot()
    if root is None:
        return None
    # VAST root usually has version attribute, e.g. <VAST version="4.2">
    version = root.attrib.get("version")
    return version.strip() if version else None


def _build_error_list(log: Iterable[etree._LogEntry]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for item in log:
        errors.append(
            ValidationError(
                line=getattr(item, "line", 0) or 0,
                column=getattr(item, "column", 0) or 0,
                message=getattr(item, "message", "Unknown validation error"),
                domain=getattr(item, "domain_name", None),
                error_type=getattr(item, "type_name", None),
            )
        )
    return errors


def _resolve_schema_path(
    xml_tree: etree._ElementTree,
    xml_path: Path,
    schema_path: Path | None,
    schema_dir: Path | None,
) -> tuple[Path, str | None, str | None]:
    version = _extract_vast_version(xml_tree)

    if schema_path is not None:
        return schema_path, version, "Using explicitly provided --xsd schema."

    base_dir = schema_dir or default_schema_dir(xml_path.resolve().parent)
    candidates = discover_schema_candidates(base_dir)
    if not candidates:
        hints = ", ".join(version_to_filename(v) for v in KNOWN_VAST_VERSIONS)
        raise VastValidationException(
            "No XSD files found for automatic resolution. "
            f"Looked in '{base_dir}'. "
            f"Suggested filenames: {hints}. "
            "You can also pass --xsd explicitly."
        )

    if version:
        requested_parts = parse_version_text(version)
        exact = [c for c in candidates if c.version_parts == requested_parts]
        if exact:
            chosen = exact[-1]
            return chosen.path, version, f"Matched schema version {chosen.version_text} exactly."

        # Same major/minor match (e.g. request 2.0, available 2.0.1)
        req_major = requested_parts[0]
        req_minor = requested_parts[1] if len(requested_parts) > 1 else 0
        same_major_minor = [
            c
            for c in candidates
            if len(c.version_parts) >= 2
            and c.version_parts[0] == req_major
            and c.version_parts[1] == req_minor
        ]
        if same_major_minor:
            chosen = same_major_minor[-1]
            return (
                chosen.path,
                version,
                f"Exact schema {version} not found; using closest patch {chosen.version_text}.",
            )

        # Fallback inside same major (e.g. request 4.3, available 4.2)
        same_major = [c for c in candidates if c.version_parts and c.version_parts[0] == req_major]
        if same_major:
            chosen = same_major[-1]
            return (
                chosen.path,
                version,
                f"Exact schema {version} not found; using latest available v{req_major}.x schema {chosen.version_text}.",
            )

        # Last-resort fallback to latest schema overall.
        chosen = candidates[-1]
        return (
            chosen.path,
            version,
            f"No schema for VAST major version {req_major}; using latest available schema {chosen.version_text}.",
        )

    # No version in XML, choose latest available schema.
    chosen = candidates[-1]
    return chosen.path, version, f"No VAST version in XML; using latest schema {chosen.version_text}."


def validate_vast(
    xml_path: str | Path,
    schema_path: str | Path | None = None,
    schema_dir: str | Path | None = None,
) -> ValidationResult:
    """
    Validate a VAST XML file using lxml XMLSchema.

    Parameters:
    - xml_path: path to VAST XML.
    - schema_path: explicit XSD path. If omitted, auto-detect using VAST version.
    - schema_dir: directory containing versioned schemas (vast_4.2.xsd, etc.).
    """
    xml_path = Path(xml_path).resolve()
    resolved_schema_path = Path(schema_path).resolve() if schema_path else None
    resolved_schema_dir = Path(schema_dir).resolve() if schema_dir else None

    if not xml_path.exists():
        raise VastValidationException(f"VAST file not found: '{xml_path}'")

    xml_tree = _parse_xml(xml_path)
    schema_file, version, resolution_note = _resolve_schema_path(
        xml_tree=xml_tree,
        xml_path=xml_path,
        schema_path=resolved_schema_path,
        schema_dir=resolved_schema_dir,
    )

    if not schema_file.exists():
        raise VastValidationException(f"XSD file not found: '{schema_file}'")

    try:
        schema_doc = etree.parse(str(schema_file))
        xml_schema = etree.XMLSchema(schema_doc)
    except (etree.XMLSyntaxError, etree.XMLSchemaParseError, OSError) as exc:
        raise VastValidationException(f"Unable to parse XSD '{schema_file}': {exc}") from exc

    is_valid = xml_schema.validate(xml_tree)
    errors = _build_error_list(xml_schema.error_log)

    return ValidationResult(
        is_valid=is_valid,
        vast_version=version,
        schema_path=schema_file,
        schema_resolution_note=resolution_note,
        errors=errors,
    )
