# The Tuningfork Grounding Framework

Nine rules for grounding LLM agents against hallucination, derived from
human reality-testing practice. The reference implementation lives in
`src/tuningfork/`; the story behind the framework is in
[`essay.md`](essay.md).

## Operating principle

**The environment is the source of truth; the model's memory is a cache
that may be stale.** Every rule below is enforcement detail for that one
invariant.

> A check terminates when the verifier sits outside the system being
> doubted.

A model re-reading its own output shares its own failure modes — it can
fluently confirm its own fabrication. A grep, a parser, a checksum, an
exit code cannot. From this, the termination rules that govern all
checking:

- **Termination by independent channel:** a check is finished when
  confirmed by a verifier that cannot share the generator's failure
  mode — code execution, parser, checksum, existence grep, schema
  validation. One such confirmation is final. Re-review by the same
  model is NOT terminal; it is re-checking the check.
- **Fallback cap:** where no independent channel exists, at most ONE
  regeneration pass; if the regenerated draft still fails, the specific
  limitation is reported instead of regenerating again.
- **Precedence on conflict:** safety > accuracy/verification >
  verification budget (G6) > style. Where two rules mandate different
  amounts of verification work, the budget decides the *amount*; the
  stricter rule decides only *whether* verification occurs.

## Grounding Rules (G0–G8)

### G0 — Asymmetric Trust (governs all checking)
**Content can convict, but it can never acquit.** Coherence, fluency, and
plausibility are what fabrication is optimized for — the more embedded in
truth a false claim is, the more dangerous, because believability is the
attack surface, not a safety signal. Therefore:
- A claim is **trusted only by source**: it traces to a tool result, a
  document in context, or a deterministic computation. Nothing else grants
  trust — not how sensible it sounds, not how well it fits.
- Content checks run **one-directional**: an implausible or too-perfect
  claim may be flagged and escalated, but a plausible one earns nothing.
- Validator ordering follows: provenance checks (source-tracing) always run;
  plausibility heuristics only ever *raise* tiers (G6), never lower them.
Verification without validation is dangerous: locating *a* source is not
enough — the source must actually have produced the claim attributed to it.

A correction from the user, or a detected internal inconsistency, is treated as a hallucination signal. The following rules apply continuously. These rules are fixed; amendments occur only by explicit user instruction, never by agent self-modification.

### G1 — Verify-Before-Assert (foresee)
Any medium- or high-stakes claim (per G6) that can be checked by an available tool must be checked before it is stated. File contents are read, not recalled; current versions/prices/statuses are searched, not remembered. Memory is a hypothesis; tools are evidence. An unverified-but-verifiable medium/high-stakes claim is a violation even if it turns out correct. *(Low-stakes claims are exempt per G6 — this rule does not override the budget.)*

### G2 — Closed-Loop Execution (recognize)
Every **state-changing** action is followed by an observation confirming its effect: write a file → confirm it; run a command → check exit code and output; call an API → validate the response schema.
**Base case:** read-only observations are terminal and require no further confirmation.
**Large-artifact clause:** for files above ~1 MB or ~5,000 lines, confirmation may use checksum, size, or line count instead of a full read-back.
Success is reported only on observed results, never on issued commands.

### G3 — Disagreement Triangulation (recognize)
When a tool result contradicts internal expectation, the tool wins by default. A single surprising result triggers exactly **one** independent check via a different method — and "independent" means a channel that cannot share the first source's failure mode (different API, direct file inspection, deterministic computation), not the same source queried twice.
**Termination:** one deterministic confirmation is final. If the two checks still conflict, stop checking, report the conflict to the user as unresolved, and proceed only with what both sources agree on.

### G4 — Negative-Space Probing (foresee)
Before relying on a remembered entity — function, API endpoint, config key, CLI flag — probe for its existence first (`--help`, schema introspection, grep, docs search). An existence check counts as the one verification required by G6's medium tier; it does not stack an additional check on top.
**Known-signature catalog:** maintain a list of recognized hallucination signatures (invented flags, citations to nonexistent papers, confidently stated version numbers, APIs with exactly the needed method). A catalog match auto-triggers the existence probe without further deliberation — recognition is cheaper than analysis.

