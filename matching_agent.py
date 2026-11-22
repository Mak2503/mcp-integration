"""LangGraph resume matcher backed by the filesystem MCP server.

Start with ``python matching_agent.py`` after setting ``RESUME_MCP_ROOT`` and
``OPENROUTER_API_KEY`` is not required; matching is deterministic and local.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import unquote

try:
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:  # pragma: no cover
    raise ImportError("LangGraph is required: install langgraph to run the agent") from exc

SERVER = Path(__file__).with_name("filesystem_mcp_server.py")
SKILLS = ["react", "javascript", "typescript", "node.js", "python", "java", "go", "ruby", "django", "fastapi", "flask", "langchain", "langgraph", "llm", "aws", "azure", "gcp", "docker", "kubernetes", "sql", "postgresql", "mongodb", "redis", "graphql", "rest", "html", "css", "next.js", "machine learning", "data analysis", "leadership", "communication", "product management", "git"]


class MCPClient:
    """Minimal synchronous stdio client for the MCP JSON-RPC transport."""
    def __init__(self, root: str | None = None):
        env = os.environ.copy()
        if root:
            env["RESUME_MCP_ROOT"] = root
        self.process = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, env=env)
        self.seq = 0
        self.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "matching-agent", "version": "1.0.0"}})
        self.notify("notifications/initialized")

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.seq += 1
        request = {"jsonrpc": "2.0", "id": self.seq, "method": method, "params": params or {}}
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        if "error" in response:
            raise RuntimeError(response["error"].get("message", "MCP request failed"))
        return response.get("result", {})

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.process.stdin
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
        self.process.stdin.flush()

    def call_tool(self, name: str, **arguments: Any) -> Any:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(result.get("content", [{}])[0].get("text", "MCP tool failed"))
        return result.get("structuredContent")

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.terminate()
        self.process.wait(timeout=3)


class State(TypedDict, total=False):
    message: str
    requirements: dict[str, Any]
    candidates: list[dict[str, Any]]
    report: str
    resources: list[dict[str, Any]]
    errors: list[str]


def extract_requirements(text: str) -> dict[str, Any]:
    lower = text.lower()
    year = re.search(r"(?:at least|minimum of|min\.?|\+)?\s*(\d+(?:\.\d+)?)\s*\+?\s*years?", lower)
    found = [skill for skill in SKILLS if re.search(r"(?<![\w])" + re.escape(skill) + r"(?![\w])", lower)]
    return {"must_have": found, "nice_to_have": [], "min_years": float(year.group(1)) if year else 0.0, "raw_jd": text}


def _skill(skill: str, text: str) -> bool:
    return bool(re.search(r"(?<![\w])" + re.escape(skill) + r"(?![\w])", text, re.I))


class MatchingAgent:
    def __init__(self, client: MCPClient | None = None, top_k: int = 10):
        self.client = client or MCPClient()
        self.top_k = top_k
        self.candidates: list[dict[str, Any]] = []
        self.shortlist: list[dict[str, Any]] = []
        graph = StateGraph(State)
        graph.add_node("discover", self._discover)
        graph.add_node("load", self._load)
        graph.add_node("rank", self._rank)
        graph.add_edge(START, "discover")
        graph.add_edge("discover", "load")
        graph.add_edge("load", "rank")
        graph.add_edge("rank", END)
        self.graph = graph.compile()

    def _discover(self, state: State) -> dict[str, Any]:
        requirements = extract_requirements(state["message"])
        resources = self.client.request("resources/list").get("resources", [])
        return {"requirements": requirements, "resources": resources}

    def _load(self, state: State) -> dict[str, Any]:
        resources = state.get("resources", [])
        paths = [unquote(item["uri"].removeprefix("file://")) for item in resources]
        try:
            batch = self.client.call_tool("batch_process", filepaths=paths)
        except Exception as exc:
            return {"candidates": [], "errors": [f"MCP batch read failed: {exc}"]}
        candidates = []
        for row in batch.get("results", []):
            if row.get("success") and row.get("content", "").strip():
                path = Path(row["filepath"])
                candidates.append({"id": path.stem, "name": path.stem.replace("_", " "), "text": row["content"]})
        return {"candidates": candidates, "errors": []}

    def _rank(self, state: State) -> dict[str, Any]:
        req, output = state.get("requirements", {}), []
        must, years_needed = req.get("must_have", []), req.get("min_years", 0)
        for candidate in state.get("candidates", []):
            text = candidate["text"]
            matched = [skill for skill in must if _skill(skill, text)]
            years = [float(y) for y in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", text, re.I)]
            actual_years = max(years, default=0)
            exp_ok = not years_needed or actual_years >= years_needed
            total = max(len(must) + (1 if years_needed else 0), 1)
            candidate.update({"score": round(100 * (len(matched) + (1 if years_needed and exp_ok else 0)) / total, 1), "strengths": matched, "gaps": [f"Missing {skill}" for skill in must if skill not in matched], "rationale": f"Matched {len(matched)}/{len(must)} required skills" + (f"; {'met' if exp_ok else 'did not meet'} {years_needed:g}+ years" if years_needed else "")})
            if years_needed and not exp_ok:
                candidate["gaps"].append(f"Below {years_needed:g}-year experience target (resume states {actual_years:g})")
            candidate["recommendation"] = "Advance to interview" if candidate["score"] >= 70 and not candidate["gaps"] else "Hold for targeted screening" if candidate["score"] >= 50 else "Do not advance based on available resume evidence"
            output.append(candidate)
        output.sort(key=lambda c: (-c["score"], c["name"].lower()))
        selected = output[:self.top_k]
        if not selected:
            root = Path(os.environ.get("RESUME_MCP_ROOT", "data/resumes")).expanduser().resolve()
            report = f"No resumes were found in the configured MCP root ({root}). Create or populate that folder with PDF, DOCX, or TXT resumes, or set RESUME_MCP_ROOT to your resume folder."
        else:
            lines = [f"Match report — {len(selected)} candidate(s)", f"Must-have: {', '.join(must) or 'not specified'}"]
            if years_needed:
                lines.append(f"Experience target: {years_needed:g}+ years")
            for i, c in enumerate(selected, 1):
                lines.extend([f"\n{i}. {c['name']} — {c['score']:.1f}%", f"   Why: {c['rationale']}", f"   Strengths: {', '.join(c['strengths']) or 'No clear evidence found'}", f"   Gaps: {', '.join(c['gaps']) or 'No listed gaps'}", f"   Recommendation: {c['recommendation']}"])
            report = "\n".join(lines)
        return {"candidates": output, "report": report}

    def respond(self, message: str) -> str:
        lower = message.lower()
        if self.shortlist and ("compare" in lower or "side by side" in lower):
            lines = ["Candidate comparison:"]
            for item in self.shortlist[:3]:
                lines.append(f"- {item['name']}: {item['score']:.1f}% match; strengths: {', '.join(item['strengths']) or 'none identified'}; gaps: {', '.join(item['gaps']) or 'none identified'}.")
            return "\n".join(lines)
        if self.shortlist and ("interview question" in lower or "screening question" in lower):
            candidate = next((c for c in self.shortlist if c["id"].lower() in lower or c["name"].lower() in lower), self.shortlist[0])
            skills = candidate.get("strengths") or ["the role's core skills"]
            return "Suggested screening questions for " + candidate["name"] + ":\n" + "\n".join(f"{i}. Describe a project where you used {skill}. What was your contribution and the outcome?" for i, skill in enumerate(skills[:3], 1))
        if self.shortlist and "why" in lower and ("rank" in lower or "higher" in lower):
            candidates = self.shortlist[:2]
            return f"{candidates[0]['name']} ranked at {candidates[0]['score']:.1f}% because {candidates[0]['rationale']} {candidates[1]['name']} scored {candidates[1]['score']:.1f}% because {candidates[1]['rationale']}" if len(candidates) > 1 else "Only one candidate is available to explain."
        if self.shortlist and re.search(r"\b(?:only|at least|minimum|prefer|prioritize|require|exclude|without|add|focus on|with)\b", lower):
            previous = self.shortlist
            new_req = extract_requirements(message)
            current_req = self.graph.invoke({"message": message}).get("requirements", {})
            current_req["must_have"] = list(dict.fromkeys(new_req["must_have"] + current_req.get("must_have", [])))
            current_req["min_years"] = max(new_req["min_years"], current_req.get("min_years", 0))
            # Re-rank the existing MCP-loaded records against accumulated criteria.
            self.candidates = self._score_records(self.candidates or previous, current_req)
            self.shortlist = self.candidates[:self.top_k]
            changes = []
            before = {c["id"]: index + 1 for index, c in enumerate(previous)}
            for index, c in enumerate(self.shortlist, 1):
                if c["id"] in before and before[c["id"]] != index:
                    changes.append(f"{c['name']}: #{before[c['id']]} → #{index}")
            return self._format(self.shortlist, current_req) + "\n\nRanking changes: " + ("; ".join(changes) if changes else "No rank positions changed.")
        state = self.graph.invoke({"message": message})
        self.candidates = state.get("candidates", [])
        self.shortlist = self.candidates[:self.top_k]
        return state["report"]

    @staticmethod
    def _score_records(records: list[dict[str, Any]], req: dict[str, Any]) -> list[dict[str, Any]]:
        output = []
        for original in records:
            c = dict(original)
            text, must, required = c["text"], req.get("must_have", []), req.get("min_years", 0)
            matched = [skill for skill in must if _skill(skill, text)]
            years = [float(y) for y in re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", text, re.I)]
            actual = max(years, default=0)
            exp_ok = not required or actual >= required
            total = max(len(must) + bool(required), 1)
            c.update({"score": round(100 * (len(matched) + (bool(required) and exp_ok)) / total, 1), "strengths": matched, "gaps": [f"Missing {s}" for s in must if s not in matched], "rationale": f"Matched {len(matched)}/{len(must)} required skills" + (f"; {'met' if exp_ok else 'did not meet'} {required:g}+ years" if required else "")})
            if required and not exp_ok:
                c["gaps"].append(f"Below {required:g}-year experience target (resume states {actual:g})")
            c["recommendation"] = "Advance to interview" if c["score"] >= 70 and not c["gaps"] else "Hold for targeted screening" if c["score"] >= 50 else "Do not advance based on available resume evidence"
            output.append(c)
        return sorted(output, key=lambda c: (-c["score"], c["name"].lower()))

    @staticmethod
    def _format(candidates: list[dict[str, Any]], req: dict[str, Any]) -> str:
        lines = [f"Match report — {len(candidates)} candidate(s)", f"Must-have: {', '.join(req.get('must_have', [])) or 'not specified'}"]
        if req.get("min_years"):
            lines.append(f"Experience target: {req['min_years']:g}+ years")
        for i, c in enumerate(candidates, 1):
            lines.append(f"\n{i}. {c['name']} — {c['score']:.1f}%\n   Why: {c['rationale']}\n   Strengths: {', '.join(c['strengths']) or 'No clear evidence found'}\n   Gaps: {', '.join(c['gaps']) or 'No listed gaps'}")
        return "\n".join(lines)


def main() -> None:
    agent = MatchingAgent()
    try:
        print("Resume matcher ready. Describe a role (or type quit).")
        while True:
            try:
                message = input("You: ").strip()
            except EOFError:
                break
            if message.lower() in {"quit", "exit"}:
                break
            if message:
                print("\n" + agent.respond(message) + "\n")
    finally:
        agent.client.close()


if __name__ == "__main__":
    main()
