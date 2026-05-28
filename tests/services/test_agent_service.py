"""Unit tests for AgentService."""

import pytest
import threading
import time
from unittest.mock import MagicMock

from cogniforge.services.agent_service import AgentService, AgentCancelledError


class FakeAgent:
    """An agent stub that respects progress callback and cancel event."""

    def __init__(self, role="pm", result=None, delay=0.0):
        self.role = role
        self._result = result or {"status": "success", "message": "done"}
        self._delay = delay

    def run(self, input_data):
        cb = input_data.get("_progress_callback")
        if cb:
            cb("starting")
        if self._delay:
            time.sleep(self._delay)
        if cb:
            cb("done")
        return dict(self._result)


class TestAgentService:
    def test_status(self):
        agents = {"pm": FakeAgent(), "architect": FakeAgent()}
        svc = AgentService(agents)
        status = svc.status()
        assert "pm" in status
        assert "architect" in status

    def test_run_unknown_role(self):
        svc = AgentService({})
        with pytest.raises(KeyError, match="Unknown agent role"):
            svc.run("nonexistent", {})

    def test_run_success(self):
        agents = {"pm": FakeAgent(result={"status": "success", "msg": "ok"})}
        svc = AgentService(agents)
        progress = []

        result = svc.run("pm", {"raw_text": "hi"}, on_progress=progress.append)
        assert result["status"] == "success"
        assert progress == ["starting", "done"]

    def test_run_cancellation(self):
        agents = {"pm": FakeAgent()}
        svc = AgentService(agents)
        cancel_event = threading.Event()
        cancel_event.set()  # pre-set — should cancel on first callback

        with pytest.raises(AgentCancelledError):
            svc.run("pm", {"raw_text": "hi"}, cancel_event=cancel_event)

    def test_submit_and_cancel(self):
        agents = {"pm": FakeAgent(delay=0.5)}
        svc = AgentService(agents)
        progress = []

        cancel = svc.submit(
            "pm", {"raw_text": "hi"},
            request_id=42,
            on_progress=progress.append,
        )

        # Cancel immediately
        ok = svc.cancel(42)
        assert ok is True

        # Already cancelled
        ok2 = svc.cancel(99)
        assert ok2 is False

        svc.shutdown(wait=True)
