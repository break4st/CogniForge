"""JSON-RPC 2.0 stdio server entry point.

Usage:
    python -m cogniforge.server              # Run server (stdio loop)
    python -m cogniforge.server --export-schema > rpc-api.json
"""

from __future__ import annotations

import os
import sys
import json
import threading
import traceback
from pathlib import Path

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
    INVALID_PARAMS,
    INTERNAL_ERROR,
    AGENT_NOT_FOUND,
    WORKFLOW_ERROR,
    PROJECT_NOT_FOUND,
    AGENT_EXEC_FAILED,
    CANCELLED,
)
from cogniforge.server.methods import MethodRegistry, MethodNotFoundError
from cogniforge.server.stream import StreamManager
from cogniforge.services.agent_service import AgentService, AgentCancelledError
from cogniforge.services.workflow_service import WorkflowService, WorkflowError
from cogniforge.services.project_service import ProjectService
from cogniforge.services.wiki_service import WikiService
from cogniforge.services import build_services
from cogniforge.core.constants import AgentRole


def _build_registry(
    agent_svc: AgentService,
    workflow_svc: WorkflowService | None,
    project_svc: ProjectService,
    wiki_svc: WikiService | None,
) -> MethodRegistry:
    """Register all RPC methods."""

    registry = MethodRegistry()

    # ── workflow.* ──
    if workflow_svc is not None:
        registry.register(
            "workflow.start",
            lambda p: workflow_svc.start(
                project_path=p.get("project_path", ""),
                resume=p.get("resume", True),
            ),
            description="Start or resume the workflow",
        )
        registry.register(
            "workflow.status",
            lambda _: workflow_svc.status(),
            description="Return current workflow state",
        )
        registry.register(
            "workflow.approve",
            lambda p: workflow_svc.approve(
                step=p.get("step"),
                comment=p.get("comment", ""),
                approver=p.get("approver", "human"),
            ),
            description="Approve the current or named step",
        )
        registry.register(
            "workflow.reject",
            lambda p: workflow_svc.reject(
                step=p.get("step"),
                comment=p.get("comment", ""),
                approver=p.get("approver", "human"),
            ),
            description="Reject the current or named step",
        )
        registry.register(
            "workflow.advance",
            lambda p: workflow_svc.advance(result=p.get("result")),
            description="Advance to the next step after approval",
        )
        registry.register(
            "workflow.history",
            lambda _: workflow_svc.history(),
            description="Return full workflow operation history",
        )

    # ── agent.* ──
    registry.register(
        "agent.status",
        lambda _: agent_svc.status(),
        description="List all agents and their descriptions",
    )
    registry.register(
        "agent.run",
        lambda _: None,  # Special handler in main loop
        description="Run an agent with streaming progress",
        streaming=True,
    )

    # ── project.* ──
    registry.register(
        "project.list",
        lambda _: project_svc.list(),
        description="List all CogniForge projects",
    )
    registry.register(
        "project.create",
        lambda p: project_svc.create(
            path=p.get("path", p.get("project_path", "")),
            name=p.get("name", p.get("project_name", "")),
        ),
        description="Initialize a new CogniForge project",
    )
    registry.register(
        "project.open",
        lambda p: project_svc.open(
            project_id=p.get("project_id", ""),
            path=p.get("path", ""),
        ),
        description="Open a project and return its summary",
    )

    # ── wiki.* ──
    if wiki_svc is not None:
        registry.register(
            "wiki.list",
            lambda p: wiki_svc.list(doc_type_str=p.get("type", "")),
            description="List wiki documents, optionally filtered by type",
        )
        registry.register(
            "wiki.read",
            lambda p: wiki_svc.read(path=p["path"]),
            description="Read a wiki document by path",
        )
        registry.register(
            "wiki.search",
            lambda p: wiki_svc.search(query=p.get("query", "")),
            description="Full-text search across wiki documents",
        )

    # ── server.* ──
    registry.register(
        "server.ping",
        lambda _: "pong",
        description="Health check — returns 'pong'",
    )

    return registry


def _write_line(line: str, lock: threading.Lock) -> None:
    """Thread-safe write to stdout."""
    with lock:
        sys.stdout.write(line)
        sys.stdout.flush()


