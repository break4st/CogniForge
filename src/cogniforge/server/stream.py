"""Stream manager — tracks which request IDs are streaming."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _StreamState:
    started: float = 0.0


class StreamManager:
    """Lightweight tracker for in-progress streaming responses."""

    def __init__(self):
        self._streams: dict[int, _StreamState] = {}

    def begin(self, request_id: int) -> None:
        self._streams[request_id] = _StreamState(started=time.monotonic())

    def end(self, request_id: int) -> None:
        self._streams.pop(request_id, None)

    def is_streaming(self, request_id: int) -> bool:
        return request_id in self._streams
