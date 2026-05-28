"""Unit tests for JSON-RPC protocol layer."""

import json
import pytest
from cogniforge.server.jsonrpc import (
    parse_request,
    JSONRPCProtocolError,
    format_response,
    format_error,
    format_notification,
    format_stream_chunk,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
)


class TestParseRequest:
    def test_valid_request(self):
        r = parse_request(
            '{"jsonrpc":"2.0","method":"server.ping","id":1}'
        )
        assert r.method == "server.ping"
        assert r.id == 1
        assert r.params == {}
        assert not r.is_notification

    def test_notification_no_id(self):
        r = parse_request(
            '{"jsonrpc":"2.0","method":"agent.progress","params":{"status":"ok"}}'
        )
        assert r.is_notification
        assert r.method == "agent.progress"
        assert r.params == {"status": "ok"}

    def test_missing_method(self):
        with pytest.raises(JSONRPCProtocolError) as e:
            parse_request('{"jsonrpc":"2.0","id":1}')
        assert e.value.code == INVALID_REQUEST

    def test_invalid_json(self):
        with pytest.raises(JSONRPCProtocolError) as e:
            parse_request("not json")
        assert e.value.code == PARSE_ERROR

    def test_wrong_jsonrpc_version(self):
        with pytest.raises(JSONRPCProtocolError) as e:
            parse_request('{"jsonrpc":"1.0","method":"ping","id":1}')
        assert e.value.code == INVALID_REQUEST

    def test_params_not_dict(self):
        with pytest.raises(JSONRPCProtocolError) as e:
            parse_request(
                '{"jsonrpc":"2.0","method":"ping","params":[1,2],"id":1}'
            )
        assert e.value.code == -32602  # INVALID_PARAMS


class TestFormatResponse:
    def test_basic(self):
        result = format_response("pong", 1)
        data = json.loads(result)
        assert data["jsonrpc"] == "2.0"
        assert data["result"] == "pong"
        assert data["id"] == 1

    def test_null_id(self):
        result = format_response(None, None)
        data = json.loads(result)
        assert data["id"] is None
        assert data["result"] is None


class TestFormatError:
    def test_basic(self):
        result = format_error(METHOD_NOT_FOUND, "Not found", 1)
        data = json.loads(result)
        assert data["error"]["code"] == METHOD_NOT_FOUND
        assert data["error"]["message"] == "Not found"
        assert data["id"] == 1


class TestFormatNotification:
    def test_hello(self):
        result = format_notification(
            "server.hello", {"version": "1.0"}
        )
        data = json.loads(result)
        assert "id" not in data
        assert data["method"] == "server.hello"
        assert data["params"]["version"] == "1.0"


class TestFormatStreamChunk:
    def test_intermediate(self):
        result = format_stream_chunk({"status": "thinking"}, 2)
        data = json.loads(result)
        assert data["id"] == 2
        assert data["result"]["status"] == "thinking"
        assert "done" not in data["result"]

    def test_final(self):
        result = format_stream_chunk({"done": True, "data": {"x": 1}}, 2, done=True)
        data = json.loads(result)
        assert data["result"]["done"] is True
        assert data["result"]["data"] == {"x": 1}