def _handle_streaming_agent(
    request,
    agent_svc: AgentService,
    stdout_lock: threading.Lock,
) -> None:
    """Execute agent.run in a background thread and stream results to stdout."""
    params = request.params
    role = params.get("role", "")
    input_data = params.get("input_data", {})
    request_id = request.id

    def on_progress(status: str):
        chunk = format_stream_chunk({"status": status}, request_id)
        _write_line(chunk, stdout_lock)

    def on_content(line: str):
        chunk = format_stream_chunk({"content": line}, request_id)
        _write_line(chunk, stdout_lock)

    cancel_event = agent_svc.submit(
        role=role,
        input_data=input_data,
        request_id=request_id,
        on_progress=on_progress,
        on_content=on_content,
    )

    def _wait_and_finalize():
        try:
            future = agent_svc.get_future(request_id)
            if future is None:
                return
            result = future.result()
            final = format_stream_chunk({"done": True, "data": result}, request_id, done=True)
            _write_line(final, stdout_lock)
        except AgentCancelledError:
            err = format_error(CANCELLED, "Agent execution cancelled", request_id)
            _write_line(err, stdout_lock)
        except Exception as exc:
            tb = traceback.format_exc()
            err = format_error(AGENT_EXEC_FAILED, str(exc), request_id, data=tb)
            _write_line(err, stdout_lock)

    t = threading.Thread(target=_wait_and_finalize, daemon=True)
    t.start()


def _init_services_for_request(params: dict, current_context: dict | None) -> dict:
    """Lazily initialize services when project_path is provided."""
    project_path = params.get("project_path", "")
    if not project_path:
        if current_context:
            return current_context
        project_path = str(Path.cwd())

    repo_path = Path(project_path).resolve()
    if current_context and current_context.get("repo_path") == repo_path:
        return current_context

    ctx = build_services(repo_path)
    ctx["repo_path"] = repo_path
    ctx["agent_service"] = AgentService(ctx["agents"])
    ctx["workflow_service"] = WorkflowService(ctx["workflow"])
    ctx["project_service"] = ProjectService(repo_path)
    ctx["wiki_service"] = WikiService(ctx["wiki_system"], repo_path)
    return ctx


