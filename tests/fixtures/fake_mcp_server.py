"""A 30-line MCP server for tests: one tool, newline-delimited JSON-RPC."""
import json, sys

def send(o): sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line: continue
    msg = json.loads(line)
    m, i = msg.get("method"), msg.get("id")
    if m == "initialize":
        send({"jsonrpc": "2.0", "id": i, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "0"}}})
    elif m == "tools/list":
        send({"jsonrpc": "2.0", "id": i, "result": {"tools": [{
            "name": "greet", "description": "Greets a name.",
            "inputSchema": {"type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"]}}]}})
    elif m == "tools/call":
        name = msg["params"]["arguments"].get("name", "?")
        send({"jsonrpc": "2.0", "id": i, "result": {
            "content": [{"type": "text", "text": f"hello {name}"}]}})
    # notifications: no reply
