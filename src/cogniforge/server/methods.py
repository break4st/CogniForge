"""Method registry — maps RPC method names to handler functions."""

from __future__ import annotations

from typing import Any, Callable


class MethodNotFoundError(Exception):
    """Raised when an RPC method is not registered."""

    def __init__(self, method: str):
        self.method = method
        super().__init__(f"Method not found: {method}")


class MethodRegistry:
    """Maps RPC method names → handler functions."""

    def __init__(self):
        self._methods: dict[str, Callable[..., Any]] = {}
        self._schemas: dict[str, dict] = {}

    def register(
        self,
        method: str,
        handler: Callable[..., Any],
        params_schema: dict | None = None,
        result_schema: dict | None = None,
        description: str = "",
        streaming: bool = False,
    ) -> None:
        """Register an RPC method."""
        self._methods[method] = handler
        self._schemas[method] = {
            "params": params_schema or {},
            "result": result_schema or {},
            "description": description or (handler.__doc__ or "").strip(),
            "streaming": streaming,
        }

    def dispatch(self, method: str, params: dict) -> Any:
        """Look up and invoke a handler. Returns the handler's result."""
        handler = self._methods.get(method)
        if handler is None:
            raise MethodNotFoundError(method)
        return handler(params)

    def is_streaming(self, method: str) -> bool:
        """Check if a method is marked as streaming."""
        info = self._schemas.get(method, {})
        return bool(info.get("streaming", False))

    def list_methods(self) -> list[str]:
        """Return all registered method names."""
        return list(self._methods.keys())

    def export_schema(self) -> dict:
        """Export all method schemas as a JSON-serializable dict."""
        return {
            "jsonrpc": "2.0",
            "methods": {
                name: {
                    "params": info["params"],
                    "result": info["result"],
                    "description": info["description"],
                    "streaming": info["streaming"],
                }
                for name, info in self._schemas.items()
            },
        }
