"""Small MCP stdio client used by the recorded demo video."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

SERVER = Path(__file__).with_name("filesystem_mcp_server.py")


class StdioMCPDemo:
    def __init__(self) -> None:
        env = os.environ.copy()
        env.setdefault("RESUME_MCP_ROOT", str(Path(__file__).parent / "data" / "resumes"))
        self.proc = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, env=env)
        self.request_id = 0

    def send(self, method: str, params: dict | None = None, notification: bool = False) -> dict:
        assert self.proc.stdin and self.proc.stdout
        request: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request["params"] = params
        if not notification:
            self.request_id += 1
            request["id"] = self.request_id
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        if notification:
            return {}
        response = json.loads(self.proc.stdout.readline())
        if "error" in response:
            raise RuntimeError(response["error"])
        return response.get("result", {})

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=3)


def main() -> None:
    client = StdioMCPDemo()
    try:
        print("1. MCP initialize")
        initialized = client.send("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "recorded-demo", "version": "1.0"}})
        print(json.dumps(initialized, indent=2))
        client.send("notifications/initialized", notification=True)

        print("\n2. Resource discovery")
        resources = client.send("resources/list").get("resources", [])
        print(f"Discovered {len(resources)} resume resource(s):")
        for resource in resources[:5]:
            print(f"- {resource['name']} ({resource['uri']})")
        if len(resources) > 5:
            print(f"- ... and {len(resources) - 5} more")

        print("\n3. Tool discovery")
        tools = client.send("tools/list").get("tools", [])
        print("Available tools: " + ", ".join(tool["name"] for tool in tools))

        print("\n4. MCP batch_process tool call")
        paths = [unquote(item["uri"].removeprefix("file://")) for item in resources[:3]]
        batch = client.send("tools/call", {"name": "batch_process", "arguments": {"filepaths": paths}}).get("structuredContent", {})
        print(json.dumps({"processed": batch.get("processed"), "succeeded": batch.get("succeeded"), "failed": batch.get("failed"), "files": [{"filepath": row.get("filepath"), "success": row.get("success"), "word_count": row.get("metadata", {}).get("word_count"), "error": row.get("error")} for row in batch.get("results", [])]}, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    main()