def main():
    """RPC server main loop."""
    import argparse

    parser = argparse.ArgumentParser(description="CogniForge JSON-RPC 2.0 Server")
    parser.add_argument(
        "--export-schema",
        action="store_true",
        help="Export RPC method schemas as JSON and exit",
    )
    args = parser.parse_args()

    # ── Schema export mode ──────────────────────────────────────────────
    if args.export_schema:
        # Build a minimal registry for schema export (no live services needed)
        repo_path = Path.cwd()
        ctx = build_services(repo_path)
        agent_svc = AgentService(ctx["agents"])
        wf_svc = WorkflowService(ctx["workflow"])
        proj_svc = ProjectService(repo_path)
        wiki_svc = WikiService(ctx["wiki_system"], repo_path)
        reg = _build_registry(agent_svc, wf_svc, proj_svc, wiki_svc)
        json.dump(
            reg.export_schema(),
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return

    # ── Server mode ─────────────────────────────────────────────────────
    stdout_lock = threading.Lock()
    stream_mgr = StreamManager()

    # Mark server mode so config validation doesn't SystemExit
    os.environ["COGNIFORGE_SERVER_MODE"] = "1"

    # Redirect click.echo to stderr since stdout is the RPC channel
    import click
    _original_echo = click.echo
    def _stderr_echo(message=None, file=None, nl=True, err=False, color=None, **styles):
        return _original_echo(message, file=sys.stderr, nl=nl, err=True, color=color, **styles)
    click.echo = _stderr_echo

    # Suppress __main__ RuntimeWarning on import
    import warnings
    warnings.filterwarnings("ignore", message=".*found in sys.modules.*")

    # Bootstrap: create a default context for ping / agent.status / project.list
    default_repo = Path.cwd()
    try:
        default_ctx = build_services(default_repo)
    except Exception:
        print(f"Warning: Could not bootstrap from {default_repo}", file=sys.stderr)
        # Minimal fallback for when cwd is not a CogniForge project
        from cogniforge.core.config import Config
        from cogniforge.orchestration.workflow import Workflow
        from cogniforge.task_engine.dag import DAGDefinition
        dummy_config = Config(repo_path=default_repo)
        dummy_ctx = {
            "config": dummy_config,
            "git_storage": None,
            "wiki_system": None,
            "context_loader": None,
            "task_engine": None,
            "workflow": Workflow(DAGDefinition(), repo_path=default_repo),
            "agents": {},
            "_providers": {},
            "repo_path": default_repo,
        }
        default_ctx = dummy_ctx
    default_ctx["repo_path"] = default_repo
    agent_svc = AgentService(default_ctx["agents"])
    wf_svc = WorkflowService(default_ctx["workflow"])
    proj_svc = ProjectService(default_repo)
    wiki_svc = WikiService(default_ctx["wiki_system"], default_repo)

    registry = _build_registry(agent_svc, wf_svc, proj_svc, wiki_svc)

    # Store lazy contexts keyed by repo_path
    _lazy_contexts: dict[str, dict] = {str(default_repo): default_ctx}

    def _ensure_context(params: dict) -> dict:
        """Return (or create) the context for the given params."""
        project_path = params.get("project_path", "")
        if not project_path:
            return default_ctx
        resolved = str(Path(project_path).resolve())
        if resolved in _lazy_contexts:
            return _lazy_contexts[resolved]
        ctx = build_services(Path(resolved))
        ctx["repo_path"] = Path(resolved)
        ctx["agent_service"] = AgentService(ctx["agents"])
        ctx["workflow_service"] = WorkflowService(ctx["workflow"])
        ctx["project_service"] = ProjectService(Path(resolved))
        ctx["wiki_service"] = WikiService(ctx["wiki_system"], Path(resolved))
        _lazy_contexts[resolved] = ctx
        return ctx

    # Send hello
    hello = format_notification(
        "server.hello",
        {"version": "1.0", "capabilities": ["streaming"]},
    )
    _write_line(hello, stdout_lock)

    # ── Main loop ───────────────────────────────────────────────────────
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        # Parse
        try:
            request = parse_request(line)
        except JSONRPCProtocolError as e:
            _write_line(format_error(e.code, e.message, e.request_id), stdout_lock)
            continue

        # Notifications (no id — no response expected)
        if request.is_notification:
            if request.method == "cancel":
                req_id = request.params.get("id", 0)
                ctx = _ensure_context(request.params)
                ctx_agent_svc = ctx.get("agent_service", agent_svc)
                ctx_agent_svc.cancel(req_id)
            elif request.method == "shutdown":
                break
            continue

        # Regular request — dispatch
        try:
            # Resolve context for this request
            ctx = _ensure_context(request.params)

            # Rebuild registry with context-specific services
            ctx_agent_svc = ctx.get("agent_service", agent_svc)
            ctx_wf_svc = ctx.get("workflow_service", wf_svc)
            ctx_proj_svc = ctx.get("project_service", proj_svc)
            ctx_wiki_svc = ctx.get("wiki_service", wiki_svc)
            ctx_registry = _build_registry(ctx_agent_svc, ctx_wf_svc, ctx_proj_svc, ctx_wiki_svc)

            # Streaming: agent.run
            if request.method == "agent.run":
                _handle_streaming_agent(request, ctx_agent_svc, stdout_lock)
                continue

            # Non-streaming
            result = ctx_registry.dispatch(request.method, request.params)
            _write_line(format_response(result, request.id), stdout_lock)

        except MethodNotFoundError as e:
            _write_line(format_error(METHOD_NOT_FOUND, str(e), request.id), stdout_lock)
        except KeyError as e:
            _write_line(format_error(AGENT_NOT_FOUND, f"Agent not found: {e}", request.id), stdout_lock)
        except (WorkflowError,) as e:
            _write_line(format_error(WORKFLOW_ERROR, str(e), request.id), stdout_lock)
        except FileNotFoundError as e:
            _write_line(format_error(PROJECT_NOT_FOUND, str(e), request.id), stdout_lock)
        except Exception as e:
            tb = traceback.format_exc()
            _write_line(format_error(INTERNAL_ERROR, str(e), request.id, data=tb), stdout_lock)

    # ── Cleanup ─────────────────────────────────────────────────────────
    agent_svc.shutdown(wait=False)


if __name__ == "__main__":
    main()
