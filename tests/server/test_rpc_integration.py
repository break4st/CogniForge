"""Integration tests for the JSON-RPC stdio server.

Starts the server as a subprocess, sends JSON-RPC requests line by line,
and verifies the responses.
"""

import json
import subprocess
import sys


SERVER_MODULE = "cogniforge.server"


def _start_server():
    """Launch the server subprocess and return the Popen handle."""
    proc = subprocess.Popen(
        [sys.executable, "-m", SERVER_MODULE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Read the hello notification
    hello = json.loads(proc.stdout.readline().strip())
    assert "server.hello" == hello.get("method")
    assert hello.get("params", {}).get("version") == "1.0"
    return proc


def _rpc(proc, method, params=None, request_id=1):
    """Send a JSON-RPC request and read one response line."""
    payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": request_id}
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline().strip()
    return json.loads(line)


class TestRpcIntegration:
    def test_ping(self):
        proc = _start_server()
        try:
            resp = _rpc(proc, "server.ping")
            assert resp["result"] == "pong"
            assert resp["id"] == 1
        finally:
            proc.terminate()
            proc.wait()

    def test_agent_status(self):
        proc = _start_server()
        try:
            resp = _rpc(proc, "agent.status")
            assert "result" in resp
            agents = resp["result"]
            assert "pm" in agents
            assert "architect" in agents
        finally:
            proc.terminate()
            proc.wait()

    def test_project_list(self):
        proc = _start_server()
        try:
            resp = _rpc(proc, "project.list")
            assert "result" in resp
            assert isinstance(resp["result"], list)
        finally:
            proc.terminate()
            proc.wait()

    def test_method_not_found(self):
        proc = _start_server()
        try:
            resp = _rpc(proc, "nonexistent.method")
            assert "error" in resp
            assert resp["error"]["code"] == -32601
        finally:
            proc.terminate()
            proc.wait()

    def test_parse_error(self):
        proc = _start_server()
        try:
            proc.stdin.write("not valid json\n")
            proc.stdin.flush()
            line = proc.stdout.readline().strip()
            resp = json.loads(line)
            assert "error" in resp
            assert resp["error"]["code"] == -32700
        finally:
            proc.terminate()
            proc.wait()
