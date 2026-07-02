"""OpenRTB bid-level checks for video/VAST responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lxml import etree


@dataclass(slots=True)
class OpenRtbIssue:
    severity: str  # error | warning | info
    code: str
    message: str


def _first_bid(payload: dict[str, Any]) -> dict[str, Any] | None:
    bid_response = payload.get("raw_bid_response", payload)
    seatbid = bid_response.get("seatbid")
    if not isinstance(seatbid, list) or not seatbid:
        return None
    bids = seatbid[0].get("bid") if isinstance(seatbid[0], dict) else None
    if not isinstance(bids, list) or not bids:
        return None
    return bids[0] if isinstance(bids[0], dict) else None


def _vast_impression_urls(adm: str) -> list[str]:
    try:
        root = etree.fromstring(adm.encode("utf-8"))
    except etree.XMLSyntaxError:
        return []
    urls: list[str] = []
    for node in root.xpath("//*[local-name()='Impression']"):
        text = (node.text or "").strip()
        if text:
            urls.append(text)
    return urls


def check_openrtb_bid(
    payload: dict[str, Any],
    *,
    is_ctv: bool = False,
) -> list[OpenRtbIssue]:
    issues: list[OpenRtbIssue] = []
    bid = _first_bid(payload)
    if bid is None:
        return [
            OpenRtbIssue(
                severity="error",
                code="NO_BID",
                message="OpenRTB payload has no seatbid[0].bid[0].",
            )
        ]

    adm = bid.get("adm")
    if not isinstance(adm, str) or not adm.strip():
        issues.append(
            OpenRtbIssue(
                severity="error",
                code="MISSING_ADM",
                message="Video bid is missing adm VAST payload.",
            )
        )
    elif "<VAST" not in adm and "<vast" not in adm:
        issues.append(
            OpenRtbIssue(
                severity="warning",
                code="ADM_NOT_VAST",
                message="adm does not appear to contain a VAST document.",
            )
        )

    adomain = bid.get("adomain")
    if not adomain:
        issues.append(
            OpenRtbIssue(
                severity="warning",
                code="MISSING_ADOMAIN",
                message="Bid is missing adomain (advertiser domain).",
            )
        )

    width = bid.get("w")
    height = bid.get("h")
    if width == 0 and height == 0:
        issues.append(
            OpenRtbIssue(
                severity="warning" if not is_ctv else "info",
                code="ZERO_DIMENSIONS",
                message="Bid has w=0 and h=0; common for CTV wrappers but not ideal for reporting.",
            )
        )
    elif not width or not height:
        issues.append(
            OpenRtbIssue(
                severity="warning",
                code="MISSING_DIMENSIONS",
                message="Bid is missing explicit width/height.",
            )
        )

    if not bid.get("crid"):
        issues.append(
            OpenRtbIssue(
                severity="info",
                code="MISSING_CRID",
                message="Bid is missing crid (creative id).",
            )
        )

    burl = bid.get("burl")
    if isinstance(adm, str) and burl:
        impression_urls = _vast_impression_urls(adm)
        if burl not in impression_urls:
            issues.append(
                OpenRtbIssue(
                    severity="info",
                    code="BURL_NOT_IN_VAST_IMPRESSIONS",
                    message="burl is not duplicated as a VAST <Impression> in adm (may still be valid).",
                )
            )

    price = bid.get("price")
    if price is None:
        issues.append(
            OpenRtbIssue(
                severity="warning",
                code="MISSING_PRICE",
                message="Bid is missing price.",
            )
        )

    return issues
