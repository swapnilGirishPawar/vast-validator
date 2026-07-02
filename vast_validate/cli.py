"""CLI for VAST XML validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from colorama import Fore, Style, init

from .validator import VastValidationException, validate_vast

init(autoreset=True)


def _c(text: str, color: str, enable_color: bool) -> str:
    return f"{color}{text}{Style.RESET_ALL}" if enable_color else text


def _hr(enable_color: bool) -> str:
    line = "=" * 80
    return _c(line, Fore.BLUE, enable_color)


def _extract_openrtb_context(response_json_path: str | None) -> dict[str, str | None]:
    if not response_json_path:
        return {}

    path = Path(response_json_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"context_error": f"Could not parse response JSON: {path}"}

    bid_response = payload.get("raw_bid_response", payload)
    seatbid = bid_response.get("seatbid") or []
    first_bid = {}
    if seatbid and isinstance(seatbid, list):
        first = seatbid[0] or {}
        bids = first.get("bid") or []
        if bids and isinstance(bids, list):
            first_bid = bids[0] or {}

    meta = payload.get("voisetech_metadata") or {}
    return {
        "partner_name": meta.get("partner_name"),
        "partner_id": meta.get("partner_id"),
        "line_item_id": meta.get("line_item_id"),
        "line_item_name": meta.get("line_item_name"),
        "impid": first_bid.get("impid"),
        "bid_id": first_bid.get("id"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vast-validate",
        description="Validate VAST XML against a VAST XSD using lxml.",
    )
    parser.add_argument("xml", help="Path to VAST XML file.")
    parser.add_argument(
        "--xsd",
        dest="xsd",
        default=None,
        help="Path to XSD file. If omitted, auto-detect by VAST version.",
    )
    parser.add_argument(
        "--schema-dir",
        dest="schema_dir",
        default=None,
        help="Directory containing versioned XSDs (e.g. vast_4.2.xsd).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    parser.add_argument(
        "--response-json",
        dest="response_json",
        default=None,
        help="Optional OpenRTB response JSON path for pretty summary context.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output in text mode.",
    )
    return parser


def _print_text(result, context: dict[str, str | None], enable_color: bool) -> int:
    print(_hr(enable_color))
    print(_c("VAST VALIDATION REPORT", Fore.CYAN + Style.BRIGHT, enable_color))
    print(_hr(enable_color))

    if result.is_valid:
        print(_c("STATUS   : PASS", Fore.GREEN + Style.BRIGHT, enable_color))
        print(f"VERSION  : {result.vast_version or 'unknown'}")
        print(f"SCHEMA   : {result.schema_path}")
        if context:
            print(
                "CONTEXT  : "
                f"partner={context.get('partner_name') or 'unknown'}, "
                f"line_item={context.get('line_item_name') or context.get('line_item_id') or 'unknown'}, "
                f"impid={context.get('impid') or 'unknown'}, "
                f"bid_id={context.get('bid_id') or 'unknown'}"
            )
        print(_hr(enable_color))
        return 0

    print(_c("STATUS   : FAIL", Fore.RED + Style.BRIGHT, enable_color))
    print(f"VERSION  : {result.vast_version or 'unknown'}")
    print(f"SCHEMA   : {result.schema_path}")
    first_error = result.errors[0] if result.errors else None
    if first_error:
        summary_text = (
            f"VAST v{result.vast_version or 'unknown'} invalid - "
            f"line {first_error.line}: {first_error.message}"
        )
        print(
            _c("SUMMARY  : ", Fore.YELLOW + Style.BRIGHT, enable_color) + summary_text
        )
    if context:
        print(
            "CONTEXT  : "
            f"partner={context.get('partner_name') or 'unknown'}, "
            f"line_item={context.get('line_item_name') or context.get('line_item_id') or 'unknown'}, "
            f"impid={context.get('impid') or 'unknown'}, "
            f"bid_id={context.get('bid_id') or 'unknown'}"
        )
        if context.get("context_error"):
            print(_c(f"WARNING  : {context['context_error']}", Fore.YELLOW, enable_color))
    print(_c("ERRORS", Fore.MAGENTA + Style.BRIGHT, enable_color))
    print(_c("-" * 80, Fore.BLUE, enable_color))
    for idx, err in enumerate(result.errors, start=1):
        print(
            f"[{idx}] line={err.line}, column={err.column}\n"
            f"    domain={err.domain}, type={err.error_type}\n"
            f"    message={err.message}"
        )
    print(_hr(enable_color))
    return 1


def _print_json(result, context: dict[str, str | None]) -> int:
    payload = {
        "is_valid": result.is_valid,
        "vast_version": result.vast_version,
        "schema_path": str(result.schema_path) if result.schema_path else None,
        "summary": None,
        "context": context or None,
        "errors": [
            {
                "line": e.line,
                "column": e.column,
                "domain": e.domain,
                "type": e.error_type,
                "message": e.message,
            }
            for e in result.errors
        ],
    }
    if result.errors:
        first = result.errors[0]
        payload["summary"] = (
            f"VAST v{result.vast_version or 'unknown'} invalid "
            f"at line {first.line}: {first.message}"
        )
    elif result.is_valid:
        payload["summary"] = f"VAST v{result.vast_version or 'unknown'} is valid"
    print(json.dumps(payload, indent=2))
    return 0 if result.is_valid else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    context = _extract_openrtb_context(args.response_json)
    enable_color = not args.no_color

    try:
        result = validate_vast(
            xml_path=args.xml,
            schema_path=args.xsd,
            schema_dir=args.schema_dir,
        )
        return _print_json(result, context) if args.json else _print_text(result, context, enable_color)
    except VastValidationException as exc:
        if args.json:
            print(
                json.dumps(
                    {"is_valid": False, "fatal_error": str(exc), "context": context or None},
                    indent=2,
                )
            )
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
