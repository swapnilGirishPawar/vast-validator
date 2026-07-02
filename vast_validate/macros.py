"""VAST macro handling for XSD validation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

# Common IAB VAST macros (VAST 2.x–4.x). XSD anyURI rejects bracketed placeholders.
KNOWN_VAST_MACROS = frozenset(
    {
        "ADCATEGORIES",
        "ADCOUNT",
        "ADPLAYHEAD",
        "ADSERVINGID",
        "ADTYPE",
        "APIFRAMEWORKS",
        "APPBUNDLE",
        "ASSETURI",
        "BLOCKEDADCATEGORIES",
        "CACHEBUSTING",
        "CLICKPOS",
        "CLICKTYPE",
        "CONTENTID",
        "CONTENTPLAYHEAD",
        "CONTENTURI",
        "DEVICEIP",
        "DEVICEUA",
        "DOMAIN",
        "ERRORCODE",
        "GDPR",
        "GDPR_CONSENT",
        "IFA",
        "IFA_TYPE",
        "INVENTORYSTATE",
        "LATLONG",
        "LIMITADTRACKING",
        "MEDIAMIME",
        "MEDIAPLAYHEAD",
        "OMIDPARTNER",
        "PAGEURL",
        "PLACEMENTTYPE",
        "PLAYERCAPABILITIES",
        "PLAYBACKMETHODS",
        "PODSEQUENCE",
        "REGULATIONS",
        "SERVERSIDE",
        "SERVERUA",
        "TRANSACTIONID",
        "UNIVERSALADID",
        "VASTVERSIONS",
        "VERIFICATIONVENDORS",
    }
)

MACRO_PATTERN = re.compile(r"\[([A-Z][A-Z0-9_]*)\]")

# Elements whose text or url-like attributes are validated as xs:anyURI in VAST XSDs.
URI_BEARING_ELEMENTS = frozenset(
    {
        "ClickThrough",
        "ClickTracking",
        "CustomClick",
        "Error",
        "HTMLResource",
        "IFrameResource",
        "IconClickThrough",
        "IconClickTracking",
        "IconViewTracking",
        "Impression",
        "NonLinearClickThrough",
        "NonLinearClickTracking",
        "StaticResource",
        "Tracking",
        "VASTAdTagURI",
    }
)

URI_BEARING_ATTRIBUTES = frozenset({"url"})


@dataclass(slots=True)
class MacroSubstitution:
    macro: str
    count: int


def _substitute_macros_in_text(text: str) -> tuple[str, list[MacroSubstitution]]:
    substitutions: dict[str, int] = {}

    def replacer(match: re.Match[str]) -> str:
        macro = match.group(1)
        substitutions[macro] = substitutions.get(macro, 0) + 1
        # RFC 3986-safe placeholder; keeps path-like structure for anyURI checks.
        return f"macro-{macro.lower()}"

    normalized = MACRO_PATTERN.sub(replacer, text)
    notes = [MacroSubstitution(macro=k, count=v) for k, v in sorted(substitutions.items())]
    return normalized, notes


def normalize_vast_macros(xml_bytes: bytes) -> tuple[bytes, list[MacroSubstitution]]:
    """
    Replace VAST URL macros with XSD-safe placeholders before schema validation.

    VAST requires macros like [ERRORCODE] in tracking URLs, but xs:anyURI rejects
    square brackets. This keeps semantic validation separate from structural XSD checks.
    """
    root = etree.fromstring(xml_bytes)
    all_notes: dict[str, int] = {}

    for element in root.iter():
        local_name = etree.QName(element).localname
        if local_name in URI_BEARING_ELEMENTS and element.text:
            normalized, notes = _substitute_macros_in_text(element.text)
            element.text = normalized
            for note in notes:
                all_notes[note.macro] = all_notes.get(note.macro, 0) + note.count

        for attr_name, attr_value in element.attrib.items():
            if attr_name in URI_BEARING_ATTRIBUTES and attr_value:
                normalized, notes = _substitute_macros_in_text(attr_value)
                element.set(attr_name, normalized)
                for note in notes:
                    all_notes[note.macro] = all_notes.get(note.macro, 0) + note.count

    merged = [MacroSubstitution(macro=k, count=v) for k, v in sorted(all_notes.items())]
    return etree.tostring(root, encoding="utf-8"), merged


def find_unknown_macros(xml_bytes: bytes) -> list[str]:
    """Return macro names in the payload that are not in the known IAB list."""
    text = xml_bytes.decode("utf-8", errors="replace")
    found = {match.group(1) for match in MACRO_PATTERN.finditer(text)}
    return sorted(found - KNOWN_VAST_MACROS)
