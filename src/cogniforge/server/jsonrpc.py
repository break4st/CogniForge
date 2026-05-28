"""JSON-RPC 2.0 wire protocol — parse, format, error codes.

Transport: line-delimited JSON over stdio (one complete JSON object per line).

Streaming: server writes multiple lines with the same id, final line has
{"done": true} in the result object.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ── Standard JSON-RPC 2.0 error codes ──────────────────────────────────────
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# ── Application-level error codes ──────────────────────────────────────────
AGENT_NOT_FOUND = -32000
WORKFLOW_ERROR = -32001
PROJECT_NOT_FOUND = -32002
AGENT_EXEC_FAILED = -32003
CANCELLED = -32004
AGENT_CANCELLED_CODE = -32005

# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class JSONRPCRequest:
    """A parsed JSON-RPC 2.0 request or notification."""
    jsonrpc: str = "2.0"
    method: str = ""
    params: dict = field(default_factory=dict)
    id: int | str | None = None

    @property
    def is_notification(self) -> bool:
        return self.id is None


# ── Parse ───────────────────────────────────────────────────────────────────


class JSONRPCProtocolError(Exception):
    """Raised for protocol-level errors that should be sent back to the client."""

    def __init__(self, code: int, message: str, request_id: int | str | None = None):
        self.code = code
        self.message = message
        self.request_id = request_id


def parse_request(line: str) -> JSONRPCRequest:
    """Parse a single line into a JSONRPCRequest.

    Raises JSONRPCProtocolError on parse failures.
    """
    try:
        data = json.loads(line)
    except json.JSONDecodeError as e:
        raise JSONRPCProtocolError(PARSE_ERROR, f"Parse error: {e}") from e

    if not isinstance(data, dict):
        raise JSONRPCProtocolError(INVALID_REQUEST, "Request must be a JSON object")

    if data.get("jsonrpc") != "2.0":
        raise JSONRPCProtocolError(
            INVALID_REQUEST,
            "jsonrpc must be '2.0'",
            data.get("id"),
        )

    method = data.get("method", "")
    if not method or not isinstance(method, str):
        raise JSONRPCProtocolError(
            INVALID_REQUEST,
            "method is required",
            data.get("id"),
        )

    params = data.get("params", {})
    if not isinstance(params, dict):
        raise JSONRPCProtocolError(
            INVALID_PARAMS,
            "params must be an object",
            data.get("id"),
        )

    request_id = data.get("id")

    return JSONRPCRequest(
        jsonrpc="2.0",
        method=method,
        params=params,
        id=request_id,
    )


# ── Format ──────────────────────────────────────────────────────────────────


def format_response(result: Any, request_id: int | str | None = None) -> str:
    """Format a successful JSON-RPC response line."""
    payload = {"jsonrpc": "2.0", "result": result, "id": request_id}
    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"


def format_error(
    code: int,
    message: str,
    request_id: int | str | None = None,
    data: Any = None,
) -> str:
    """Format a JSON-RPC error response line."""
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    payload = {"jsonrpc": "2.0", "error": error, "id": request_id}
    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"


def format_notification(method: str, params: dict) -> str:
    """Format a server→client notification (no id field)."""
    payload = {"jsonrpc": "2.0", "method": method, "params": params}
    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"


def format_stream_chunk(
    result: Any,
    request_id: int | str,
    done: bool = False,
) -> str:
    """Format a streaming response chunk.

    For intermediate chunks, result may contain status/progress info.
    The final chunk marks done=true.
    """
    payload = {"jsonrpc": "2.0", "result": result, "id": request_id}
    if done and isinstance(result, dict):
        result["done"] = True
        payload["result"] = result
    return json.dumps(payload, ensure_ascii=False, default=str) + "\n"
