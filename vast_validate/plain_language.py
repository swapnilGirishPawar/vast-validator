"""Plain-language explanations for validation findings."""

from __future__ import annotations

import re

from .validator_types import ChainLevel, ValidationResult

# Best-practice and OpenRTB codes → short, non-technical explanations.
_CODE_EXPLANATIONS: dict[str, str] = {
    "NO_IMPRESSION": (
        "The ad is missing at least one <Impression> tracking URL. "
        "Impression URLs are required so the ad server can count when the ad was shown."
    ),
    "WRAPPER_ONLY": (
        "This response only points to another VAST URL (a wrapper). "
        "The actual video creative lives in that linked document and must be checked too."
    ),
    "WRAPPER_MISSING_TAG_URI": (
        "A wrapper ad is missing the <VASTAdTagURI> that tells the player where to fetch the next VAST document."
    ),
    "INLINE_MISSING_MEDIAFILE": (
        "The final inline ad has no <MediaFile>, so there is no video file for the player to load."
    ),
    "NO_ADS": "The VAST document contains no <Ad> elements, so there is nothing to serve.",
    "NO_INLINE_OR_WRAPPER": (
        "Each <Ad> must contain either an <InLine> block (the creative itself) "
        "or a <Wrapper> block (a link to another VAST)."
    ),
    "MISSING_VAST_VERSION": (
        "The root <VAST> element is missing its version attribute (for example version=\"3.0\")."
    ),
    "CHAIN_NO_FINAL_INLINE": (
        "Following the wrapper chain did not reach a final inline ad with actual video media."
    ),
    "WRAPPER_DEPTH_EXCEEDED": "The wrapper chain is too deep (too many redirects between VAST documents).",
    "MISSING_QUARTILE_TRACKING": (
        "The linear video creative is missing standard progress tracking events "
        "(start, quartiles, complete). Players may still work, but reporting will be incomplete."
    ),
    "MEDIAFILE_EMPTY_URL": "A <MediaFile> entry has no video URL.",
    "MEDIAFILE_MISSING_MIME": "A <MediaFile> entry is missing its type (MIME) attribute.",
    "XML_MALFORMED": "The XML is not well-formed and cannot be parsed.",
    "ZERO_DIMENSIONS": (
        "The OpenRTB bid lists width and height as 0. "
        "This is common for CTV wrapper bids but makes size-based reporting less useful."
    ),
    "MISSING_DIMENSIONS": "The OpenRTB bid does not include explicit width and height.",
    "MISSING_ADOMAIN": "The bid does not list an advertiser domain (adomain).",
    "MISSING_ADM": "The bid has no adm field containing the VAST XML.",
    "ADM_NOT_VAST": "The bid adm field does not look like a VAST document.",
    "NO_BID": "The OpenRTB response JSON does not contain a usable bid object.",
    "MISSING_PRICE": "The bid is missing a price value.",
    "MISSING_CRID": "The bid is missing a creative id (crid).",
    "BURL_NOT_IN_VAST_IMPRESSIONS": (
        "The bid's billing URL (burl) is not also listed as a VAST <Impression>. "
        "This may still be acceptable depending on your setup."
    ),
}


def _explain_xsd_error(message: str) -> str:
    """Turn a raw XSD message into a short plain-language explanation."""
    unexpected = re.search(
        r"Element '([^']+)': This element is not expected\. Expected is(?: one of)? \(([^)]+)\)",
        message,
    )
    if unexpected:
        found, expected = unexpected.group(1), unexpected.group(2)
        expected_clean = ", ".join(part.strip() for part in expected.split(","))
        return (
            f"The <{found}> element is in the wrong place or used incorrectly. "
            f"At this position the VAST schema expects: {expected_clean}."
        )

    missing_child = re.search(
        r"Element '([^']+)': Missing child element\(s\)\. Expected is(?: one of)? \(([^)]+)\)",
        message,
    )
    if missing_child:
        parent, expected = missing_child.group(1), missing_child.group(2)
        expected_clean = ", ".join(part.strip() for part in expected.split(","))
        return (
            f"The <{parent}> element is missing required child content. "
            f"It should include one of: {expected_clean}."
        )

    invalid_value = re.search(
        r"Element '([^']+)': '([^']*)' is not a valid value of the atomic type '([^']+)'",
        message,
    )
    if invalid_value:
        element, value, type_name = invalid_value.groups()
        shown = value if value else "(empty)"
        return (
            f"The <{element}> element has an invalid value ({shown!r}) "
            f"for the required {type_name} format."
        )

    if "not complete" in message.lower() or "missing" in message.lower():
        return f"The XML structure is incomplete: {message}"

    return message


