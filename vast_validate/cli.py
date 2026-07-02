"""CLI for VAST XML validation."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

from colorama import Fore, Style, init

from .plain_language import build_plain_language_section
from .validator import overall_is_valid, validate_vast
from .validator_types import ChainLevel, ValidationResult, VastValidationException

init(autoreset=True)


def _c(text: str, color: str, enable_color: bool) -> str:
    return f"{color}{text}{Style.RESET_ALL}" if enable_color else text


def _hr(enable_color: bool) -> str:
    line = "=" * 80
    return _c(line, Fore.BLUE, enable_color)


def _load_openrtb_payload(response_json_path: str | None) -> dict | None:
    if not response_json_path:
        return None
    path = Path(response_json_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _extract_openrtb_context(response_json_path: str | None) -> dict[str, str | None]:
    payload = _load_openrtb_payload(response_json_path)
    if payload is None:
        if response_json_path:
            return {"context_error": f"Could not parse response JSON: {response_json_path}"}
        return {}

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
        description="Validate VAST XML against IAB XSD with optional wrapper-chain and OpenRTB checks.",
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
        help="Optional OpenRTB response JSON path for context and bid-level checks.",
    )
    parser.add_argument(
        "--follow-wrapper-chain",
        action="store_true",
        help="Fetch and validate each VASTAdTagURI in the wrapper chain.",
    )
    parser.add_argument(
        "--max-wrapper-depth",
        type=int,
        default=5,
        help="Maximum wrapper hops when following the chain (default: 5).",
    )
    parser.add_argument(
        "--strict-macros",
        action="store_true",
        help="Disable macro normalization before XSD validation (strict anyURI mode).",
    )
    parser.add_argument(
        "--no-best-practices",
        action="store_true",
        help="Skip semantic VAST best-practice checks.",
    )
    parser.add_argument(
        "--no-openrtb-checks",
        action="store_true",
        help="Skip OpenRTB bid-level checks even when --response-json is provided.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output in text mode.",
    )
    parser.add_argument(
        "--report-file",
        dest="report_file",
        default="vast_validation_report.txt",
        help=(
            "Path to save formatted validation report. "
            "File is overwritten on every run (default: vast_validation_report.txt)."
        ),
    )
    return parser


def _severity_color(severity: str, enable_color: bool) -> str:
    if severity == "error":
        return _c(severity.upper(), Fore.RED + Style.BRIGHT, enable_color)
    if severity == "warning":
        return _c(severity.upper(), Fore.YELLOW, enable_color)
    return _c(severity.upper(), Fore.CYAN, enable_color)


def _format_chain_section(chain: list[ChainLevel], enable_color: bool) -> list[str]:
    if not chain:
        return []
    lines = [_c("WRAPPER CHAIN", Fore.MAGENTA + Style.BRIGHT, enable_color), "-" * 80]
    for level in chain:
        schema = level.schema_result
        status = "PASS" if schema and schema.is_valid else "FAIL"
        color = Fore.GREEN if status == "PASS" else Fore.RED
        lines.append(
            _c(
                f"[level {level.level}] {status} | {level.ad_type} | v{level.vast_version or '?'}",
                color + Style.BRIGHT,
                enable_color,
            )
        )
        lines.append(f"  source: {level.source}")
        if level.vast_ad_tag_uri:
            lines.append(f"  next:   {level.vast_ad_tag_uri}")
        if schema and schema.errors:
            for err in schema.errors[:3]:
                lines.append(f"  xsd:    line {err.line}: {err.message}")
        for issue in level.best_practices:
            if issue.severity == "error":
                lines.append(f"  rule:   [{issue.code}] {issue.message}")
    return lines


def _build_text_report(result: ValidationResult, context: dict[str, str | None], enable_color: bool) -> str:
    lines: list[str] = []
    generated_at = datetime.now(timezone.utc).isoformat()
    passed = overall_is_valid(result)

    lines.append(_hr(enable_color))
    lines.append(_c("VAST VALIDATION REPORT", Fore.CYAN + Style.BRIGHT, enable_color))
    lines.append(_hr(enable_color))
    lines.append(f"GENERATED: {generated_at}")

    if passed:
        lines.append(_c("STATUS   : PASS", Fore.GREEN + Style.BRIGHT, enable_color))
    else:
        lines.append(_c("STATUS   : FAIL", Fore.RED + Style.BRIGHT, enable_color))

    lines.append(f"XSD      : {'PASS' if result.is_valid else 'FAIL'}")
    lines.append(f"VERSION  : {result.vast_version or 'unknown'}")
    lines.append(f"SCHEMA   : {result.schema_path}")
    if result.schema_resolution_note:
        lines.append(f"SCHEMA-NOTE: {result.schema_resolution_note}")

    if result.macro_substitutions:
        macros = ", ".join(f"[{m.macro}]x{m.count}" for m in result.macro_substitutions)
        lines.append(f"MACROS   : normalized for XSD ({macros})")
    if result.unknown_macros:
        lines.append(
            _c(
                f"MACRO-WARN: unknown macros found: {', '.join(result.unknown_macros)}",
                Fore.YELLOW,
                enable_color,
            )
        )

    if context:
        lines.append(
            "CONTEXT  : "
            f"partner={context.get('partner_name') or 'unknown'}, "
            f"line_item={context.get('line_item_name') or context.get('line_item_id') or 'unknown'}, "
            f"impid={context.get('impid') or 'unknown'}, "
            f"bid_id={context.get('bid_id') or 'unknown'}"
        )
        if context.get("context_error"):
            lines.append(_c(f"WARNING  : {context['context_error']}", Fore.YELLOW, enable_color))

    if not result.is_valid:
        first_error = result.errors[0] if result.errors else None
        if first_error:
            summary_text = (
                f"VAST v{result.vast_version or 'unknown'} XSD invalid - "
                f"line {first_error.line}: {first_error.message}"
            )
            lines.append(_c("XSD-ERR  : ", Fore.YELLOW + Style.BRIGHT, enable_color) + summary_text)

    if result.best_practices:
        lines.append(_c("BEST PRACTICES", Fore.MAGENTA + Style.BRIGHT, enable_color))
        lines.append("-" * 80)
        for issue in result.best_practices:
            lines.append(
                f"  [{_severity_color(issue.severity, enable_color)}] {issue.code}: {issue.message}"
            )

    if result.openrtb_issues:
        lines.append(_c("OPENRTB CHECKS", Fore.MAGENTA + Style.BRIGHT, enable_color))
        lines.append("-" * 80)
        for issue in result.openrtb_issues:
            lines.append(
                f"  [{_severity_color(issue.severity, enable_color)}] {issue.code}: {issue.message}"
            )

    lines.extend(_format_chain_section(result.chain, enable_color))

    if result.errors:
        lines.append(_c("XSD ERRORS", Fore.MAGENTA + Style.BRIGHT, enable_color))
        lines.append(_c("-" * 80, Fore.BLUE, enable_color))
        for idx, err in enumerate(result.errors, start=1):
            lines.append(
                f"[{idx}] line={err.line}, column={err.column}\n"
                f"    domain={err.domain}, type={err.error_type}\n"
                f"    message={err.message}"
            )

    plain_lines = build_plain_language_section(result, passed=passed)
    lines.append(_c(plain_lines[0], Fore.GREEN + Style.BRIGHT, enable_color))
    lines.extend(plain_lines[1:])

    lines.append(_hr(enable_color))
    return "\n".join(lines)


def _build_fatal_text_report(message: str, context: dict[str, str | None], enable_color: bool) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    lines: list[str] = [
        _hr(enable_color),
        _c("VAST VALIDATION REPORT", Fore.CYAN + Style.BRIGHT, enable_color),
        _hr(enable_color),
        f"GENERATED: {generated_at}",
        _c("STATUS   : ERROR", Fore.RED + Style.BRIGHT, enable_color),
        f"MESSAGE  : {message}",
    ]
    if context:
        lines.append(
            "CONTEXT  : "
            f"partner={context.get('partner_name') or 'unknown'}, "
            f"line_item={context.get('line_item_name') or context.get('line_item_id') or 'unknown'}, "
            f"impid={context.get('impid') or 'unknown'}, "
            f"bid_id={context.get('bid_id') or 'unknown'}"
        )
    lines.append(_c("PLAIN-LANGUAGE SUMMARY", Fore.GREEN + Style.BRIGHT, enable_color))
    lines.append("-" * 80)
    lines.append(f"The validation could not run: {message}")
    lines.append(_hr(enable_color))
    return "\n".join(lines)


def _write_report_file(report_text: str, report_file: str | None) -> None:
    if not report_file:
        return
    report_path = Path(report_file).resolve()
    report_path.write_text(report_text + "\n", encoding="utf-8")


def _chain_to_json(chain: list[ChainLevel]) -> list[dict]:
    payload = []
    for level in chain:
        schema = level.schema_result
        payload.append(
            {
                "level": level.level,
                "source": level.source,
                "ad_type": level.ad_type,
                "vast_version": level.vast_version,
                "vast_ad_tag_uri": level.vast_ad_tag_uri,
                "xsd_valid": schema.is_valid if schema else False,
                "xsd_errors": [
                    {
                        "line": e.line,
                        "column": e.column,
                        "message": e.message,
                    }
                    for e in (schema.errors if schema else [])
                ],
                "best_practices": [
                    {"severity": i.severity, "code": i.code, "message": i.message}
                    for i in level.best_practices
                ],
                "unknown_macros": level.unknown_macros,
            }
        )
    return payload


def _print_json(result: ValidationResult, context: dict[str, str | None]) -> int:
    passed = overall_is_valid(result)
    payload = {
        "is_valid": passed,
        "xsd_valid": result.is_valid,
        "vast_version": result.vast_version,
        "schema_path": str(result.schema_path) if result.schema_path else None,
        "schema_resolution_note": result.schema_resolution_note,
        "summary": None,
        "context": context or None,
        "macro_substitutions": [
            {"macro": m.macro, "count": m.count} for m in result.macro_substitutions
        ],
        "unknown_macros": result.unknown_macros,
        "best_practices": [
            {"severity": i.severity, "code": i.code, "message": i.message}
            for i in result.best_practices
        ],
        "openrtb_issues": [
            {"severity": i.severity, "code": i.code, "message": i.message}
            for i in result.openrtb_issues
        ],
        "chain": _chain_to_json(result.chain) if result.chain else None,
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
            f"VAST v{result.vast_version or 'unknown'} XSD invalid "
            f"at line {first.line}: {first.message}"
        )
    elif not passed:
        payload["summary"] = "VAST failed best-practice, OpenRTB, or wrapper-chain checks"
    else:
        payload["summary"] = f"VAST v{result.vast_version or 'unknown'} passed all enabled checks"
    print(json.dumps(payload, indent=2))
    return 0 if passed else 1


def _print_text(result: ValidationResult, context: dict[str, str | None], enable_color: bool) -> int:
    print(_build_text_report(result, context, enable_color))
    return 0 if overall_is_valid(result) else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    context = _extract_openrtb_context(args.response_json)
    enable_color = not args.no_color
    openrtb_payload = None
    if args.response_json and not args.no_openrtb_checks:
        openrtb_payload = _load_openrtb_payload(args.response_json)

    try:
        result = validate_vast(
            xml_path=args.xml,
            schema_path=args.xsd,
            schema_dir=args.schema_dir,
            normalize_macros=not args.strict_macros,
            check_best_practices=not args.no_best_practices,
            openrtb_payload=openrtb_payload,
            follow_wrapper_chain=args.follow_wrapper_chain,
            max_wrapper_depth=args.max_wrapper_depth,
        )
        plain_report = _build_text_report(result, context, enable_color=False)
        report_save_error: str | None = None
        if args.report_file:
            try:
                _write_report_file(plain_report, args.report_file)
            except OSError as write_exc:
                report_save_error = str(write_exc)
        if args.json:
            exit_code = _print_json(result, context)
        else:
            exit_code = _print_text(result, context, enable_color)
        if args.report_file:
            report_path = Path(args.report_file).resolve()
            if report_save_error:
                print(f"Report save warning: {report_save_error}", file=sys.stderr)
            else:
                print(f"Report saved: {report_path}")
        return exit_code
    except VastValidationException as exc:
        fatal_report = _build_fatal_text_report(str(exc), context, enable_color=False)
        try:
            _write_report_file(fatal_report, args.report_file)
        except OSError:
            pass
        if args.json:
            print(
                json.dumps(
                    {"is_valid": False, "fatal_error": str(exc), "context": context or None},
                    indent=2,
                )
            )
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
            if args.report_file:
                print(f"Report saved: {Path(args.report_file).resolve()}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
