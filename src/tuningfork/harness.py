"""
tuningfork.harness — wires the rules around any LLM callable.

Provider-agnostic: pass any `generate(prompt: str) -> str` callable.
The harness does not improve the model. It surrounds the model with
channels the model cannot argue with:

  G6  price the task before generation (tier decided up front)
  G7  run the validator bank over the output (the watch)
  G4  validator misses become existence probes, not debates
  G5  on a confirmed miss at HIGH tier, the narrative is discarded and
      state is rebuilt from evidence only (the tuning fork: interrupt
      the state, don't argue with it)

Termination principle (G3 / Section 6): a check is finished when it is
confirmed by a channel that cannot share the generator's failure mode.
One deterministic confirmation is final. Same-model re-review is never
terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .tiering import Tier, TierDecision, assess
from .validators import ValidationReport, ValidatorBank


@dataclass
class GroundedResult:
    output: str
    tier: TierDecision
    report: ValidationReport
    regenerated: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def trustworthy(self) -> bool:
        return self.report.clean


class GroundedAgent:
    """Wrap a generator with pre-generation pricing and post-generation
    independent validation. Exactly one regeneration pass is permitted
    (Section 6 fallback cap); a second failure is reported, not retried,
    because retrying the same channel is re-checking the check."""

    def __init__(self, generate: Callable[[str], str], bank: ValidatorBank):
        self.generate = generate
        self.bank = bank

    def run(self, prompt: str, *, destructive: bool = False,
            externally_actionable: bool = False) -> GroundedResult:
        # G6: tier decided before generation; cannot be downgraded later.
        tier = assess(prompt, destructive=destructive,
                      externally_actionable=externally_actionable)

        output = self.generate(prompt)
        report = self.bank.run(output)              # G7: the watch
        result = GroundedResult(output=output, tier=tier, report=report)

        if report.clean:
            return result

        # G7 miss -> route by tier.
        if tier.tier >= Tier.MEDIUM:
            # Section 6 fallback cap: ONE regeneration, fed the evidence.
            evidence = report.summary()
            correction_prompt = (
                f"{prompt}\n\n"
                f"[GROUNDING — independent validators rejected the previous "
                f"draft. Their findings are evidence, not suggestions. Do not "
                f"reuse any rejected claim unless it reappears in fresh "
                f"evidence (G5).]\n{evidence}"
            )
            output2 = self.generate(correction_prompt)
            report2 = self.bank.run(output2)
            result = GroundedResult(output=output2, tier=tier,
                                    report=report2, regenerated=True)
            if not report2.clean:
                result.notes.append(
                    "Regeneration cap reached; remaining failures reported "
                    "to the user as unresolved (G3 termination)."
                )
        else:
            result.notes.append(
                "Low tier: failures flagged inline; no regeneration spent."
            )
        return result
