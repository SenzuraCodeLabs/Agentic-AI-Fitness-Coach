"""Test-case schema and loader for the red-team suite.

A case is data, not code. That matters for this assignment: the payloads are
YOUR work and must be defensible at a viva, so they live in reviewable files
rather than being buried in Python.

The schema is validated on load. A malformed case fails immediately with a
clear message rather than producing a misleading result three hours into a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

CASES_DIR = Path(__file__).resolve().parent / "cases"


class Family(StrEnum):
    """Attack family. Used to group findings in the report."""

    DIRECT_INJECTION = "direct_injection"
    INDIRECT_INJECTION = "indirect_injection"
    JAILBREAK = "jailbreak"
    SYSTEM_PROMPT_EXTRACTION = "system_prompt_extraction"
    DATA_EXFILTRATION = "data_exfiltration"
    ENCODING_EVASION = "encoding_evasion"
    OBFUSCATION = "obfuscation"
    PROTOCOL_ATTACK = "protocol_attack"
    POLICY_BYPASS = "policy_bypass"
    DENIAL_OF_SERVICE = "denial_of_service"
    # Benign families. A suite made only of attacks cannot measure whether the
    # defences are too aggressive, and over-refusal is a real failure mode.
    OVER_REFUSAL = "over_refusal"
    BENIGN_CONTROL = "benign_control"


class Severity(StrEnum):
    """Severity IF the test fails. Your judgement, recorded in the case file.

    Deliberately not inferred from the family: two cases in the same family can
    have very different impact, and an automatically assigned severity is not
    one you can defend.
    """

    INFO = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Endpoint(StrEnum):
    CHAT = "chat"
    PIPELINE = "pipeline"
    A2A_COACH = "a2a_coach"
    A2A_RESEARCHER = "a2a_researcher"
    AUTH = "auth"


@dataclass(slots=True)
class TestCase:
    id: str
    title: str
    family: Family
    objective: str
    payload: str | list[str]
    expected_behaviour: str
    severity_if_failed: Severity
    owasp_ref: str = ""
    target_endpoint: Endpoint = Endpoint.CHAT
    notes: str = ""
    # Optional machine-checkable assertions. When present the runner reports a
    # pass or fail; when absent the case is captured as evidence for your own
    # judgement, which is the honest default for anything subtle.
    expect_decision: str | None = None
    expect_blocked: bool | None = None
    expect_not_in_response: list[str] = field(default_factory=list)
    expect_in_response: list[str] = field(default_factory=list)
    source_file: str = ""

    @property
    def is_multi_turn(self) -> bool:
        return isinstance(self.payload, list)

    @property
    def turns(self) -> list[str]:
        return self.payload if isinstance(self.payload, list) else [self.payload]

    @property
    def is_automatically_checkable(self) -> bool:
        return any(
            [
                self.expect_decision is not None,
                self.expect_blocked is not None,
                self.expect_not_in_response,
                self.expect_in_response,
            ]
        )


class CaseValidationError(Exception):
    pass


REQUIRED_FIELDS = (
    "id",
    "title",
    "family",
    "objective",
    "payload",
    "expected_behaviour",
    "severity_if_failed",
)


def _parse_case(raw: dict[str, Any], source: Path) -> TestCase:
    missing = [f for f in REQUIRED_FIELDS if f not in raw or raw[f] in (None, "")]
    if missing:
        raise CaseValidationError(
            f"{source.name}: case {raw.get('id', '?')} is missing {', '.join(missing)}"
        )

    try:
        family = Family(str(raw["family"]))
    except ValueError as exc:
        valid = ", ".join(f.value for f in Family)
        raise CaseValidationError(
            f"{source.name}: case {raw['id']} has unknown family "
            f"'{raw['family']}'. Valid families: {valid}"
        ) from exc

    try:
        severity = Severity(str(raw["severity_if_failed"]))
    except ValueError as exc:
        valid = ", ".join(s.value for s in Severity)
        raise CaseValidationError(
            f"{source.name}: case {raw['id']} has unknown severity "
            f"'{raw['severity_if_failed']}'. Valid: {valid}"
        ) from exc

    try:
        endpoint = Endpoint(str(raw.get("target_endpoint", "chat")))
    except ValueError as exc:
        valid = ", ".join(e.value for e in Endpoint)
        raise CaseValidationError(
            f"{source.name}: case {raw['id']} has unknown endpoint. Valid: {valid}"
        ) from exc

    payload = raw["payload"]
    if not isinstance(payload, str | list):
        raise CaseValidationError(
            f"{source.name}: case {raw['id']} payload must be a string or a list"
        )

    return TestCase(
        id=str(raw["id"]),
        title=str(raw["title"]),
        family=family,
        objective=str(raw["objective"]),
        payload=payload,
        expected_behaviour=str(raw["expected_behaviour"]),
        severity_if_failed=severity,
        owasp_ref=str(raw.get("owasp_ref", "")),
        target_endpoint=endpoint,
        notes=str(raw.get("notes", "")),
        expect_decision=raw.get("expect_decision"),
        expect_blocked=raw.get("expect_blocked"),
        expect_not_in_response=list(raw.get("expect_not_in_response", [])),
        expect_in_response=list(raw.get("expect_in_response", [])),
        source_file=source.name,
    )


def load_cases(directory: Path | None = None) -> list[TestCase]:
    """Load and validate every case file. Ids must be unique across files."""
    directory = directory or CASES_DIR
    if not directory.exists():
        raise CaseValidationError(f"cases directory not found: {directory}")

    cases: list[TestCase] = []
    seen: dict[str, str] = {}

    for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = document.get("cases", [])
        if not isinstance(entries, list):
            raise CaseValidationError(f"{path.name}: 'cases' must be a list")

        for raw in entries:
            case = _parse_case(raw, path)
            if case.id in seen:
                raise CaseValidationError(
                    f"duplicate case id '{case.id}' in {path.name} "
                    f"(already defined in {seen[case.id]})"
                )
            seen[case.id] = path.name
            cases.append(case)

    return cases
