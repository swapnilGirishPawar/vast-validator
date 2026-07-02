"""Core VAST XML validation logic using lxml."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from .best_practices import check_vast_best_practices
from .macros import MacroSubstitution, find_unknown_macros, normalize_vast_macros
from .openrtb_checks import check_openrtb_bid
from .validator_types import ValidationResult, VastValidationException
from .wrapper_chain import validate_wrapper_chain
from .xsd_validate import validate_tree


def _parse_xml_bytes(xml_bytes: bytes) -> etree._ElementTree:
    parser = etree.XMLParser(remove_blank_text=False, recover=False)
    try:
        return etree.ElementTree(etree.fromstring(xml_bytes, parser))
    except etree.XMLSyntaxError as exc:
        raise VastValidationException(f"Unable to parse XML: {exc}") from exc


def validate_vast_bytes(
    xml_bytes: bytes,
    *,
    source_label: str | Path = "input",
    schema_path: str | Path | None = None,
    schema_dir: str | Path | None = None,
    normalize_macros: bool = True,
    check_best_practices: bool = True,
    openrtb_payload: dict | None = None,
    follow_wrapper_chain: bool = False,
    max_wrapper_depth: int = 5,
) -> ValidationResult:
    """Validate VAST XML bytes with optional macro normalization and extra checks."""
    source_path = Path(source_label)
    resolved_schema_path = Path(schema_path).resolve() if schema_path else None
    resolved_schema_dir = Path(schema_dir).resolve() if schema_dir else None

    macro_substitutions: list[MacroSubstitution] = []
    validation_bytes = xml_bytes
    if normalize_macros:
        validation_bytes, macro_substitutions = normalize_vast_macros(xml_bytes)

    xml_tree = _parse_xml_bytes(validation_bytes)
    result = validate_tree(
        xml_tree=xml_tree,
        xml_path=source_path,
        schema_path=resolved_schema_path,
        schema_dir=resolved_schema_dir,
    )
    result.macro_substitutions = macro_substitutions
    result.unknown_macros = find_unknown_macros(xml_bytes)

    if check_best_practices:
        result.best_practices = check_vast_best_practices(xml_bytes, level=0)

    if openrtb_payload is not None:
        result.openrtb_issues = check_openrtb_bid(openrtb_payload)

    if follow_wrapper_chain:
        result.chain = validate_wrapper_chain(
            xml_bytes,
            source=str(source_path),
            schema_dir=resolved_schema_dir,
            schema_path=resolved_schema_path,
            normalize_macros=normalize_macros,
            max_depth=max_wrapper_depth,
        )

    return result


def validate_vast(
    xml_path: str | Path,
    schema_path: str | Path | None = None,
    schema_dir: str | Path | None = None,
    *,
    normalize_macros: bool = True,
    check_best_practices: bool = True,
    openrtb_payload: dict | None = None,
    follow_wrapper_chain: bool = False,
    max_wrapper_depth: int = 5,
) -> ValidationResult:
    """
    Validate a VAST XML file using lxml XMLSchema.

    Parameters:
    - xml_path: path to VAST XML.
    - schema_path: explicit XSD path. If omitted, auto-detect using VAST version.
    - schema_dir: directory containing versioned schemas (vast_4.2.xsd, etc.).
    - normalize_macros: replace VAST URL macros before XSD validation.
    - check_best_practices: run semantic checks beyond XSD.
    - openrtb_payload: optional OpenRTB JSON dict for bid-level checks.
    - follow_wrapper_chain: fetch and validate downstream wrapper VAST documents.
    - max_wrapper_depth: maximum wrapper hops when following the chain.
    """
    xml_path = Path(xml_path).resolve()

    if not xml_path.exists():
        raise VastValidationException(f"VAST file not found: '{xml_path}'")

    xml_bytes = xml_path.read_bytes()
    return validate_vast_bytes(
        xml_bytes,
        source_label=xml_path,
        schema_path=schema_path,
        schema_dir=schema_dir,
        normalize_macros=normalize_macros,
        check_best_practices=check_best_practices,
        openrtb_payload=openrtb_payload,
        follow_wrapper_chain=follow_wrapper_chain,
        max_wrapper_depth=max_wrapper_depth,
    )


def overall_is_valid(result: ValidationResult) -> bool:
    """True when XSD, chain, and error-severity best-practice checks all pass."""
    if not result.is_valid:
        return False

    for issue in result.best_practices:
        if issue.severity == "error":
            return False

    for issue in result.openrtb_issues:
        if issue.severity == "error":
            return False

    for level in result.chain:
        if level.schema_result and not level.schema_result.is_valid:
            return False
        for issue in level.best_practices:
            if issue.severity == "error":
                return False

    return True
