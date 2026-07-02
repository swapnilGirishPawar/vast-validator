"""Shared validation datatypes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .best_practices import PracticeIssue
from .macros import MacroSubstitution
from .openrtb_checks import OpenRtbIssue


@dataclass(slots=True)
class ValidationError:
    line: int
    column: int
    message: str
    domain: str | None = None
    error_type: str | None = None


@dataclass(slots=True)
class ChainLevel:
    level: int
    source: str
    ad_type: str
    vast_version: str | None
    vast_ad_tag_uri: str | None = None
    schema_result: ValidationResult | None = None
    best_practices: list[PracticeIssue] = field(default_factory=list)
    unknown_macros: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationResult:
    is_valid: bool
    vast_version: str | None
    schema_path: Path | None
    schema_resolution_note: str | None = None
    errors: list[ValidationError] = field(default_factory=list)
    macro_substitutions: list[MacroSubstitution] = field(default_factory=list)
    unknown_macros: list[str] = field(default_factory=list)
    best_practices: list[PracticeIssue] = field(default_factory=list)
    openrtb_issues: list[OpenRtbIssue] = field(default_factory=list)
    chain: list[ChainLevel] = field(default_factory=list)


class VastValidationException(Exception):
    """Raised for validation setup and parsing errors."""