### G5 — Reproducibility Snapshot (snap out)
After a correction **about facts or system state** (not style, phrasing, or preference), rebuild only the working state that the correction invalidates, from tool output: re-read the affected files, re-run the affected command, and write a short verified-state summary citing each tool result. Nothing from the pre-correction narrative about the invalidated state carries over unless it reappears in fresh evidence.
**Scope:** rebuild depth follows the G6 tier of the corrected claim.
**Single-snapshot rule:** one snapshot per correction event. New inconsistencies surfaced during a rebuild are flagged to the user, not re-snapshotted.
*(This is the tool-based counterpart of the draft self-check in the termination rules above: instead of re-reading the draft, it regenerates state from the environment.)*

### G6 — Cost-Tiered Verification Budget (continuous)
Claims are tiered by blast radius, decided **before** generation:
- **Low** — conceptual explanation, general knowledge: no tool call.
- **Medium** — specific facts, code that will be run, named entities: one verification (G1/G4).
- **High** — destructive operations, output the user will act on externally, legal/financial/system-critical content: verification **plus** G2 closed-loop confirmation.
The tier may not be downgraded retroactively. G6 sets the ceiling on verification work for every other rule, including G5 rebuilds.
**Convenience penalty (too-perfect test):** when a remembered claim is exactly maximally convenient for the current task — the recalled API has precisely the needed method, the remembered fact supports the argument exactly, every piece fits with no loose ends — raise its tier one level (capped at High). The same applies to claims structured so they cannot be tested: convenient unverifiability is itself a flag. Real evidence is usually messier than fabricated evidence; suspicious perfection is a hallucination signal, not a reason for confidence.

### G7 — Passive Independent Validators (continuous monitor)
Alongside generation, run cheap deterministic validators on an independent channel — checks that observe the agent's output but cannot share its failure modes:
- every citation index references a source that exists in context;
- every file path mentioned appeared in a prior tool result;
- generated JSON/YAML parses; generated code passes lint/compile;
- every referenced function, flag, or endpoint resolves against the actual codebase or schema;
- **no echo**: no sentence repeats within an output, and no previously rejected claim is re-asserted without new evidence. Repetition is a structural drift signature — fabrication's content varies endlessly, but its texture (looping, re-assertion, echoing the prompt back) is detectable and cheap to catch. It is also a *leading* indicator: echo often appears before outright fabrication does.
Validators report binary facts only and do not ask the generation process for permission to run. They are deterministic and low-cost, so they run at **every** tier, including Low — they sit below the G6 budget rather than inside it.
A validator miss is treated as a hallucination signal: it auto-triggers G4 (existence probe) at Medium tier or G5 (snapshot rebuild) at High tier. The monitor that matters is the one outside the narrative — the generator cannot be trusted to notice its own drift from within it.

### G8 — Source Re-attribution (after the verdict)
A verified-false output is not discarded as noise. It is **re-attributed**:
its claims stop being evidence about the world and become evidence about
the generator — its priors, its biases, the direction of its drift. Then
it is **mined**:
- Rejected outputs accumulate in a ledger across the session.
- Recurring fabrications graduate into known signatures. The G4 catalog is
  therefore *accumulated from processed rejections*, not hand-written —
  each verified-false experience, mined instead of merely dismissed,
  becomes recognizable the next time.
- The ledger feeds echo detection: re-asserting a mined fabrication
  without new evidence is caught at high severity.

The principle underneath: **belief and action are decoupled.** The system
never requires the generator to stop producing the false signal — it
cannot; re-queried, the model will fluently re-assert. It requires only
that actions trace to verified sources. The generator's internal
conviction is not load-bearing. Rejected content updates the model of the
model; it never updates the world model.
