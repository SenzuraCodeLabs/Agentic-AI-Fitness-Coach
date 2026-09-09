"""Shared types for the pipeline layers.

Every layer returns its result *and* a trace record. The trace is what makes a
decision explainable after the fact: the transparency panel, the explain
endpoint and the red-team evidence files are all built from it. A layer that
transformed text without recording what it did would make an attack
un-analysable, which is exactly what the individual report has to analyse.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from shared.contracts.enums import ReasonCode


@dataclass(slots=True)
class Transformation:
    """One change a layer made to the text.

    ``before`` and ``after`` are truncated: a trace is written to logs and to
    Mongo, and storing full user text at every step would multiply the amount
    of personal data retained.
    """

    kind: str
    detail: str = ""
    before: str = ""
    after: str = ""
    count: int = 1

    def truncated(self, limit: int = 60) -> Transformation:
        return Transformation(
            kind=self.kind,
            detail=self.detail[:120],
            before=self.before[:limit],
            after=self.after[:limit],
            count=self.count,
        )


@dataclass(slots=True)
class LayerTrace:
    """Timing, reason codes and transformations for one layer."""

    layer: str
    version: str
    duration_ms: float = 0.0
    reason_codes: list[ReasonCode] = field(default_factory=list)
    transformations: list[Transformation] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "version": self.version,
            "duration_ms": round(self.duration_ms, 3),
            "reason_codes": [str(c) for c in self.reason_codes],
            "transformations": [
                {
                    "kind": t.kind,
                    "detail": t.detail,
                    "before": t.before,
                    "after": t.after,
                    "count": t.count,
                }
                for t in (t.truncated() for t in self.transformations)
            ],
            "notes": self.notes,
        }


class Timer:
    """Context manager recording elapsed milliseconds into a LayerTrace.

    Uses ``perf_counter`` rather than ``time()`` because the latter is subject
    to wall-clock adjustments and has coarse resolution on Windows, which would
    make sub-millisecond layer timings meaningless.
    """

    __slots__ = ("_start", "trace")

    def __init__(self, trace: LayerTrace) -> None:
        self.trace = trace
        self._start = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.trace.duration_ms = (time.perf_counter() - self._start) * 1000
