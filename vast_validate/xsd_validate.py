"""XSD schema resolution and validation helpers."""

from __future__ import annotations

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
from .validator_types import ValidationError, ValidationResult, VastValidationException


def extract_vast_version(xml_tree: etree._ElementTree) -> str | None:
    root = xml_tree.getroot()
    if root is None:
        return None
    version = root.attrib.get("version")
    return version.strip() if version else None


def build_error_list(log: Iterable[etree._LogEntry]) -> list[ValidationError]:
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


def resolve_schema_path(
    xml_tree: etree._ElementTree,
    xml_path: Path,
    schema_path: Path | None,
    schema_dir: Path | None,
) -> tuple[Path, str | None, str | None]:
    version = extract_vast_version(xml_tree)

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

        if requested_parts[:2] == (4, 3):
            four_two = [c for c in candidates if c.version_parts[:2] == (4, 2)]
            if four_two:
                chosen = four_two[-1]
                return (
                    chosen.path,
                    version,
                    "VAST 4.3 has no dedicated XSD; using official VAST 4.2 schema.",
                )

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

        same_major = [c for c in candidates if c.version_parts and c.version_parts[0] == req_major]
        if same_major:
            chosen = same_major[-1]
            return (
                chosen.path,
                version,
                f"Exact schema {version} not found; using latest available v{req_major}.x schema {chosen.version_text}.",
            )

        chosen = candidates[-1]
        return (
            chosen.path,
            version,
            f"No schema for VAST major version {req_major}; using latest available schema {chosen.version_text}.",
        )

    chosen = candidates[-1]
    return chosen.path, version, f"No VAST version in XML; using latest schema {chosen.version_text}."


def validate_tree(
    xml_tree: etree._ElementTree,
    xml_path: Path,
    schema_path: Path | None,
    schema_dir: Path | None,
) -> ValidationResult:
    schema_file, version, resolution_note = resolve_schema_path(
        xml_tree=xml_tree,
        xml_path=xml_path,
        schema_path=schema_path,
        schema_dir=schema_dir,
    )

    if not schema_file.exists():
        raise VastValidationException(f"XSD file not found: '{schema_file}'")

    try:
        schema_doc = etree.parse(str(schema_file))
        xml_schema = etree.XMLSchema(schema_doc)
    except (etree.XMLSyntaxError, etree.XMLSchemaParseError, OSError) as exc:
        raise VastValidationException(f"Unable to parse XSD '{schema_file}': {exc}") from exc

    is_valid = xml_schema.validate(xml_tree)
    errors = build_error_list(xml_schema.error_log)

    return ValidationResult(
        is_valid=is_valid,
        vast_version=version,
        schema_path=schema_file,
        schema_resolution_note=resolution_note,
        errors=errors,
    )
