"""Unified eval harness MCP server.

Serves all eval harness tools over a single HTTP JSON-RPC MCP endpoint so
subprocess-based providers (codex) can call them via curl.

Tools exposed
-------------
  read_file          — read file contents (relative to repo_root)
  glob_files         — find files matching a glob pattern
  grep_files         — regex search across files
  search_memory      — semantic search via VoltSnip API (Claude-compatible name)
  search_snippets    — semantic search via VoltSnip API (legacy alias)
  get_snippet_by_canonical_key — fetch snippet by canonical key (Claude-compatible name)
  get_snippet_by_key — fetch snippet by canonical key (legacy alias)
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .harness_tools import (
    get_snippet_by_key,
    glob_files,
    grep_files,
    read_file,
    search_snippets,
)

LOGGER = logging.getLogger(__name__)

_TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file. path is relative to the repo root. "
            "Returns up to limit lines starting at offset, with line numbers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to file"},
                "offset": {"type": "integer", "default": 0, "description": "Start line (0-indexed)"},
                "limit": {"type": "integer", "default": 200, "description": "Max lines to return"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "glob_files",
        "description": (
            "Find files matching a glob pattern. pattern is relative to the repo root. "
            "Supports ** for recursive matching. Returns sorted list of matching paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern, e.g. '**/*.py'"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_files",
        "description": (
            "Search file contents using a regex pattern. "
            "Returns matching lines with file path and line number."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regex pattern"},
                "path": {"type": "string", "default": ".", "description": "Directory to search (relative to repo root)"},
                "glob": {"type": "string", "default": "**/*", "description": "File glob filter"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "search_memory",
        "description": "Semantic search for reusable code patterns in VoltSnip.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What you are looking for"},
                "intent": {"type": "string", "description": "Legacy alias for query"},
                "language": {"type": "string", "description": "Programming language filter"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tag filters"},
            },
        },
    },
    {
        "name": "search_snippets",
        "description": "Semantic search for reusable code patterns in VoltSnip.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "description": "What you are looking for"},
                "language": {"type": "string", "description": "Programming language filter"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Tag filters"},
            },
            "required": ["intent"],
        },
    },
    {
        "name": "get_snippet_by_canonical_key",
        "description": "Fetch a specific snippet directly by its canonical key from VoltSnip.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Canonical snippet key"},
                "canonical_key": {"type": "string", "description": "Legacy alias for key"},
            },
        },
    },
    {
        "name": "get_snippet_by_key",
        "description": "Fetch a specific snippet directly by its canonical key from VoltSnip.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Canonical snippet key"},
            },
            "required": ["key"],
        },
    },
]

# Filesystem tool names — used to filter when include_fs_tools=False.
_FS_TOOL_NAMES: frozenset[str] = frozenset({"read_file", "glob_files", "grep_files"})


def _make_handler(
    repo_root: Path,
    base_url: str,
    include_fs_tools: bool = False,
) -> type[BaseHTTPRequestHandler]:
    root = repo_root.resolve()
    vs_base = base_url.rstrip("/")
    exposed_tools = _TOOLS if include_fs_tools else [t for t in _TOOLS if t["name"] not in _FS_TOOL_NAMES]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                req = json.loads(body) if body else {}
            except Exception as exc:
                self._send(400, {"error": str(exc)})
                return

            method = req.get("method", "")
            req_id = req.get("id", 0)

            if method == "initialize":
                self._send(200, {"jsonrpc": "2.0", "id": req_id, "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "vsevals-harness", "version": "1.0"},
                }})
            elif method.startswith("notifications/"):
                # JSON-RPC notifications have no id — respond with
                # HTTP 202 Accepted and empty body per MCP spec.
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif method == "tools/list":
                self._send(200, {"jsonrpc": "2.0", "id": req_id, "result": {"tools": exposed_tools}})
            elif method == "tools/call":
                params = req.get("params", {})
                name = params.get("name", "")
                args = params.get("arguments", {})
                try:
                    if not include_fs_tools and name in _FS_TOOL_NAMES:
                        raise ValueError(f"tool {name!r} is not available in this eval variant")
                    text = _call_tool(root, vs_base, name, args)
                    self._send(200, {
                        "jsonrpc": "2.0", "id": req_id,
                        "result": {"content": [{"type": "text", "text": text}]},
                    })
                except Exception as exc:
                    self._send(200, {
                        "jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32603, "message": str(exc)},
                    })
            elif method == "resources/list":
                # Codex queries for MCP resources before falling through to
                # tools.  Return a well-formed empty list so it moves on.
                self._send(200, {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}})
            elif method == "resources/templates/list":
                self._send(200, {"jsonrpc": "2.0", "id": req_id, "result": {"resourceTemplates": []}})
            elif method == "resources/read":
                # No resources served — return a JSON-RPC error.
                params = req.get("params", {})
                uri = params.get("uri", "<unknown>")
                self._send(200, {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32602, "message": f"resource not found: {uri}"},
                })
            elif method == "prompts/list":
                self._send(200, {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}})
            else:
                # Unknown methods: return empty result (required for MCP handshake)
                self._send(200, {"jsonrpc": "2.0", "id": req_id, "result": {}})

        def _send(self, code: int, data: dict) -> None:
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass  # suppress per-request logs

    return Handler


def _call_tool(root: Path, base_url: str, name: str, args: dict) -> str:
    if name == "read_file":
        return read_file(root, args.get("path", ""), int(args.get("offset", 0)), int(args.get("limit", 200)))
    elif name == "glob_files":
        return glob_files(root, args.get("pattern", "**/*"))
    elif name == "grep_files":
        return grep_files(root, args.get("pattern", ""), args.get("path", "."), args.get("glob", "**/*"))
    elif name in ("search_memory", "search_snippets"):
        query = args.get("query") or args.get("intent") or ""
        return search_snippets(base_url, query, args.get("language"), args.get("tags"))
    elif name in ("get_snippet_by_canonical_key", "get_snippet_by_key"):
        key = args.get("key") or args.get("canonical_key") or ""
        if not key:
            keys = args.get("canonical_keys") or []
            if isinstance(keys, list) and keys:
                key = str(keys[0])
        return get_snippet_by_key(base_url, key)
    else:
        raise ValueError(f"unknown tool: {name!r}")


class HarnessMCPServer:
    """Lifecycle wrapper around the unified harness MCP HTTP server."""

    def __init__(
        self,
        repo_root: Path | str,
        base_url: str,
        port: int = 0,
        include_fs_tools: bool = False,
    ) -> None:
        root = Path(repo_root).resolve()
        handler = _make_handler(root, base_url, include_fs_tools=include_fs_tools)
        self._server = HTTPServer(("127.0.0.1", port), handler)
        self.port: int = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> "HarnessMCPServer":
        self._thread.start()
        LOGGER.debug("harness MCP server started on port %d", self.port)
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=2)
        LOGGER.debug("harness MCP server stopped")
