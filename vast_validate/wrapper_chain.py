"""Follow and validate VAST wrapper chains."""

from __future__ import annotations

from urllib.request import Request, urlopen

from lxml import etree

from .best_practices import PracticeIssue, check_vast_best_practices
from .macros import find_unknown_macros, normalize_vast_macros
from .validator_types import ChainLevel, ValidationError, ValidationResult
from .xsd_validate import extract_vast_version, validate_tree


def _download_vast(url: str, timeout_seconds: int = 10) -> bytes:
    request = Request(url, headers={"User-Agent": "vast-validate/0.2"})
    with urlopen(request, timeout=timeout_seconds) as resp:
        return resp.read()


def _detect_ad_type(root: etree._Element) -> str:
    if root.xpath(".//*[local-name()='InLine']"):
        return "inline"
    if root.xpath(".//*[local-name()='Wrapper']"):
        return "wrapper"
    return "unknown"


def _find_vast_ad_tag_uri(root: etree._Element) -> str | None:
    nodes = root.xpath("//*[local-name()='VASTAdTagURI']")
    if not nodes:
        return None
    text = (nodes[0].text or "").strip()
    return text or None


def _validate_level_bytes(
    xml_bytes: bytes,
    *,
    source_label: str,
    schema_dir,
    schema_path,
    normalize_macros: bool,
) -> tuple[ValidationResult, list[str]]:
    validation_bytes = xml_bytes
    if normalize_macros:
        validation_bytes, _ = normalize_vast_macros(xml_bytes)

    parser = etree.XMLParser(remove_blank_text=False, recover=False)
    xml_tree = etree.ElementTree(etree.fromstring(validation_bytes, parser))

    from pathlib import Path

    result = validate_tree(
        xml_tree=xml_tree,
        xml_path=Path(source_label),
        schema_path=Path(schema_path).resolve() if schema_path else None,
        schema_dir=Path(schema_dir).resolve() if schema_dir else None,
    )
    return result, find_unknown_macros(xml_bytes)


def validate_wrapper_chain(
    xml_bytes: bytes,
    *,
    source: str = "input",
    schema_dir=None,
    schema_path=None,
    normalize_macros: bool = True,
    max_depth: int = 5,
    fetch_timeout_seconds: int = 10,
) -> list[ChainLevel]:
    """
    Validate VAST at each wrapper level and optionally fetch downstream tags.

    Level 0 is always the input document. When a wrapper is found, the chain
    continues until an InLine ad, an error, or max_depth is reached.
    """
    levels: list[ChainLevel] = []
    current_bytes = xml_bytes
    current_source = source
    depth = 0

    while True:
        try:
            root = etree.fromstring(current_bytes)
        except etree.XMLSyntaxError as exc:
            levels.append(
                ChainLevel(
                    level=depth,
                    source=current_source,
                    ad_type="unknown",
                    vast_version=None,
                    schema_result=ValidationResult(
                        is_valid=False,
                        vast_version=None,
                        schema_path=None,
                        errors=[
                            ValidationError(
                                line=0,
                                column=0,
                                message=f"Malformed VAST XML: {exc}",
                            )
                        ],
                    ),
                )
            )
            break

        ad_type = _detect_ad_type(root)
        version = extract_vast_version(etree.ElementTree(root))
        tag_uri = _find_vast_ad_tag_uri(root) if ad_type == "wrapper" else None

        schema_result, unknown_macros = _validate_level_bytes(
            current_bytes,
            source_label=current_source,
            schema_dir=schema_dir,
            schema_path=schema_path,
            normalize_macros=normalize_macros,
        )

        practices = check_vast_best_practices(
            current_bytes,
            level=depth,
            is_final_inline=ad_type == "inline",
            wrapper_depth=depth,
            max_wrapper_depth=max_depth,
        )

        levels.append(
            ChainLevel(
                level=depth,
                source=current_source,
                ad_type=ad_type,
                vast_version=version,
                vast_ad_tag_uri=tag_uri,
                schema_result=schema_result,
                best_practices=practices,
                unknown_macros=unknown_macros,
            )
        )

        if ad_type != "wrapper" or not tag_uri or depth >= max_depth:
            if ad_type == "wrapper" and tag_uri and depth >= max_depth:
                levels[-1].best_practices.append(
                    PracticeIssue(
                        severity="error",
                        code="WRAPPER_DEPTH_EXCEEDED",
                        message=f"Stopped at wrapper depth limit ({max_depth}); downstream VAST not fetched.",
                        level=depth,
                    )
                )
            break

        try:
            current_bytes = _download_vast(tag_uri, timeout_seconds=fetch_timeout_seconds)
        except OSError as exc:
            levels.append(
                ChainLevel(
                    level=depth + 1,
                    source=tag_uri,
                    ad_type="unknown",
                    vast_version=None,
                    schema_result=ValidationResult(
                        is_valid=False,
                        vast_version=None,
                        schema_path=None,
                        errors=[
                            ValidationError(
                                line=0,
                                column=0,
                                message=f"Failed to fetch wrapper VASTAdTagURI: {exc}",
                            )
                        ],
                    ),
                    best_practices=[
                        PracticeIssue(
                            severity="error",
                            code="WRAPPER_FETCH_FAILED",
                            message=f"Could not fetch VASTAdTagURI: {exc}",
                            level=depth + 1,
                        )
                    ],
                )
            )
            break

        current_source = tag_uri
        depth += 1

    return levels
