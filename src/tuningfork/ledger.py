"""
tuningfork.ledger — G8: Source Re-attribution.

A verified-false output is not noise to discard. It is evidence about the
generator: its priors, its biases, the direction of its drift. The ledger
re-attributes rejected content — from "claim about the world" to "data
about the model" — and mines it.

Three functions:
  1. Accumulate every rejected finding across runs.
  2. Feed EchoValidator's rejected_history automatically, so stale
     re-assertions of mined fabrications are caught at HIGH severity.
  3. Build the generator's bias profile: which validators fire most,
     which fabricated claims recur. Recurring fabrications graduate into
     known signatures — the catalog is accumulated, not hand-written.

The principle this encodes: belief and action are decoupled. The system
never requires the generator to stop producing the false signal; it
requires only that actions trace to verified sources. Rejected content
updates the model-of-the-model. It never updates the world model.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from dataclasses import dataclass, field

from .validators import Finding, ValidationReport


@dataclass
class BiasProfile:
    """What this generator's fabrications look like, empirically."""
    rejections_by_validator: dict[str, int]
    recurring_claims: list[tuple[str, int]]   # (claim, times rejected)
    total_rejections: int

    def summary(self) -> str:
        if not self.total_rejections:
            return "No rejections recorded — no bias profile yet."
        lines = [f"Bias profile from {self.total_rejections} rejections:"]
        for v, n in sorted(self.rejections_by_validator.items(),
                           key=lambda kv: -kv[1]):
            lines.append(f"  {v}: {n}")
        if self.recurring_claims:
            lines.append("Recurring fabrications (candidate signatures):")
            for claim, n in self.recurring_claims:
                lines.append(f"  x{n}  {claim!r}")
        return "\n".join(lines)


class RejectionLedger:
    """Accumulates verified-false output across a session and mines it.

    Usage:
        ledger = RejectionLedger()
        ...
        if not report.clean:
            ledger.record(output, report)
        echo = EchoValidator(rejected_history=ledger.rejected_outputs)
    """

    def __init__(self, recurrence_threshold: int = 2):
        self.rejected_outputs: list[str] = []
        self._claims: Counter[str] = Counter()
        self._by_validator: Counter[str] = Counter()
        self.recurrence_threshold = recurrence_threshold

    # -- accumulate -------------------------------------------------------
    def record(self, output: str, report: ValidationReport) -> None:
        """Re-attribute one rejected output: file it as generator-evidence."""
        if report.clean:
            return
        self.rejected_outputs.append(output)
        for f in report.failures:
            self._claims[f.claim] += 1
            self._by_validator[f.validator] += 1

    # -- mine -------------------------------------------------------------
    def profile(self) -> BiasProfile:
        recurring = [(c, n) for c, n in self._claims.most_common()
                     if n >= self.recurrence_threshold]
        return BiasProfile(
            rejections_by_validator=dict(self._by_validator),
            recurring_claims=recurring,
            total_rejections=sum(self._by_validator.values()),
        )

    def known_signatures(self) -> list[str]:
        """Fabrications rejected enough times to count as 'known' — the
        accumulated library. A match against these is recognized, not
        re-analyzed (recognition is cheaper than analysis)."""
        return [c for c, n in self._claims.items()
                if n >= self.recurrence_threshold]

    # -- persistence (G8 across sessions: the library survives restarts) ---
    def save(self, path) -> None:
        Path(path).write_text(json.dumps({
            "rejected_outputs": self.rejected_outputs[-200:],
            "claims": dict(self._claims),
            "by_validator": dict(self._by_validator),
        }, indent=1))

    @classmethod
    def load(cls, path, recurrence_threshold: int = 2) -> "RejectionLedger":
        led = cls(recurrence_threshold=recurrence_threshold)
        p = Path(path)
        if p.exists():
            try:
                d = json.loads(p.read_text())
                led.rejected_outputs = list(d.get("rejected_outputs", []))
                led._claims.update(d.get("claims", {}))
                led._by_validator.update(d.get("by_validator", {}))
            except (json.JSONDecodeError, OSError):
                pass  # corrupt ledger: start fresh rather than crash
        return led
