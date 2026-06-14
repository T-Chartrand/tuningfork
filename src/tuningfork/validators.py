"""
tuningfork.validators — G7: Passive Independent Validators.

Deterministic checks that observe an agent's output but cannot share its
failure modes. A language model can fabricate a file path, a citation, or
a function name with perfect fluency; a grep cannot. These validators are
the agent equivalent of an external perceptual channel: they report binary
facts and do not ask the generator for permission to run.

Design rules (from the framework):
  * Validators are deterministic and cheap. They run at every tier.
  * A validator reports facts, never opinions. PASS/FAIL plus evidence.
  * A miss is a hallucination *signal*, not proof — it triggers G4
    (existence probe) or G5 (snapshot rebuild) depending on stakes.

Stdlib only. No dependencies.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------

@dataclass
class Finding:
    """A single validator hit: one claim checked against one channel."""
    validator: str
    claim: str            # the string in the output that was checked
    passed: bool
    evidence: str         # what the independent channel actually reported
    severity: str = "medium"  # low | medium | high — feeds G6 tier routing


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed]

    @property
    def clean(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        if self.clean:
            return f"PASS — {len(self.findings)} claims checked, 0 failures."
        lines = [f"FAIL — {len(self.failures)}/{len(self.findings)} checks failed:"]
        for f in self.failures:
            lines.append(f"  [{f.validator}] {f.claim!r}: {f.evidence}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Validators
# --------------------------------------------------------------------------

class PathValidator:
    """Every file path the agent mentions must exist on disk OR appear in
    the evidence set (paths previously returned by tools). Mentioning a
    path that exists nowhere is the classic fabrication signature."""

    name = "path"
    # Conservative pattern: unix-ish and windows-ish absolute paths.
    _PATTERN = re.compile(
        r"(?:(?:[A-Za-z]:\\|/)(?:[\w.\-]+[/\\])*[\w.\-]+\.\w{1,8})"
    )

    def __init__(self, evidence_paths: Iterable[str] = (), check_disk: bool = True):
        self.evidence = {str(p) for p in evidence_paths}
        self.check_disk = check_disk
        self._exists_cache: dict[str, bool] = {}

    def _exists(self, p: str) -> bool:
        if p not in self._exists_cache:
            self._exists_cache[p] = Path(p).exists()
        return self._exists_cache[p]

    def run(self, output: str) -> list[Finding]:
        findings = []
        for match in set(self._PATTERN.findall(output)):
            in_evidence = match in self.evidence
            on_disk = self.check_disk and self._exists(match)
            passed = in_evidence or on_disk
            findings.append(Finding(
                validator=self.name,
                claim=match,
                passed=passed,
                evidence=(
                    "found in tool evidence" if in_evidence
                    else "exists on disk" if on_disk
                    else "NOT in any tool result and NOT on disk"
                ),
            ))
        return findings


class JsonBlockValidator:
    """Every fenced ```json block in the output must parse. Fluent,
    confident, syntactically broken JSON is a cheap drift signal."""

    name = "json"
    _FENCE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL)

    def run(self, output: str) -> list[Finding]:
        findings = []
        for i, block in enumerate(self._FENCE.findall(output)):
            try:
                json.loads(block)
                findings.append(Finding(self.name, f"json block #{i}", True, "parses"))
            except json.JSONDecodeError as e:
                findings.append(Finding(self.name, f"json block #{i}", False,
                                        f"parse error: {e}", severity="high"))
        return findings


class CitationValidator:
    """Every citation marker like [3] or [doc-2] must resolve to a source
    that actually exists in the provided context. Phantom citations are
    among the most common LLM fabrications."""

    name = "citation"
    _PATTERN = re.compile(r"\[(\d{1,3}|doc-\d{1,3})\]")

    def __init__(self, valid_source_ids: Iterable[str]):
        self.valid = {str(s) for s in valid_source_ids}

    def run(self, output: str) -> list[Finding]:
        findings = []
        for ref in set(self._PATTERN.findall(output)):
            passed = ref in self.valid
            findings.append(Finding(
                validator=self.name, claim=f"[{ref}]", passed=passed,
                evidence="source exists in context" if passed
                         else f"no source {ref!r} in context",
            ))
        return findings


class SymbolValidator:
    """Every code symbol the agent claims exists in a codebase must be
    findable by grep (G4 negative-space probing, automated). Pass the
    repo root and a list of symbols extracted from the output, or let
    it auto-extract dotted/called identifiers from fenced code blocks."""

    name = "symbol"
    _CALL = re.compile(r"\b([A-Za-z_][\w.]+)\s*\(")

    def __init__(self, repo_root: str | Path, allow_builtins: bool = True):
        self.root = Path(repo_root)
        self.allow_builtins = allow_builtins
        self._builtins = set(dir(__builtins__)) if allow_builtins else set()

    _cache: dict[tuple[str, str], bool] = {}

    def _grep(self, symbol: str) -> bool:
        leaf = symbol.split(".")[-1]
        key = (str(self.root), leaf)
        if key in self._cache:
            return self._cache[key]
        try:
            # one subprocess instead of two: alternation matches def OR class
            r = subprocess.run(
                ["grep", "-rIlE", "--include=*.py",
                 f"^(def|class) {leaf}\\b", str(self.root)],
                capture_output=True, text=True, timeout=10,
            )
            found = bool(r.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            found = True  # cannot check -> do not accuse; fail open
        self._cache[key] = found
        return found

    def run(self, output: str, symbols: Iterable[str] | None = None) -> list[Finding]:
        if symbols is None:
            blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", output, re.DOTALL)
            symbols = {m for b in blocks for m in self._CALL.findall(b)}
        findings = []
        for sym in symbols:
            leaf = sym.split(".")[-1]
            if leaf in self._builtins or len(leaf) < 3:
                continue
            found = self._grep(sym)
            findings.append(Finding(
                validator=self.name, claim=sym, passed=found,
                evidence="resolves in repo" if found
                         else "no def/class found in repo (possible invention)",
            ))
        return findings


class EchoValidator:
    """Repetition as a structural drift signal.

    Origin: a lived leading indicator — the earliest detectable sign of an
    auditory hallucination is often not its content but its texture: a
    slight echo, repetition where none should be. The machine analog is
    well documented: models drifting into fabrication loop phrases,
    re-assert identical claims without new evidence, and echo the prompt's
    framing back. Content varies endlessly; the echo is structural.

    Two checks:
      * internal echo  — a sentence (normalized) recurring within one output
      * stale echo     — a sentence recurring verbatim from a *previous*
                         output that validators already rejected, i.e. the
                         narrative re-asserting itself without new evidence
    """

    name = "echo"
    _SENT = re.compile(r"[^.!?\n]{20,}[.!?]")  # sentences of substance only
    _WS = re.compile(r"\s+")

    def __init__(self, rejected_history: Iterable[str] = ()):
        self.rejected: set[str] = set()
        for prior in rejected_history:
            self.rejected.update(self._normalize(s)
                                 for s in self._SENT.findall(prior))

    @classmethod
    def _normalize(cls, s: str) -> str:
        return cls._WS.sub(" ", s).strip().lower()

    def run(self, output: str) -> list[Finding]:
        findings = []
        seen: set[str] = set()
        for sent in self._SENT.findall(output):
            norm = self._normalize(sent)
            if norm in seen:
                findings.append(Finding(
                    validator=self.name, claim=sent.strip()[:80],
                    passed=False, severity="medium",
                    evidence="internal echo: sentence repeats within output",
                ))
            elif norm in self.rejected:
                findings.append(Finding(
                    validator=self.name, claim=sent.strip()[:80],
                    passed=False, severity="high",
                    evidence="stale echo: re-asserts a previously rejected "
                             "claim with no new evidence",
                ))
            seen.add(norm)
        if not findings:
            findings.append(Finding(self.name, "(whole output)", True,
                                    "no echo detected"))
        return findings




class QuoteValidator:
    """Quoted text is a provenance claim: the model asserts these exact
    words exist in its sources. That is deterministically checkable —
    every quoted span of substance must appear verbatim (whitespace-
    normalized) in the accumulated tool-result evidence. Near-quotes are
    fabrications wearing quotation marks.

    First caught in the wild: a 7B model citing three "excerpts" to
    support a claim, one of which read 'evidence about *me*' where the
    source said 'information about *me*'."""

    name = "quote"
    _QUOTED = re.compile(r'"([^"\n]{15,300})"')
    _WS = re.compile(r"\s+")

    def __init__(self, evidence_text: str = ""):
        self.evidence = self._WS.sub(" ", evidence_text)

    def run(self, output: str) -> list[Finding]:
        findings = []
        for span in set(self._QUOTED.findall(output)):
            norm = self._WS.sub(" ", span).strip()
            passed = norm in self.evidence
            findings.append(Finding(
                validator=self.name, claim=span[:80], passed=passed,
                severity="high",
                evidence=("found verbatim in tool results" if passed else
                          "quoted text does NOT appear verbatim in any "
                          "tool result this session"),
            ))
        return findings


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

class ValidatorBank:
    """Runs every registered validator over an output string. This is the
    'watch on the wrist': it observes everything, costs almost nothing,
    and its verdict does not negotiate with the narrative."""

    def __init__(self, validators: list):
        self.validators = validators

    def run(self, output: str) -> ValidationReport:
        report = ValidationReport()
        for v in self.validators:
            report.findings.extend(v.run(output))
        return report
