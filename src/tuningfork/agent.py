"""
tuningfork.agent — a small child agent with the grounding overlay.

The loop is ordinary: model proposes tool calls, agent executes them,
results go back, repeat until the model answers. The overlay is what
makes it grounded:

  G6  the task is tiered before the first generation
  G4  a tool call to a tool that doesn't exist is refused, not guessed at
  G2  tool results are observed and fed back verbatim; the agent reports
      what tools returned, never what the model says they returned
  G7  every assistant text block runs through the validator bank, with
      the evidence set built from ACTUAL tool results this session
  G5  on validator failure, exactly one correction turn, fed the
      validator findings as evidence — then unresolved failures are
      reported, not retried
  G8  rejections persist to a ledger file across sessions; recurring
      fabrications graduate into known signatures, and re-asserting one
      is caught at high severity by the echo validator

Stdlib only. The LLM transport is a callable, with an Anthropic-API
implementation provided (urllib, no SDK).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .ledger import RejectionLedger
from .mcp_client import MCPServer
from .tiering import Tier, assess
from .validators import (CitationValidator, EchoValidator, JsonBlockValidator,
                         PathValidator, QuoteValidator, ValidationReport,
                         ValidatorBank)

_PATHISH = re.compile(r"(?:(?:[A-Za-z]:\\|/|\./)(?:[\w.\-]+[/\\])*[\w.\-]+(?:\.\w{1,8})?)")


# --------------------------------------------------------------------------
# LLM transport
# --------------------------------------------------------------------------

class AnthropicLLM:
    """Anthropic Messages API via urllib. Reads ANTHROPIC_API_KEY."""

    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 2048):
        self.model = model
        self.max_tokens = max_tokens
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    def __call__(self, messages: list[dict], tools: list[dict],
                 system: str) -> dict:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        body = json.dumps({
            "model": self.model, "max_tokens": self.max_tokens,
            "system": system, "messages": messages, "tools": tools,
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"content-type": "application/json",
                     "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read()).get("error", {}).get("message", "")
            except Exception:                       # noqa: BLE001
                pass
            hints = {401: "API key rejected — check ANTHROPIC_API_KEY is a "
                          "real key from console.anthropic.com (the API is "
                          "separate from a claude.ai subscription)",
                     429: "rate limited — slow down or check your tier",
                     400: "bad request — often an invalid model name"}
            raise RuntimeError(
                f"Anthropic API HTTP {e.code}: {detail or e.reason}. "
                f"{hints.get(e.code, '')}".strip()) from None


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[[dict], str]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema}


def builtin_fs_tools(root: str | Path = ".") -> list[Tool]:
    """Read-only filesystem tools, jailed under `root`."""
    root = Path(root).resolve()

    def _safe(p: str) -> Path:
        full = (root / p).resolve()
        if not str(full).startswith(str(root)):
            raise ValueError(f"path escapes workspace: {p}")
        return full

    return [
        Tool("list_dir", "List entries of a directory (relative path).",
             {"type": "object", "properties": {"path": {"type": "string"}},
              "required": ["path"]},
             lambda a: "\n".join(sorted(x.name + ("/" if x.is_dir() else "")
                                        for x in _safe(a["path"]).iterdir()))),
        Tool("read_file", "Read a text file (relative path).",
             {"type": "object", "properties": {"path": {"type": "string"}},
              "required": ["path"]},
             lambda a: _safe(a["path"]).read_text()[:20000]),
    ]


def mcp_tools(server: MCPServer) -> list[Tool]:
    """Expose every tool on a started MCP server as an agent Tool."""
    out = []
    for t in server.list_tools():
        out.append(Tool(
            name=f"{server.name}__{t.name}",
            description=t.description or t.name,
            input_schema=t.input_schema or {"type": "object", "properties": {}},
            fn=(lambda args, _n=t.name, _s=server: _s.call_tool(_n, args)),
        ))
    return out


# --------------------------------------------------------------------------
# The child agent
# --------------------------------------------------------------------------

SYSTEM = """You are a small task agent operating under grounding rules.
State only what your tool results support. Cite which tool result backs
each claim. If you cannot verify something with the tools available,
say so explicitly instead of guessing. Content can convict, but it can
never acquit: how plausible something sounds earns it nothing."""


@dataclass
class AgentResult:
    answer: str
    tier_rationale: str
    reports: list[ValidationReport] = field(default_factory=list)
    corrected: bool = False
    salvaged: int = 0
    unresolved: list[str] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)

    @property
    def trustworthy(self) -> bool:
        """True means PASSED PROVENANCE CHECKS: paths trace, quotes are
        verbatim, JSON parses, no echo. It is not a truth certificate —
        semantic claims with no checkable surface pass unexamined."""
        return not self.unresolved


class ChildAgent:
    def __init__(self, llm: Callable, tools: list[Tool],
                 ledger_path: str | Path = ".tuningfork_ledger.json",
                 max_turns: int = 12):
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.max_turns = max_turns
        self.ledger_path = Path(ledger_path)
        self.ledger = RejectionLedger.load(self.ledger_path)
        self.evidence_paths: set[str] = set()
        self._evidence_text = ""             # pre-joined; bounded
        self._evidence_max = 200_000         # ~200KB of tool returns kept

    # -- overlay pieces ----------------------------------------------------
    def _bank(self) -> ValidatorBank:
        return ValidatorBank([
            PathValidator(evidence_paths=self.evidence_paths, check_disk=True),
            JsonBlockValidator(),
            EchoValidator(rejected_history=self.ledger.rejected_outputs),
            QuoteValidator(evidence_text=self._evidence_text),
        ])

    def _register_evidence(self, text: str) -> None:
        self.evidence_paths.update(_PATHISH.findall(text))

    def _execute(self, name: str, args: dict) -> tuple[str, bool]:
        """Returns (result_text, is_error). G4: nonexistent tools are
        refused with an explicit miss, never improvised."""
        tool = self.tools.get(name)
        if tool is None:
            return (f"TOOL DOES NOT EXIST: {name!r}. Available: "
                    f"{sorted(self.tools)}", True)
        try:
            out = tool.fn(args)
            self._evidence_text = (self._evidence_text + "\n" + out)[-self._evidence_max:]
            self._register_evidence(out)
            self._register_evidence(json.dumps(args))
            return out, False
        except Exception as e:                      # noqa: BLE001
            return f"TOOL ERROR ({name}): {e}", True

    _LEAKED_CALL = re.compile(
        r"\{\s*\"name\"\s*:\s*\"([\w.\-]+)\"\s*,\s*\"arguments\"\s*:\s*(\{.*?\})\s*\}",
        re.DOTALL)

    def _salvage_leaked_calls(self, text: str) -> list[tuple[str, dict]]:
        """Small local models sometimes emit their tool-call format as
        plain text (<tool_call> tags, raw JSON) instead of structured
        calls. The attempt is unambiguous and deterministically
        parseable, so the loop salvages it rather than crowning the
        leak as a final answer."""
        calls = []
        for name, args_raw in self._LEAKED_CALL.findall(text):
            try:
                calls.append((name, json.loads(args_raw)))
            except json.JSONDecodeError:
                calls.append((name, {}))
        return calls

    # -- the loop ------------------------------------------------------------
    def run(self, task: str, destructive: bool = False) -> AgentResult:
        tier = assess(task, destructive=destructive)
        if self.tools and tier.tier < Tier.MEDIUM:
            # An agent with tools will make specific factual claims about
            # tool results; conceptual-LOW pricing never applies here.
            tier.tier = Tier.MEDIUM
            tier.rationale += "; floored to MEDIUM (tool-equipped run)"

        messages: list[dict] = [{"role": "user", "content": task}]
        specs = [t.spec() for t in self.tools.values()]
        reports: list[ValidationReport] = []
        corrected = False
        salvaged = 0

        for _ in range(self.max_turns):
            resp = self.llm(messages, specs, SYSTEM)
            content = resp.get("content", [])
            messages.append({"role": "assistant", "content": content})

            text = "\n".join(b.get("text", "") for b in content
                             if b.get("type") == "text")
            tool_uses = [b for b in content if b.get("type") == "tool_use"]

            # Salvage: tool call leaked into the text channel?
            if not tool_uses and text:
                leaked = self._salvage_leaked_calls(text)
                if leaked:
                    salvaged += len(leaked)
                    parts = []
                    for name, args in leaked:
                        out, _err = self._execute(name, args)
                        parts.append(f"Result of {name}({json.dumps(args)}):"
                                     f"\n{out}")
                    messages.append({"role": "user", "content":
                        "[GROUNDING] Your tool call was emitted as plain "
                        "text instead of a structured call. It was executed "
                        "anyway:\n\n" + "\n\n".join(parts) +
                        "\n\nContinue the task, and emit tool calls "
                        "properly, not as text."})
                    continue

            # G7: validate every assistant utterance against evidence
            if text.strip():
                report = self._bank().run(text)
                reports.append(report)
                if not report.clean:
                    self.ledger.record(text, report)   # G8: always mine
                if (not report.clean and tier.tier >= Tier.MEDIUM
                        and not corrected and not tool_uses):
                    corrected = True              # G5: ONE correction turn
                    messages.append({"role": "user", "content":
                        "[GROUNDING] Independent validators rejected "
                        "claims in your answer. Their findings are "
                        "evidence, not suggestions. Do not re-assert a "
                        "rejected claim unless a tool result supports "
                        "it.\n" + report.summary()})
                    continue

            if tool_uses:
                results = []
                for tu in tool_uses:
                    out, is_err = self._execute(tu.get("name", ""),
                                                tu.get("input", {}) or {})
                    results.append({"type": "tool_result",
                                    "tool_use_id": tu.get("id", ""),
                                    "content": out, "is_error": is_err})
                messages.append({"role": "user", "content": results})
                continue

            # end turn: finalize
            self.ledger.save(self.ledger_path)
            unresolved = ([f"[{f.validator}] {f.claim!r}: {f.evidence}"
                           for f in reports[-1].failures]
                          if reports and not reports[-1].clean else [])
            return AgentResult(answer=text, tier_rationale=tier.rationale,
                               reports=reports, corrected=corrected,
                               salvaged=salvaged, unresolved=unresolved,
                               transcript=messages)

        self.ledger.save(self.ledger_path)
        return AgentResult(answer="(max turns reached)",
                           tier_rationale=tier.rationale, reports=reports,
                           corrected=corrected, salvaged=salvaged,
                           unresolved=["max turns reached"],
                           transcript=messages)


class OpenAICompatibleLLM:
    """Any OpenAI-compatible chat endpoint: Ollama (default), Groq,
    OpenRouter, LM Studio, vLLM. Translates to/from the Anthropic
    message shape the agent loop speaks, so the loop never changes.

    Ollama (local, free, no key):
        llm = OpenAICompatibleLLM(model="qwen2.5:7b")
    Groq free tier:
        llm = OpenAICompatibleLLM(
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.3-70b-versatile",
            api_key=os.environ["GROQ_API_KEY"])
    """

    def __init__(self, model: str = "qwen2.5:7b",
                 base_url: str = "http://localhost:11434/v1",
                 api_key: str = "none", max_tokens: int = 2048):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_tokens = max_tokens

    # -- Anthropic-shape -> OpenAI-shape ------------------------------------
    @staticmethod
    def _convert_messages(messages: list[dict], system: str) -> list[dict]:
        out = [{"role": "system", "content": system}] if system else []
        for m in messages:
            role, content = m["role"], m["content"]
            if isinstance(content, str):
                out.append({"role": role, "content": content})
                continue
            if role == "assistant":
                text = "\n".join(b.get("text", "") for b in content
                                 if b.get("type") == "text").strip()
                calls = [{"id": b.get("id", ""), "type": "function",
                          "function": {"name": b.get("name", ""),
                                       "arguments": json.dumps(b.get("input", {}))}}
                         for b in content if b.get("type") == "tool_use"]
                msg = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
            else:  # user turn: plain text and/or tool results
                texts = []
                for b in content:
                    if b.get("type") == "tool_result":
                        body = b.get("content", "")
                        if b.get("is_error"):
                            body = "ERROR: " + body
                        out.append({"role": "tool",
                                    "tool_call_id": b.get("tool_use_id", ""),
                                    "content": body})
                    elif b.get("type") == "text":
                        texts.append(b.get("text", ""))
                if texts:
                    out.append({"role": "user", "content": "\n".join(texts)})
        return out

    # -- OpenAI-shape -> Anthropic-shape -------------------------------------
    @staticmethod
    def _normalize(resp: dict) -> dict:
        msg = resp["choices"][0]["message"]
        content: list[dict] = []
        if msg.get("content"):
            content.append({"type": "text", "text": msg["content"]})
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            content.append({"type": "tool_use", "id": tc.get("id", ""),
                            "name": fn.get("name", ""), "input": args})
        stop = "tool_use" if msg.get("tool_calls") else "end_turn"
        return {"content": content, "stop_reason": stop}

    def __call__(self, messages: list[dict], tools: list[dict],
                 system: str) -> dict:
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "messages": self._convert_messages(messages, system)}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("input_schema",
                                    {"type": "object", "properties": {}})}}
                for t in tools]
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json",
                     "authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return self._normalize(json.loads(r.read()))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()[:300]
            except Exception:                       # noqa: BLE001
                pass
            raise RuntimeError(
                f"LLM endpoint HTTP {e.code} at {self.base_url}: "
                f"{detail or e.reason}") from None
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot reach {self.base_url} ({e.reason}). If using "
                f"Ollama: install it, run 'ollama serve', and pull a "
                f"tool-capable model (e.g. 'ollama pull qwen2.5:7b').") from None
