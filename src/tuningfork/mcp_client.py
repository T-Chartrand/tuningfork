"""
tuningfork.mcp_client — a minimal MCP (Model Context Protocol) client.

Speaks the stdio transport: newline-delimited JSON-RPC 2.0 to a server
subprocess. Supports the three calls a grounded agent needs:
initialize, tools/list, tools/call.

Stdlib only. Deliberately small — this is a reference client for wiring
MCP tools into a grounded agent loop, not a full SDK.
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass


class MCPError(RuntimeError):
    pass


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict


class MCPServer:
    """One MCP server subprocess. Usage:

        srv = MCPServer(["python", "my_server.py"])
        srv.start()
        tools = srv.list_tools()
        result_text = srv.call_tool("read_file", {"path": "x.txt"})
        srv.stop()
    """

    def __init__(self, command: list[str], name: str = "mcp"):
        self.command = command
        self.name = name
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()

    # -- transport ---------------------------------------------------------
    def _send(self, payload: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def _recv_response(self, want_id: int) -> dict:
        assert self.proc and self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise MCPError(f"{self.name}: server closed the pipe")
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("id") == want_id:
                if "error" in msg:
                    raise MCPError(f"{self.name}: {msg['error']}")
                return msg.get("result", {})
            # notifications / unrelated ids are skipped

    def _request(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            self._id += 1
            rid = self._id
            self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                        "params": params or {}})
            return self._recv_response(rid)

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "tuningfork-agent", "version": "0.3.0"},
        })
        self._send({"jsonrpc": "2.0",
                    "method": "notifications/initialized", "params": {}})

    def stop(self) -> None:
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            self.proc = None

    # -- the three calls ---------------------------------------------------
    def list_tools(self) -> list[MCPTool]:
        result = self._request("tools/list")
        return [MCPTool(t["name"], t.get("description", ""),
                        t.get("inputSchema", {}))
                for t in result.get("tools", [])]

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._request("tools/call",
                               {"name": name, "arguments": arguments})
        parts = []
        for block in result.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        if result.get("isError"):
            raise MCPError(f"{self.name}.{name}: " + "\n".join(parts))
        return "\n".join(parts)
