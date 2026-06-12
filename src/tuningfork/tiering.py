"""
tuningfork.tiering — G6: Cost-Tiered Verification Budget,
plus the G4 known-signature catalog and the G6 convenience penalty
("too-perfect test").

The tier of a claim is decided BEFORE generation acts on it and may
never be downgraded retroactively. Signatures below are deterministic
heuristics: they don't prove fabrication, they price the verification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum


class Tier(IntEnum):
    LOW = 0      # conceptual explanation — no tool call required
    MEDIUM = 1   # specific facts, runnable code, named entities — one check
    HIGH = 2     # destructive ops, externally actionable output — check + closed loop

    def raised(self) -> "Tier":
        """Convenience penalty: raise one level, capped at HIGH."""
        return Tier(min(self.value + 1, Tier.HIGH.value))


# G4 known-signature catalog: patterns that historically mark fabrication.
# A match does not prove error — it auto-triggers an existence probe.
SIGNATURE_CATALOG: dict[str, re.Pattern] = {
    "version_number": re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b"),
    "cli_flag": re.compile(r"(?<!\w)--[a-z][\w-]{2,}\b"),
    "price_or_money": re.compile(r"[$€£]\s?\d"),
    "specific_date": re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b"),
    "url": re.compile(r"https?://\S+"),
    "api_method": re.compile(r"\.\w+\([^)]*\)"),
}

# Convenience-penalty signatures: phrasing that marks a claim as
# suspiciously frictionless or conveniently untestable.
PERFECTION_SIGNATURES: dict[str, re.Pattern] = {
    "exactly_what_we_need": re.compile(
        r"\b(exactly what (?:we|you) need|conveniently|perfect for this|"
        r"precisely the (?:method|function|flag))\b", re.I),
    "unfalsifiable_framing": re.compile(
        r"\b(there'?s no way to (?:check|verify|test)|"
        r"can'?t be (?:verified|tested)|trust me)\b", re.I),
    "total_coverage": re.compile(
        r"\b(explains everything|all of (?:this|it) fits|no loose ends)\b", re.I),
}


@dataclass
class TierDecision:
    tier: Tier
    base_tier: Tier
    catalog_hits: list[str]
    perfection_hits: list[str]
    rationale: str


def assess(claim_text: str, *, destructive: bool = False,
           externally_actionable: bool = False) -> TierDecision:
    """Price a claim before generation commits to it.

    destructive / externally_actionable are declared by the caller (the
    agent harness) about the *task*, not inferred from text — the tier
    may not be talked down by the narrative.
    """
    if destructive or externally_actionable:
        base = Tier.HIGH
    else:
        catalog = [name for name, pat in SIGNATURE_CATALOG.items()
                   if pat.search(claim_text)]
        base = Tier.MEDIUM if catalog else Tier.LOW

    catalog_hits = [name for name, pat in SIGNATURE_CATALOG.items()
                    if pat.search(claim_text)]
    perfection_hits = [name for name, pat in PERFECTION_SIGNATURES.items()
                       if pat.search(claim_text)]

    tier = base.raised() if perfection_hits else base

    rationale_parts = [f"base={base.name}"]
    if catalog_hits:
        rationale_parts.append(f"catalog={catalog_hits}")
    if perfection_hits:
        rationale_parts.append(f"too-perfect={perfection_hits} -> raised to {tier.name}")
    return TierDecision(tier=tier, base_tier=base,
                        catalog_hits=catalog_hits,
                        perfection_hits=perfection_hits,
                        rationale="; ".join(rationale_parts))