def _explain_by_code(code: str, fallback_message: str) -> str:
    return _CODE_EXPLANATIONS.get(code, fallback_message)


def _chain_level_label(level: ChainLevel) -> str:
    if level.level == 0:
        return "the first VAST in the bid (wrapper)"
    if level.ad_type == "inline":
        return f"the final inline ad (wrapper level {level.level})"
    return f"wrapper level {level.level}"


def _collect_plain_items(result: ValidationResult) -> list[tuple[str, str]]:
    """Return (severity, explanation) pairs for the plain-language section."""
    items: list[tuple[str, str]] = []

    # When a wrapper chain was followed, chain levels carry per-hop context;
    # root XSD errors duplicate level 0 and are omitted here.
    if not result.chain and result.errors:
        for err in result.errors:
            items.append(("error", _explain_xsd_error(err.message)))

    for issue in result.best_practices:
        if issue.severity == "info":
            continue
        items.append((issue.severity, _explain_by_code(issue.code, issue.message)))

    for issue in result.openrtb_issues:
        if issue.severity == "info":
            continue
        items.append((issue.severity, _explain_by_code(issue.code, issue.message)))

    seen_xsd: set[str] = set()
    for level in result.chain:
        label = _chain_level_label(level)
        schema = level.schema_result
        if schema and schema.errors:
            for err in schema.errors:
                explanation = _explain_xsd_error(err.message)
                key = f"{level.level}:{explanation}"
                if key not in seen_xsd:
                    seen_xsd.add(key)
                    items.append(("error", f"In {label}: {explanation}"))

        for issue in level.best_practices:
            if issue.severity != "error":
                continue
            explanation = _explain_by_code(issue.code, issue.message)
            items.append(("error", f"In {label}: {explanation}"))

    for issue in result.best_practices:
        if issue.severity != "info":
            continue
        items.append(("info", _explain_by_code(issue.code, issue.message)))

    for issue in result.openrtb_issues:
        if issue.severity != "info":
            continue
        items.append(("info", _explain_by_code(issue.code, issue.message)))

    return items


def _dedupe_preserve_order(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for severity, text in items:
        if text in seen:
            continue
        seen.add(text)
        unique.append((severity, text))
    return unique


def build_plain_language_section(result: ValidationResult, *, passed: bool) -> list[str]:
    """Build lines for the PLAIN-LANGUAGE SUMMARY report section."""
    lines: list[str] = ["PLAIN-LANGUAGE SUMMARY", "-" * 80]

    if passed:
        lines.append(
            "This VAST response passed all checks. The XML structure matches the schema, "
            "and no blocking issues were found in the enabled best-practice or OpenRTB checks."
        )
        return lines

    lines.append(
        "This VAST response did not pass validation. Below is what went wrong in everyday terms:"
    )
    lines.append("")

    items = _dedupe_preserve_order(_collect_plain_items(result))
    if not items:
        lines.append(
            "Validation failed, but no detailed issue text was captured. "
            "See the technical sections above for raw error output."
        )
        return lines

    # Group by severity for readability
    errors = [text for sev, text in items if sev == "error"]
    warnings = [text for sev, text in items if sev == "warning"]
    infos = [text for sev, text in items if sev == "info"]

    if errors:
        lines.append("Problems that must be fixed:")
        for idx, text in enumerate(errors, start=1):
            lines.append(f"  {idx}. {text}")
        lines.append("")

    if warnings:
        lines.append("Warnings (worth reviewing, may still play in some players):")
        for idx, text in enumerate(warnings, start=1):
            lines.append(f"  {idx}. {text}")
        lines.append("")

    if infos:
        lines.append("Notes:")
        for idx, text in enumerate(infos, start=1):
            lines.append(f"  {idx}. {text}")

    if result.chain and any(
        level.schema_result and not level.schema_result.is_valid for level in result.chain
    ):
        lines.append(
            "Tip: When a wrapper chain is involved, fix issues starting at the first "
            "failing level - later levels may fail because of upstream problems."
        )

    return lines
