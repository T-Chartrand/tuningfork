"""Demo: a deliberately unreliable generator caught by independent channels.

Run:  python3 examples/demo.py
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tuningfork import (CitationValidator, GroundedAgent, JsonBlockValidator,
                        PathValidator, ValidatorBank, assess)

# --- A fake LLM that fabricates on the first call, behaves on the second ---
state = {"calls": 0}

def flaky_llm(prompt: str) -> str:
    state["calls"] += 1
    if state["calls"] == 1:
        return ("Per [2] and [9], the settings live in /opt/app/secret_config.yaml.\n"
                "```json\n{\"mode\": \"auto\",}\n```")
    return ("Per [2], the settings live in /opt/app/config.yaml.\n"
            "```json\n{\"mode\": \"auto\"}\n```")

# --- Evidence the agent actually has (from prior tool calls) ---
sources_in_context = ["1", "2"]
paths_from_tools = ["/opt/app/config.yaml"]

bank = ValidatorBank([
    CitationValidator(valid_source_ids=sources_in_context),
    PathValidator(evidence_paths=paths_from_tools, check_disk=False),
    JsonBlockValidator(),
])

agent = GroundedAgent(flaky_llm, bank)
result = agent.run("Where do the settings live? Cite sources. v1.0 config")

print("tier decision :", result.tier.rationale)
print("regenerated   :", result.regenerated)
print("verdict       :", "TRUSTWORTHY" if result.trustworthy else "REJECTED")
print("final output  :", result.output.splitlines()[0])
print("llm calls     :", state["calls"], "(cap: 2)")
