# tuningfork

**Grounding rules for LLM agents, derived from human reality-testing.**

Humans who must routinely distinguish real perception from convincing internal
fabrication have spent decades refining practical checks for it. Those checks
turn out to map directly onto the agent hallucination problem — often more
cleanly than the framings in the ML literature. `tuningfork` is that mapping,
written down as nine rules and shipped as a small, dependency-free Python
reference implementation.

The name comes from one of those human techniques: a physical tuning fork held
to the ear interrupts auditory hallucination through an independent channel.
It doesn't argue with the false signal — it breaks the state. That is the
design principle of this entire library.

## The core insight

> **A check terminates when the verifier sits outside the system being doubted.**

A model re-reading its own output shares its own failure modes — it can
fluently confirm its own fabrication. A grep, a parser, a checksum, an exit
code cannot. One deterministic confirmation from an independent channel is
*final*; a hundred same-model re-checks are not. Everything here follows from
that: the environment is the source of truth, and the model's memory is a
cache that may be stale.

## The nine rules

| Rule | Phase | One-liner |
|------|-------|-----------|
| **G0** Asymmetric Trust | governs all | Content can convict, but never acquit — trust flows from source-tracing only |
| **G1** Verify-Before-Assert | foresee | A claim that *could* be tool-checked *must* be, before it's stated |
| **G2** Closed-Loop Execution | recognize | Report observed results, never issued commands. Read-only observations are terminal |
| **G3** Disagreement Triangulation | recognize | Tool beats memory; one independent check on surprises; one deterministic confirmation is final |
| **G4** Negative-Space Probing | foresee | Probe for existence before relying on remembered entities; keep a catalog of known fabrication signatures |
| **G5** Reproducibility Snapshot | snap out | After a correction, rebuild state from tool output only — nothing from the broken narrative carries over |
| **G6** Cost-Tiered Budget | continuous | Tier verification by blast radius, decided *before* generation; suspiciously perfect claims get their tier raised |
| **G7** Passive Independent Validators | continuous | Cheap deterministic monitors run on everything and never ask the generator's permission |
| **G8** Source Re-attribution | after the verdict | A verified-false output is evidence about the generator — mine it; belief and action are decoupled |

Full text with rationale: [`docs/framework.md`](docs/framework.md) · The story behind it: [`docs/essay.md`](docs/essay.md)

## Quick start

```bash
pip install -e .
```

```python
from tuningfork import (GroundedAgent, ValidatorBank,
                        CitationValidator, PathValidator, JsonBlockValidator)

bank = ValidatorBank([
    CitationValidator(valid_source_ids=["1", "2", "3"]),
    PathValidator(evidence_paths=tool_returned_paths),
    JsonBlockValidator(),
])

agent = GroundedAgent(generate=my_llm_callable, bank=bank)
result = agent.run("Summarize sources [1]-[3] and list the config files involved.")

print(result.tier.rationale)      # how the claim was priced before generation
print(result.report.summary())    # what the independent channels observed
print(result.trustworthy)         # validators' verdict, not the model's
```

The harness permits exactly **one** regeneration pass on validator failure —
fed the validator evidence, not an apology prompt. A second failure is
reported as unresolved, because retrying the same channel is re-checking the
check.

## The child agent

`v0.3.0` adds a small runnable agent with the overlay on: an ordinary
tool loop (Anthropic Messages API via stdlib urllib — no SDK) where
every assistant utterance is validated against evidence built from the
tools' ACTUAL returns, nonexistent tool calls are refused instead of
improvised, one evidence-fed correction turn is permitted, and
rejections persist to a ledger file across sessions — the catalog of
known fabrications accumulates instead of resetting.

```python
from tuningfork import AnthropicLLM, ChildAgent, builtin_fs_tools

agent = ChildAgent(AnthropicLLM(), builtin_fs_tools("."))
result = agent.run("Which files in ./docs mention 'echo'? Cite paths.")
print(result.trustworthy, result.answer)
```

MCP servers wire in as first-class tools via a minimal stdlib client
(newline-delimited JSON-RPC over stdio):

```python
from tuningfork import MCPServer, mcp_tools

srv = MCPServer(["python3", "my_server.py"], name="files")
srv.start()
agent = ChildAgent(AnthropicLLM(), mcp_tools(srv))
```

See `examples/agent_demo.py` for the runnable version.

## What this is not

- Not a wrapper that makes a model "more honest." The model is unchanged.
- Not an eval suite. It's a runtime harness.
- Not novel components — verify-then-assert, closed-loop execution, and
  output guardrails all exist in prior work (Chain-of-Verification,
  SelfCheckGPT, ReAct/Reflexion, guardrails frameworks). What's new here is
  the unifying frame and the termination principle, which most frameworks
  lack: they either never verify or can't stop.

## Status

`v0.2.0` — reference implementation, full test suite passing, stdlib only. Includes EchoValidator (repetition as a structural leading indicator) and RejectionLedger (the G4 catalog accumulates from mined rejections).
Roadmap: coverage validator (evidence the response *ignored*), async
validator bank, adapters for popular agent frameworks.

## License

MIT
