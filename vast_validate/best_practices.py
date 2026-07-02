"""Semantic VAST best-practice checks beyond XSD validation."""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

REQUIRED_LINEAR_EVENTS = frozenset(
    {"start", "firstQuartile", "midpoint", "thirdQuartile", "complete"}
)
RECOMMENDED_LINEAR_EVENTS = REQUIRED_LINEAR_EVENTS | frozenset({"creativeView"})


@dataclass(slots=True)
class PracticeIssue:
    severity: str  # error | warning | info
    code: str
    message: str
    level: int | None = None


def _local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def _find_ad_types(root: etree._Element) -> list[str]:
    types: list[str] = []
    for ad in root.xpath("//*[local-name()='Ad']"):
        if ad.xpath(".//*[local-name()='InLine']"):
            types.append("inline")
        elif ad.xpath(".//*[local-name()='Wrapper']"):
            types.append("wrapper")
    return types


def _linear_tracking_events(linear: etree._Element) -> set[str]:
    events: set[str] = set()
    for tracking in linear.xpath(".//*[local-name()='Tracking']"):
        event_name = tracking.get("event")
        if event_name:
            events.add(event_name)
    return events


def check_vast_best_practices(
    xml_bytes: bytes,
    *,
    level: int = 0,
    is_final_inline: bool = False,
    wrapper_depth: int = 0,
    max_wrapper_depth: int = 5,
) -> list[PracticeIssue]:
    issues: list[PracticeIssue] = []
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        return [
            PracticeIssue(
                severity="error",
                code="XML_MALFORMED",
                message=f"Malformed VAST XML: {exc}",
                level=level,
            )
        ]

    version = (root.get("version") or "").strip()
    if not version:
        issues.append(
            PracticeIssue(
                severity="error",
                code="MISSING_VAST_VERSION",
                message="Root <VAST> element is missing required version attribute.",
                level=level,
            )
        )

    ads = root.xpath("//*[local-name()='Ad']")
    if not ads:
        issues.append(
            PracticeIssue(
                severity="error",
                code="NO_ADS",
                message="VAST response contains no <Ad> elements.",
                level=level,
            )
        )

    ad_types = _find_ad_types(root)
    if not ad_types:
        issues.append(
            PracticeIssue(
                severity="error",
                code="NO_INLINE_OR_WRAPPER",
                message="Each <Ad> must contain either <InLine> or <Wrapper>.",
                level=level,
            )
        )

    impressions = root.xpath("//*[local-name()='Impression']")
    if not impressions:
        issues.append(
            PracticeIssue(
                severity="error",
                code="NO_IMPRESSION",
                message="At least one <Impression> URL is required.",
                level=level,
            )
        )

    wrappers = root.xpath("//*[local-name()='Wrapper']")
    for wrapper in wrappers:
        tag_uri = wrapper.xpath(".//*[local-name()='VASTAdTagURI']")
        if not tag_uri or not (tag_uri[0].text or "").strip():
            issues.append(
                PracticeIssue(
                    severity="error",
                    code="WRAPPER_MISSING_TAG_URI",
                    message="Wrapper ad is missing <VASTAdTagURI>.",
                    level=level,
                )
            )

    if wrapper_depth > max_wrapper_depth:
        issues.append(
            PracticeIssue(
                severity="error",
                code="WRAPPER_DEPTH_EXCEEDED",
                message=(
                    f"Wrapper chain depth {wrapper_depth} exceeds limit of {max_wrapper_depth}."
                ),
                level=level,
            )
        )

    inlines = root.xpath("//*[local-name()='InLine']")
    for inline in inlines:
        media_files = inline.xpath(".//*[local-name()='MediaFile']")
        if not media_files:
            issues.append(
                PracticeIssue(
                    severity="error",
                    code="INLINE_MISSING_MEDIAFILE",
                    message="InLine ad must include at least one <MediaFile>.",
                    level=level,
                )
            )
        else:
            for media in media_files:
                if not (media.text or "").strip() and not media.get("apiFramework"):
                    issues.append(
                        PracticeIssue(
                            severity="warning",
                            code="MEDIAFILE_EMPTY_URL",
                            message="MediaFile has no URL content.",
                            level=level,
                        )
                    )
                if not media.get("type"):
                    issues.append(
                        PracticeIssue(
                            severity="warning",
                            code="MEDIAFILE_MISSING_MIME",
                            message="MediaFile is missing type (MIME) attribute.",
                            level=level,
                        )
                    )

        for linear in inline.xpath(".//*[local-name()='Linear']"):
            events = _linear_tracking_events(linear)
            missing = REQUIRED_LINEAR_EVENTS - events
            if missing:
                issues.append(
                    PracticeIssue(
                        severity="warning",
                        code="MISSING_QUARTILE_TRACKING",
                        message=(
                            "Linear creative missing recommended tracking events: "
                            f"{', '.join(sorted(missing))}."
                        ),
                        level=level,
                    )
                )

    if is_final_inline and "inline" not in ad_types:
        issues.append(
            PracticeIssue(
                severity="error",
                code="CHAIN_NO_FINAL_INLINE",
                message="Wrapper chain did not resolve to a final InLine ad with media.",
                level=level,
            )
        )

    if wrappers and not inlines and not is_final_inline:
        issues.append(
            PracticeIssue(
                severity="info",
                code="WRAPPER_ONLY",
                message="Response is wrapper-only; downstream VAST must be validated separately.",
                level=level,
            )
        )

    return issues
