"""Child-agent tests: the overlay catching a live(-shaped) fabricator,
G4 tool-existence refusal, MCP round trip, ledger persistence."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tuningfork import (ChildAgent, MCPServer, Tool, builtin_fs_tools,
                        mcp_tools)

FIX = pathlib.Path(__file__).parent / "fixtures"


def scripted_llm(turns):
    """LLM double: yields scripted responses in order."""
    it = iter(turns)
    def call(messages, tools, system):
        return next(it)
    return call


def text(t): return {"type": "text", "text": t}
def tooluse(name, args, i="t1"):
    return {"type": "tool_use", "id": i, "name": name, "input": args}


def test_agent_catches_fabricated_path_and_corrects(tmp_path):
    (tmp_path / "real.txt").write_text("contents")
    llm = scripted_llm([
        # turn 1: fabricates a path that no tool ever returned
        {"content": [text("The config is at /opt/secret/made_up.yaml.")]},
        # turn 2 (after grounding correction): uses tools properly
        {"content": [tooluse("list_dir", {"path": "."})]},
        # turn 3: grounded answer referencing the real file
        {"content": [text(f"The directory contains real.txt at {tmp_path}/real.txt.")]},
    ])
    agent = ChildAgent(llm, builtin_fs_tools(tmp_path),
                       ledger_path=tmp_path / "ledger.json")
    res = agent.run("Where is the config? v1.0")   # catalog hit -> MEDIUM
    assert res.corrected is True                    # one correction turn fired
    assert res.trustworthy                          # final answer validated
    assert "real.txt" in res.answer
    # G8: the fabrication was mined into the persistent ledger
    led = json.loads((tmp_path / "ledger.json").read_text())
    assert any("made_up.yaml" in c for c in led["claims"])


def test_agent_refuses_nonexistent_tool(tmp_path):
    llm = scripted_llm([
        {"content": [tooluse("delete_everything", {})]},
        {"content": [text("That tool does not exist; I cannot do that.")]},
    ])
    agent = ChildAgent(llm, builtin_fs_tools(tmp_path),
                       ledger_path=tmp_path / "ledger.json")
    res = agent.run("clean up")
    # the refusal travelled back as an is_error tool_result
    tool_results = [b for m in res.transcript if isinstance(m["content"], list)
                    for b in m["content"] if isinstance(b, dict)
                    and b.get("type") == "tool_result"]
    assert tool_results and tool_results[0]["is_error"] is True
    assert "DOES NOT EXIST" in tool_results[0]["content"]


def test_mcp_round_trip():
    srv = MCPServer([sys.executable, str(FIX / "fake_mcp_server.py")], name="fake")
    srv.start()
    try:
        tools = mcp_tools(srv)
        assert tools[0].name == "fake__greet"
        assert tools[0].fn({"name": "tyrrell"}) == "hello tyrrell"
    finally:
        srv.stop()


def test_ledger_persists_across_agent_instances(tmp_path):
    llm1 = scripted_llm([
        {"content": [text("See /fake/path/one.txt for details.")]},
        {"content": [text("I could not verify that path.")]},
    ])
    a1 = ChildAgent(llm1, [], ledger_path=tmp_path / "l.json")
    a1.run("where? v2.0")
    # fresh instance loads the prior session's rejections (the library)
    a2 = ChildAgent(scripted_llm([]), [], ledger_path=tmp_path / "l.json")
    assert any("one.txt" in r for r in a2.ledger.rejected_outputs)


def test_anthropic_llm_surfaces_api_errors_readably(monkeypatch):
    import io, urllib.error, urllib.request
    from tuningfork import AnthropicLLM

    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {},
            io.BytesIO(b'{"error":{"message":"invalid x-api-key"}}'))
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    llm = AnthropicLLM(); llm.api_key = "sk-ant-placeholder"
    try:
        llm([], [], "")
        assert False, "should have raised"
    except RuntimeError as e:
        msg = str(e)
        assert "401" in msg and "invalid x-api-key" in msg
        assert "console.anthropic.com" in msg     # the hint travels


def test_openai_compat_message_and_response_translation():
    from tuningfork import OpenAICompatibleLLM as L
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "checking"},
            {"type": "tool_use", "id": "c1", "name": "read_file",
             "input": {"path": "a.txt"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1",
             "content": "file body", "is_error": False}]},
    ]
    conv = L._convert_messages(msgs, system="be good")
    assert conv[0] == {"role": "system", "content": "be good"}
    assert conv[2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert conv[3] == {"role": "tool", "tool_call_id": "c1",
                       "content": "file body"}
    norm = L._normalize({"choices": [{"message": {
        "content": None,
        "tool_calls": [{"id": "x", "function": {
            "name": "list_dir", "arguments": "{\"path\": \".\"}"}}]}}]})
    assert norm["content"][0] == {"type": "tool_use", "id": "x",
                                  "name": "list_dir", "input": {"path": "."}}
    assert norm["stop_reason"] == "tool_use"


def test_tool_equipped_run_floors_tier_and_always_mines(tmp_path):
    # Task text matches no catalog signature -> would price LOW; with tools
    # it must floor to MEDIUM, the correction turn must arm, and the
    # rejection must reach the ledger.
    llm = scripted_llm([
        {"content": [text("The notes live in /nowhere/fabricated_notes.txt.")]},
        {"content": [text("I cannot verify that file with my tools.")]},
    ])
    agent = ChildAgent(llm, builtin_fs_tools(tmp_path),
                       ledger_path=tmp_path / "l.json")
    res = agent.run("where are the notes")          # no catalog hits
    assert "MEDIUM" in res.tier_rationale and "floored" in res.tier_rationale
    assert res.corrected is True
    assert agent.ledger.profile().total_rejections >= 1


def test_unresolved_surfaces_the_failing_claim(tmp_path):
    llm = scripted_llm([
        {"content": [text("See /nowhere/ghost.txt for details. v3.1")]},
        {"content": [text("Still: /nowhere/ghost.txt has it. v3.1")]},
    ])
    agent = ChildAgent(llm, [], ledger_path=tmp_path / "l.json")
    res = agent.run("where v3.1")
    assert res.unresolved
    assert "ghost.txt" in res.unresolved[0]         # the claim is visible
    assert "[path]" in res.unresolved[0]            # and which validator


def test_quote_validator_catches_near_quote(tmp_path):
    (tmp_path / "essay.txt").write_text(
        "the voices become information about me: a version of myself "
        "speaking from a different direction.")
    llm = scripted_llm([
        {"content": [tooluse("read_file", {"path": "essay.txt"})]},
        {"content": [text('The file says "the voices become evidence about '
                          'me: a version of myself" on line 3.')]},
        {"content": [text('Correction: the file says "information about me: '
                          'a version of myself speaking" verbatim.')]},
    ])
    agent = ChildAgent(llm, builtin_fs_tools(tmp_path),
                       ledger_path=tmp_path / "l.json")
    res = agent.run("what does the essay say")
    assert res.corrected is True              # near-quote caught, turn fired
    assert res.trustworthy                    # verbatim re-quote passes
    assert agent.ledger.profile().rejections_by_validator.get("quote") == 1


def test_leaked_text_tool_call_is_salvaged_not_crowned(tmp_path):
    (tmp_path / "real.txt").write_text("hello")
    leak = ('brtc\n{"name": "list_dir", "arguments": {"path": "."}}\n'
            "</tool_call>")
    llm = scripted_llm([
        {"content": [text(leak)]},                       # the leak
        {"content": [text(f"The directory contains real.txt "
                          f"({tmp_path}/real.txt).")]},  # proper finish
    ])
    agent = ChildAgent(llm, builtin_fs_tools(tmp_path),
                       ledger_path=tmp_path / "l.json")
    res = agent.run("list the files")
    assert res.salvaged == 1
    assert "real.txt" in res.answer          # the leak never became the answer
    assert res.trustworthy
    # the salvaged execution's result travelled back as user content
    assert any(isinstance(m["content"], str) and "Result of list_dir" in m["content"]
               for m in res.transcript if m["role"] == "user")


def test_evidence_text_is_bounded_not_quadratic(tmp_path):
    """Before this fix, evidence_text was a list joined on every validator
    call — O(n^2) over a long-running session. Cap is now declarative."""
    big = "X" * 50_000
    (tmp_path / "a.txt").write_text(big)
    llm = scripted_llm([
        {"content": [tooluse("read_file", {"path": "a.txt"}, i="t1")]},
        {"content": [tooluse("read_file", {"path": "a.txt"}, i="t2")]},
        {"content": [tooluse("read_file", {"path": "a.txt"}, i="t3")]},
        {"content": [tooluse("read_file", {"path": "a.txt"}, i="t4")]},
        {"content": [tooluse("read_file", {"path": "a.txt"}, i="t5")]},
        {"content": [text("done")]},
    ])
    agent = ChildAgent(llm, builtin_fs_tools(tmp_path),
                       ledger_path=tmp_path / "l.json")
    agent._evidence_max = 60_000              # bound for the test
    agent.run("read it many times")
    assert isinstance(agent._evidence_text, str)
    assert len(agent._evidence_text) <= agent._evidence_max + 100
