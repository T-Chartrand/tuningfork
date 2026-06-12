"""Grounded child agent demo — a real LLM, real tools, the overlay on.

Run from the repo root with an API key:
    ANTHROPIC_API_KEY=sk-... python3 examples/agent_demo.py

Optionally wire in any MCP server:
    python3 examples/agent_demo.py --mcp "python3 path/to/server.py"
"""
import pathlib, shlex, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tuningfork import (AnthropicLLM, ChildAgent, MCPServer,
                        builtin_fs_tools, mcp_tools)

tools = builtin_fs_tools(".")
servers = []
if "--mcp" in sys.argv:
    cmd = shlex.split(sys.argv[sys.argv.index("--mcp") + 1])
    srv = MCPServer(cmd, name="mcp")
    srv.start()
    servers.append(srv)
    tools += mcp_tools(srv)

agent = ChildAgent(AnthropicLLM(), tools)
try:
    res = agent.run("List the files in ./docs and tell me which of them "
                    "mention the word 'echo'. Cite the file paths you "
                    "actually read.")
    print("tier      :", res.tier_rationale)
    print("corrected :", res.corrected)
    print("verdict   :", "TRUSTWORTHY" if res.trustworthy else
          f"UNRESOLVED: {res.unresolved}")
    print("ledger    :", agent.ledger.profile().summary().splitlines()[0])
    print("-" * 60)
    print(res.answer)
finally:
    for s in servers:
        s.stop()
