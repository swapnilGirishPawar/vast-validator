"""Extract VAST XML from OpenRTB bid responses."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from lxml import etree


@dataclass(slots=True)
class ExtractedVast:
    impid: str | None
    bid_id: str | None
    vast_xml: str
    vast_version: str | None
    vast_ad_tag_uri: str | None


class OpenRtbExtractionError(Exception):
    """Raised when VAST cannot be extracted from an OpenRTB payload."""


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpenRtbExtractionError(f"Failed to read JSON file '{path}': {exc}") from exc


def _find_vast_ad_tag_uri(vast_xml: str) -> str | None:
    try:
        root = etree.fromstring(vast_xml.encode("utf-8"))
    except etree.XMLSyntaxError:
        return None

    # Use local-name to support optional namespaces.
    nodes = root.xpath("//*[local-name()='VASTAdTagURI']")
    if not nodes:
        return None
    text = (nodes[0].text or "").strip()
    return text or None


def _extract_vast_version(vast_xml: str) -> str | None:
    try:
        root = etree.fromstring(vast_xml.encode("utf-8"))
    except etree.XMLSyntaxError:
        return None
    version = root.attrib.get("version")
    return version.strip() if version else None


def extract_vast_from_openrtb(
    payload: dict,
    seat_index: int = 0,
    bid_index: int = 0,
) -> ExtractedVast:
    """
    Extract inline VAST XML (adm) from OpenRTB bid response payload.
    Accepts both:
    - full wrapper with key raw_bid_response
    - plain OpenRTB bid response
    """
    bid_response = payload.get("raw_bid_response", payload)

    seatbid = bid_response.get("seatbid")
    if not isinstance(seatbid, list) or not seatbid:
        raise OpenRtbExtractionError("No seatbid[] found in response.")
    if seat_index < 0 or seat_index >= len(seatbid):
        raise OpenRtbExtractionError(
            f"seat_index={seat_index} out of range (seatbid size={len(seatbid)})."
        )

    bids = seatbid[seat_index].get("bid")
    if not isinstance(bids, list) or not bids:
        raise OpenRtbExtractionError("No bid[] found under selected seatbid.")
    if bid_index < 0 or bid_index >= len(bids):
        raise OpenRtbExtractionError(f"bid_index={bid_index} out of range (bid size={len(bids)}).")

    bid = bids[bid_index]
    adm = bid.get("adm")
    if not isinstance(adm, str) or not adm.strip():
        raise OpenRtbExtractionError(
            "Selected bid has no inline VAST in bid.adm. "
            "Check if partner returned nurl/adm in another bid."
        )

    vast_xml = adm.strip()
    return ExtractedVast(
        impid=bid.get("impid"),
        bid_id=bid.get("id"),
        vast_xml=vast_xml,
        vast_version=_extract_vast_version(vast_xml),
        vast_ad_tag_uri=_find_vast_ad_tag_uri(vast_xml),
    )


def _download_vast(url: str, timeout_seconds: int = 10) -> str:
    request = Request(url, headers={"User-Agent": "vast-validate/0.1"})
    with urlopen(request, timeout=timeout_seconds) as resp:
        body = resp.read()
    return body.decode("utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vast-extract",
        description="Extract VAST XML from OpenRTB response JSON.",
    )
    parser.add_argument("json_file", help="Path to JSON file containing OpenRTB response.")
    parser.add_argument(
        "--output",
        default="vast.xml",
        help="Path to write extracted VAST XML (default: vast.xml).",
    )
    parser.add_argument("--seat-index", type=int, default=0, help="seatbid index (default: 0).")
    parser.add_argument("--bid-index", type=int, default=0, help="bid index (default: 0).")
    parser.add_argument(
        "--follow-wrapper-uri",
        action="store_true",
        help="If VAST contains Wrapper/VASTAdTagURI, fetch that URL and save resolved VAST.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        payload = _load_json(Path(args.json_file))
        extracted = extract_vast_from_openrtb(
            payload=payload,
            seat_index=args.seat_index,
            bid_index=args.bid_index,
        )

        output_xml = extracted.vast_xml
        if args.follow_wrapper_uri and extracted.vast_ad_tag_uri:
            output_xml = _download_vast(extracted.vast_ad_tag_uri)

        output_path = Path(args.output).resolve()
        output_path.write_text(output_xml, encoding="utf-8")

        print(f"Saved VAST XML to: {output_path}")
        print(f"VAST version: {extracted.vast_version or 'unknown'}")
        print(f"impid: {extracted.impid}, bid.id: {extracted.bid_id}")
        if extracted.vast_ad_tag_uri:
            print(f"Wrapper VASTAdTagURI: {extracted.vast_ad_tag_uri}")
        return 0
    except OpenRtbExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: Failed writing output file: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # defensive
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
