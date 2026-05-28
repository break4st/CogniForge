"""Agent execution service — thread-safe wrapper for agent.run()."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Any


class AgentCancelledError(Exception):
    """Raised when agent execution is cancelled via cancel_event."""


class AgentService:
    """Wraps agent execution with cancellation and progress callback support."""

    def __init__(self, agents: dict[str, Any]):
        self._agents = agents
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="agent")
        self._lock = threading.Lock()
        # request_id -> {"future": Future, "cancel_event": Event, "start_time": float}
        self._running: dict[int, dict] = {}

    def status(self) -> dict[str, dict]:
        """Return status for all registered agents."""
        result = {}
        for role, agent in self._agents.items():
            result[role] = {
                "role": role,
                "description": getattr(
                    getattr(agent, "definition", None), "description", ""
                ),
            }
        return result

    def run(
        self,
        role: str,
        input_data: dict,
        *,
        on_progress: Callable[[str], None] | None = None,
        on_content: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict:
        """Execute an agent synchronously.

        Injects _progress_callback and _content_callback into input_data.
        The progress callback checks cancel_event on each invocation and
        raises AgentCancelledError if set.
        """
        if role not in self._agents:
            raise KeyError(f"Unknown agent role: {role}")

        agent = self._agents[role]
        input_copy = dict(input_data)

        # Inject progress callback with cancellation check
        def _cb(status: str) -> None:
            if cancel_event and cancel_event.is_set():
                raise AgentCancelledError(f"Agent {role} cancelled")
            if on_progress:
                on_progress(status)

        input_copy["_progress_callback"] = _cb
        if on_content:
            input_copy["_content_callback"] = on_content

        return agent.run(input_copy)

    def submit(
        self,
        role: str,
        input_data: dict,
        *,
        request_id: int,
        on_progress: Callable[[str], None] | None = None,
        on_content: Callable[[str], None] | None = None,
    ) -> threading.Event:
        """Submit agent execution to the thread pool.

        Returns the cancel_event for this request so the caller can
        cancel it later.
        """
        cancel_event = threading.Event()

        def _run():
            try:
                return self.run(
                    role, input_data,
                    on_progress=on_progress,
                    on_content=on_content,
                    cancel_event=cancel_event,
                )
            finally:
                with self._lock:
                    self._running.pop(request_id, None)

        future = self._executor.submit(_run)
        with self._lock:
            self._running[request_id] = {
                "future": future,
                "cancel_event": cancel_event,
                "start_time": time.monotonic(),
            }
        return cancel_event

    def cancel(self, request_id: int) -> bool:
        """Signal cancellation for a running agent."""
        with self._lock:
            entry = self._running.get(request_id)
        if not entry:
            return False
        entry["cancel_event"].set()
        # Future.cancel only works if not started; the Event handles
        # the in-flight case via the progress callback.
        entry["future"].cancel()
        return True

    def get_future(self, request_id: int) -> Future | None:
        """Get the Future for a running request, or None."""
        with self._lock:
            entry = self._running.get(request_id)
        return entry["future"] if entry else None

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the thread pool."""
        self._executor.shutdown(wait=wait)
