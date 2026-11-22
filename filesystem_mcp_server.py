"""A small stdio MCP server for the resume file system.

Run with ``python filesystem_mcp_server.py``. MCP messages are JSON-RPC 2.0
objects, one per line. Set ``RESUME_MCP_ROOT`` to limit file access to a folder.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx"}
PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "filesystem-resumes"
ROOT = Path(os.environ.get("RESUME_MCP_ROOT", "data/resumes")).expanduser().resolve()


def _safe_path(value: str) -> Path:
    path = Path(value).expanduser()
    path = (ROOT / path if not path.is_absolute() else path).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"Path must be inside configured root: {ROOT}")
    return path


def _read(path: Path) -> tuple[str, dict[str, Any]]:
    ext = path.suffix.lower()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"Not a file: {path}")
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}")
    pages = None
    if ext == ".txt":
        content = path.read_text(encoding="utf-8", errors="replace")
    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF reading requires pypdf") from exc
        reader = PdfReader(str(path))
        content = "\n".join(page.extract_text() or "" for page in reader.pages)
        pages = len(reader.pages)
    else:
        try:
            import docx
        except ImportError as exc:
            raise RuntimeError("DOCX reading requires python-docx") from exc
        content = "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    stat = path.stat()
    meta: dict[str, Any] = {
        "size_bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "word_count": len(content.split()),
        "char_count": len(content),
    }
    if pages is not None:
        meta["num_pages"] = pages
    return content, meta


def read_file(filepath: str) -> dict[str, Any]:
    path = _safe_path(filepath)
    content, metadata = _read(path)
    return {"success": True, "filepath": str(path), "extension": path.suffix.lower(), "content": content, "metadata": metadata, "error": None}


def list_files(directory: str = ".", extension: str | None = None) -> list[dict[str, Any]]:
    path = _safe_path(directory)
    if not path.is_dir():
        raise NotADirectoryError(f"Directory not found: {path}")
    suffix = extension.lower() if extension else None
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    rows = []
    for entry in sorted(path.iterdir()):
        if entry.is_file() and (not suffix or entry.suffix.lower() == suffix):
            stat = entry.stat()
            rows.append({"name": entry.name, "path": str(entry), "extension": entry.suffix.lower(), "size_bytes": stat.st_size, "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()})
    return rows


def write_file(filepath: str, content: str) -> dict[str, Any]:
    path = _safe_path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"success": True, "filepath": str(path), "bytes_written": len(content.encode("utf-8")), "error": None}


def search_in_file(filepath: str, keyword: str, context_chars: int = 60) -> dict[str, Any]:
    if not keyword:
        raise ValueError("keyword must not be empty")
    path = _safe_path(filepath)
    content, _ = _read(path)
    matches, start = [], 0
    while (idx := content.casefold().find(keyword.casefold(), start)) >= 0:
        snippet = content[max(0, idx-context_chars):min(len(content), idx+len(keyword)+context_chars)].replace("\n", " ").strip()
        matches.append({"position": idx, "context": f"...{snippet}..."})
        start = idx + len(keyword)
    return {"success": True, "filepath": str(path), "keyword": keyword, "match_count": len(matches), "matches": matches, "error": None}


def batch_process(filepaths: list[str]) -> dict[str, Any]:
    """Read many resumes in one tool call; individual failures do not abort the batch."""
    results = []
    for filepath in filepaths:
        try:
            results.append(read_file(filepath))
        except Exception as exc:
            results.append({"success": False, "filepath": filepath, "content": "", "metadata": {}, "error": str(exc)})
    return {"processed": len(results), "succeeded": sum(bool(row["success"]) for row in results), "failed": sum(not row["success"] for row in results), "results": results}


def watch_directory(directory: str = ".", interval_seconds: float = 2, timeout_seconds: float = 30) -> dict[str, Any]:
    """Poll for newly appearing supported files until found or timed out."""
    if interval_seconds <= 0 or timeout_seconds < 0:
        raise ValueError("interval_seconds must be positive and timeout_seconds non-negative")
    path = _safe_path(directory)
    if not path.is_dir():
        raise NotADirectoryError(f"Directory not found: {path}")
    existing = {p.name for p in path.iterdir() if p.is_file()}
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(min(interval_seconds, max(0, deadline - time.monotonic())))
        created = [p for p in sorted(path.iterdir()) if p.is_file() and p.name not in existing and p.suffix.lower() in SUPPORTED_EXTENSIONS]
        if created:
            return {"directory": str(path), "timed_out": False, "files": [{"name": p.name, "path": str(p)} for p in created]}
    return {"directory": str(path), "timed_out": True, "files": []}


TOOLS = [
    {"name": "read_file", "description": "Extract text and metadata from a PDF, TXT, or DOCX resume.", "inputSchema": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}},
    {"name": "list_files", "description": "List files in a directory, optionally filtered by extension.", "inputSchema": {"type": "object", "properties": {"directory": {"type": "string", "default": "."}, "extension": {"type": "string"}}}},
    {"name": "write_file", "description": "Write UTF-8 text beneath the configured root.", "inputSchema": {"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]}},
    {"name": "search_in_file", "description": "Search a supported file and return matching context snippets.", "inputSchema": {"type": "object", "properties": {"filepath": {"type": "string"}, "keyword": {"type": "string"}, "context_chars": {"type": "integer", "default": 60}}, "required": ["filepath", "keyword"]}},
    {"name": "batch_process", "description": "Read multiple resumes in one request, preserving per-file errors.", "inputSchema": {"type": "object", "properties": {"filepaths": {"type": "array", "items": {"type": "string"}}}, "required": ["filepaths"]}},
    {"name": "watch_directory", "description": "Poll for newly added supported resumes until a file appears or timeout expires.", "inputSchema": {"type": "object", "properties": {"directory": {"type": "string", "default": "."}, "interval_seconds": {"type": "number", "default": 2}, "timeout_seconds": {"type": "number", "default": 30}}}},
]
CALLS = {"read_file": read_file, "list_files": list_files, "write_file": write_file, "search_in_file": search_in_file, "batch_process": batch_process, "watch_directory": watch_directory}


def _resource_list() -> list[dict[str, Any]]:
    # An empty or not-yet-created resume root is a valid discovery result. The
    # agent can then explain how to configure/populate it instead of crashing.
    if not ROOT.is_dir():
        return []
    resources = []
    for item in list_files("."):
        if item["extension"] in SUPPORTED_EXTENSIONS:
            uri = "file://" + quote(Path(item["path"]).relative_to(ROOT).as_posix())
            resources.append({"uri": uri, "name": item["name"], "description": "Resume file", "mimeType": "text/plain"})
    return resources


def _dispatch(method: str, params: dict[str, Any]) -> Any:
    if method == "initialize":
        version = params.get("protocolVersion", PROTOCOL_VERSION)
        return {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}}, "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in CALLS:
            raise KeyError(f"Unknown tool: {name}")
        try:
            result = CALLS[name](**args)
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False, "structuredContent": result}
        except (ValueError, FileNotFoundError, IsADirectoryError, PermissionError, KeyError) as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except Exception as exc:
            return {"content": [{"type": "text", "text": f"Tool failed: {exc}"}], "isError": True}
    if method == "resources/list":
        return {"resources": _resource_list()}
    if method == "resources/templates/list":
        return {"resourceTemplates": [{"uriTemplate": "file://{relative_path}", "name": "Resume file content", "description": "Read a supported resume under the configured root", "mimeType": "text/plain"}]}
    if method == "resources/read":
        uri = params.get("uri", "")
        if not uri.startswith("file://"):
            raise ValueError("Unsupported resource URI")
        path = _safe_path(unquote(uri[len("file://"):]))
        content, _ = _read(path)
        return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": content}]}
    raise LookupError(f"Method not found: {method}")


def serve() -> None:
    """Serve JSON-RPC over stdin/stdout; diagnostics belong on stderr."""
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("Invalid JSON-RPC 2.0 request")
            method, params, request_id = request.get("method"), request.get("params") or {}, request.get("id")
            if not isinstance(method, str) or not isinstance(params, dict):
                raise ValueError("method must be a string and params must be an object")
            if method.startswith("notifications/"):
                continue
            try:
                result = _dispatch(method, params)
                response = {"jsonrpc": "2.0", "id": request_id, "result": result}
            except LookupError as exc:
                response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": str(exc)}}
            except (ValueError, TypeError) as exc:
                response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": str(exc)}}
            except Exception as exc:
                response = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(exc)}}
            if "id" in request:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc.msg}"}}) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": str(exc)}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve()
