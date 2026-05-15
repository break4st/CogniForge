"""REPL — interactive natural-language workflow session (Claude Code style)."""

from __future__ import annotations

import itertools
import json
import os
import re
import select
import sys
import termios
import threading
import time
import tty
from pathlib import Path
from typing import Optional

import click

from cogniforge.core.constants import TaskStatus
from cogniforge.llm.base import BaseLLMAdapter
from cogniforge.models.task import Task
from cogniforge.orchestration.workflow import Workflow
from cogniforge.task_engine.dag import DAGStep
from cogniforge.task_engine.task_engine import TaskEngine
from cogniforge.repl_text import (
    AGENT_SCHEMAS,
    REVIEW_STEPS,
    WELCOME_LINE_1,
    WELCOME_LINE_2,
    WELCOME_LINE_3,
    WORKFLOW_COMPLETE,
    PAUSE_MESSAGE,
    QUIT_MESSAGE,
    SPINNER_INTERPRETING,
    SPINNER_RUNNING,
    CHOICE_APPROVE,
    CHOICE_REJECT,
    CHOICE_RETRY,
    APPROVE_CONFIRM,
    REJECT_PROMPT,
    REJECT_DEFAULT,
    APPROVE_OK,
    APPROVE_NEXT,
    APPROVE_DONE,
    REJECT_OK,
    REJECT_REASON,
    REJECT_HINT,
    NO_STEP_APPROVE,
    NO_STEP_REJECT,
    UNKNOWN_ACTION,
    HELP_TEXT,
    SKIP_OK,
    SKIP_NEXT,
    CLEAR_OK,
    CLEAR_CURRENT,
    UNKNOWN_CMD,
    STATUS_WORKFLOW,
    STATUS_STARTED,
    STATUS_STEP,
    STATUS_AWAITING,
    STATUS_COMPLETED,
    STATUS_TASKS,
    PROMPT_REVIEW,
    PROMPT_AGENT,
    PROMPT_RETRY_SUFFIX,
    PARSE_RETRY,
    PARSE_FAIL,
    INTERPRET_FAIL,
    AGENT_NO_ROLE,
    AGENT_EXEC_ERROR,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> str:
    """Strip markdown code fences so we get bare JSON."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _step_label(step: Optional[DAGStep]) -> str:
    if step is None:
        return "(none)"
    return f"{step.value} — {step.get_approval_prompt()}"


def _display_width(text: str) -> int:
    """Terminal display width — East Asian wide characters count as 2."""
    w = 0
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF    # CJK Unified Ideographs
            or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
            or 0x3000 <= cp <= 0x303F  # CJK Symbols & Punctuation
            or 0xFF01 <= cp <= 0xFF60  # Fullwidth Forms
            or 0xFFE0 <= cp <= 0xFFE6  # Fullwidth Signs
            or 0x2E80 <= cp <= 0x2FDF  # CJK Radicals Supplement
            or 0xFE30 <= cp <= 0xFE4F  # CJK Compatibility Forms
            or 0xF900 <= cp <= 0xFAFF  # CJK Compatibility Ideographs
            or 0x20000 <= cp <= 0x2FFFF  # CJK Extension B+
        ):
            w += 2
        else:
            w += 1
    return w


def _draw_box(top_line: str, lines: list[str], bottom_close: bool = True) -> str:
    """Draw a CJK-aware aligned box.

    top_line: title in the top border
    lines: body lines
    """
    all_lines = [top_line] + lines
    content_w = max(_display_width(ln) for ln in all_lines)
    # Ensure room for ─ padding around title in top border (needs ≥2 extra cols)
    max_w = max(content_w, _display_width(top_line) + 2)

    def _pad(ln: str) -> str:
        return ln + " " * (max_w - _display_width(ln))

    # Top: ╭─ title ───────╮
    fill_w = max_w - _display_width(top_line) - 2  # always ≥ 0 now
    top = f"  ╭─ {top_line} {'─' * fill_w}─╮"

    body = [f"  │ {_pad(ln)} │" for ln in lines]
    bottom = f"  ╰─{'─' * max_w}─╯" if bottom_close else None

    return "\n".join([top] + body + ([bottom] if bottom else []))


# ---------------------------------------------------------------------------
# Arrow-key select menu
# ---------------------------------------------------------------------------


def _read_key() -> str:
    """Read a single keypress from stdin in raw mode. Returns 'up'/'down'/'enter'/esc/char."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        b = os.read(fd, 1)
        if b == b"\x1b":
            # Check if more bytes follow (escape sequence)
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                more = os.read(fd, 2)
                seq = b + more
                if seq == b"\x1b[A":
                    return "up"
                elif seq == b"\x1b[B":
                    return "down"
            return "esc"
        elif b == b"\r" or b == b"\n":
            return "enter"
        else:
            try:
                return b.decode("utf-8")
            except UnicodeDecodeError:
                return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _select(options: list[tuple[str, str]], default: int = 0) -> str:
    """Arrow-key navigable menu.  Falls back to plain input if no TTY.

    options: [(value, label), ...]
    default: index of default selection
    """
    n = len(options)
    labels = [label for _val, label in options]

    # Fallback for non-TTY (tests, pipes)
    if not sys.stdin.isatty():
        for i, label in enumerate(labels):
            mark = "→" if i == default else " "
            click.echo(f"  {mark} {label}")
        choice = click.prompt(
            "  输入选项",
            type=click.Choice([v for v, _ in options]),
            default=options[default][0],
            show_choices=False,
        )
        return choice.strip()

    idx = default

    def _redraw() -> None:
        """Clear from cursor and redraw all options, leaving cursor at top line."""
        sys.stdout.write("\033[J")  # Clear from cursor to end of screen
        for i, label in enumerate(labels):
            prefix = "❯" if i == idx else " "
            sys.stdout.write(f"\r\033[K  {prefix} {label}\n")
        # Move cursor back to first option
        sys.stdout.write(f"\033[{n}A")
        sys.stdout.flush()

    # Initial draw
    sys.stdout.write("\n")
    _redraw()

    while True:
        key = _read_key()
        if key == "enter":
            sys.stdout.write(f"\033[{n}B\n")
            sys.stdout.flush()
            return options[idx][0]
        elif key == "up":
            idx = (idx - 1) % n
            _redraw()
        elif key == "down":
            idx = (idx + 1) % n
            _redraw()
        elif key == "esc":
            return options[idx][0]


# ---------------------------------------------------------------------------
# Spinner — visual feedback during LLM / agent execution
# ---------------------------------------------------------------------------


class Spinner:
    """Braille spinner that runs in a background thread."""

    _chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "处理中") -> None:
        self.message = message
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        sys.stderr.write("\r" + " " * (len(self.message) + 6) + "\r")
        sys.stderr.flush()

    def _spin(self) -> None:
        for char in itertools.cycle(self._chars):
            if not self._running:
                break
            sys.stderr.write(f"\r  {char} {self.message}...")
            sys.stderr.flush()
            time.sleep(0.08)


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


class Repl:
    """Natural-language REPL that drives the CogniForge workflow."""

    def __init__(
        self,
        workflow: Workflow,
        agents: dict[str, object],
        task_engine: TaskEngine,
        llm: BaseLLMAdapter,
    ) -> None:
        self.workflow = workflow
        self.agents = agents
        self.task_engine = task_engine
        self.llm = llm
        self._last_printed_step: Optional[str] = None

    # ---- main loop -------------------------------------------------------

    def run(self) -> None:
        """Start (or resume) the interactive REPL."""
        if not self.workflow.is_started:
            self.workflow.start()

        step = self.workflow.current_step
        click.echo()
        click.echo(WELCOME_LINE_1)
        click.echo(WELCOME_LINE_2.format(step_label=_step_label(step)))
        click.echo(WELCOME_LINE_3)
        self._print_step_hint(step)
        self._last_printed_step = step.value if step else None
        click.echo()

        try:
            while True:
                step = self.workflow.current_step
                if step is None:
                    click.echo(WORKFLOW_COMPLETE)
                    user_input = click.prompt("cogniforge", default="").strip()
                    if user_input in ("/quit", "/exit", "/q"):
                        break
                    continue

                # Reprint hint when step changes
                step_key = step.value
                if step_key != self._last_printed_step:
                    self._print_step_hint(step)
                    self._last_printed_step = step_key

                user_input = click.prompt("cogniforge", default="").strip()

                # Review steps: empty input = approve
                if not user_input and step and step.value in REVIEW_STEPS:
                    if click.confirm(APPROVE_CONFIRM, default=True):
                        click.echo(self._exec_approve({"comment": ""}))
                    continue

                if not user_input:
                    continue

                # Slash commands
                if user_input.startswith("/"):
                    if self._handle_slash(user_input):
                        break
                    continue

                # Interpret via LLM (with spinner)
                spinner = Spinner(SPINNER_INTERPRETING)
                spinner.start()
                try:
                    action = self._natural_to_json(user_input)
                except Exception as exc:
                    spinner.stop()
                    click.echo(INTERPRET_FAIL.format(error=exc))
                    continue
                finally:
                    spinner.stop()

                if action is None:
                    continue

                # Execute
                try:
                    result_text = self._execute(action)
                    click.echo(result_text)
                except Exception as exc:
                    click.echo(AGENT_EXEC_ERROR.format(error=exc))

        except KeyboardInterrupt:
            click.echo(PAUSE_MESSAGE.format(step_label=_step_label(self.workflow.current_step)))

    # ---- step hints ------------------------------------------------------

    def _print_step_hint(self, step: Optional[DAGStep]) -> None:
        """Show a concise hint about what the user should do at this step."""
        if step is None:
            return

        if step.value in REVIEW_STEPS:
            click.echo(_draw_box(
                top_line=step.get_approval_prompt(),
                lines=["回车 ↵ → 审批通过，进入下一步", "Ctrl+C → 拒绝，返回修改"],
            ))
            return

        schema = AGENT_SCHEMAS.get(step.value)
        if schema is None:
            return

        title = f"{step.value.upper()}（{schema['agent']} agent）"
        click.echo(_draw_box(
            top_line=title,
            lines=[
                f"请描述: {schema.get('hint', '')}",
                "用自然语言描述即可，系统自动提取结构化数据。",
            ],
        ))

    # ---- slash commands --------------------------------------------------

    def _handle_slash(self, text: str) -> bool:
        """Handle built-in slash commands.  Returns True if REPL should exit."""
        cmd, _, _ = text.partition(" ")
        cmd = cmd.lower()

        if cmd in ("/quit", "/exit", "/q"):
            click.echo(QUIT_MESSAGE.format(step_label=_step_label(self.workflow.current_step)))
            return True

        if cmd == "/help":
            click.echo(HELP_TEXT)
            return False

        if cmd == "/status":
            self._show_status()
            return False

        if cmd == "/steps":
            self._show_steps()
            return False

        if cmd == "/skip":
            self._do_skip()
            return False

        if cmd == "/clear":
            self._do_clear()
            return False

        click.echo(UNKNOWN_CMD.format(cmd=cmd))
        return False

    # ---- LLM interpretation ----------------------------------------------

    def _natural_to_json(self, user_input: str) -> Optional[dict]:
        """Ask the LLM to convert natural language into a structured action."""
        step = self.workflow.current_step
        if step is None:
            return None

        step_value = step.value

        if step_value in REVIEW_STEPS:
            prompt = PROMPT_REVIEW.format(step_value=step_value, user_input=user_input)
        else:
            schema = AGENT_SCHEMAS.get(step_value, {})
            prompt = PROMPT_AGENT.format(
                step_value=step_value,
                agent_name=schema.get("agent", "unknown"),
                fields=schema.get("fields", ""),
                user_input=user_input,
            )

        response = self.llm.generate(prompt)
        raw = response.content if hasattr(response, "content") else str(response)

        try:
            return json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            click.echo(PARSE_RETRY)
            retry = self.llm.generate(prompt + PROMPT_RETRY_SUFFIX)
            raw2 = retry.content if hasattr(retry, "content") else str(retry)
            try:
                return json.loads(_extract_json(raw2))
            except json.JSONDecodeError:
                click.echo(PARSE_FAIL.format(raw=raw[:200]))
                return None

    # ---- action execution -------------------------------------------------

    def _execute(self, action: dict) -> str:
        action_type = action.get("action", "")

        if action_type == "run_agent":
            return self._exec_run_agent(action)
        elif action_type == "approve":
            return self._exec_approve(action)
        elif action_type == "reject":
            return self._exec_reject(action)
        elif action_type == "respond":
            return f"  {action.get('message', '...')}"
        else:
            return UNKNOWN_ACTION.format(action=action_type)

    def _exec_run_agent(self, action: dict) -> str:
        agent_role = action.get("agent", "")
        agent = self.agents.get(agent_role)
        if agent is None:
            return AGENT_NO_ROLE.format(role=agent_role)

        input_data = action.get("input", {})

        if agent_role == "dev" and "task" not in input_data:
            input_data["task"] = self._pick_or_create_task(input_data)

        spinner = Spinner(SPINNER_RUNNING.format(agent=agent_role))
        spinner.start()
        try:
            result = agent.run(input_data)
        finally:
            spinner.stop()

        status_icon = "✓" if result.get("status") == "success" else "✗"
        lines = [f"\n  [{status_icon}] {result.get('message', '')}"]
        for a in result.get("artifacts", []):
            abs_path = (Path.cwd() / a).resolve()
            link = f"\033]8;;file://{abs_path}\033\\{a}\033]8;;\033\\"
            lines.append(f"       {link}")

        step = self.workflow.current_step
        if step:
            action_choice = self._post_agent_menu(step)
            if action_choice == "approve":
                lines.append(self._exec_approve({"comment": ""}))
            elif action_choice == "reject":
                reason = click.prompt(REJECT_PROMPT, default=REJECT_DEFAULT)
                lines.append(self._exec_reject({"comment": reason}))
            elif action_choice == "retry":
                lines.append(f"  {CHOICE_RETRY}")

        return "\n".join(lines)

    def _post_agent_menu(self, step) -> str:
        """Interactive menu shown after each agent execution."""
        click.echo(_draw_box(
            top_line=step.get_approval_prompt(),
            lines=["使用 ↑↓ 选择，回车确认"],
            bottom_close=False,
        ))
        return _select([
            ("approve", CHOICE_APPROVE),
            ("reject", CHOICE_REJECT),
            ("retry", CHOICE_RETRY),
        ], default=0)

    def _exec_approve(self, action: dict) -> str:
        step = self.workflow.current_step
        if step is None:
            return NO_STEP_APPROVE

        self.workflow.approve(comment=action.get("comment", ""), approver="repl_user")
        next_step = self.workflow.advance()

        lines = [APPROVE_OK.format(step=step.value)]
        if next_step:
            lines.append(APPROVE_NEXT.format(step_label=_step_label(next_step)))
        else:
            lines.append(APPROVE_DONE)
        return "\n".join(lines)

    def _exec_reject(self, action: dict) -> str:
        step = self.workflow.current_step
        if step is None:
            return NO_STEP_REJECT

        comment = action.get("comment", REJECT_DEFAULT)
        self.workflow.reject(comment=comment, approver="repl_user")
        return "\n".join([
            REJECT_OK.format(step=step.value),
            REJECT_REASON.format(reason=comment),
            REJECT_HINT,
        ])

    # ---- DevAgent task resolution ----------------------------------------

    def _pick_or_create_task(self, input_data: dict) -> Task:
        module = input_data.get("module", "main")
        ready = [t for t in self.task_engine.list_tasks() if t.status == TaskStatus.PENDING]
        if ready:
            return ready[0]

        try:
            return self.task_engine.create_task(
                name=f"实现 {module}",
                module=module,
                description=input_data.get("description", f"{module} 模块代码"),
            )
        except Exception:
            return Task(
                task_id=f"{module}-001",
                name=f"实现 {module}",
                module=module,
                description="REPL 自动创建",
            )

    # ---- status display --------------------------------------------------

    def _show_status(self) -> None:
        state = self.workflow.get_state()
        click.echo(STATUS_WORKFLOW.format(workflow_id=state.get("workflow_id", "N/A")))
        click.echo(STATUS_STARTED.format(started=state["started"]))
        click.echo(STATUS_STEP.format(step=state["current_step"] or "(none)"))
        click.echo(STATUS_AWAITING.format(awaiting=state["awaiting_approval"]))

        completed = state.get("completed_steps", [])
        if completed:
            click.echo(STATUS_COMPLETED.format(completed=", ".join(completed)))

        for step_name, record in state.get("approval_records", {}).items():
            icon = {"approved": "+", "rejected": "-"}.get(record.get("status"), "?")
            click.echo(f"    [{icon}] {step_name} — {record.get('comment', '')}")

        stats = self.task_engine.get_statistics()
        click.echo(STATUS_TASKS.format(
            total=stats["total"], pending=stats["pending"],
            done=stats["done"], failed=stats["failed"],
        ))

    def _show_steps(self) -> None:
        current = self.workflow.current_step
        state = self.workflow.get_state()
        completed = set(state.get("completed_steps", []))

        click.echo()
        for s in DAGStep:
            if DAGStep.from_string(s.value) == current:
                prefix = "→"
            elif s.value in completed:
                prefix = "✓"
            else:
                prefix = " "
            tag = " [评审]" if s.value in REVIEW_STEPS else ""
            click.echo(f"  {prefix} {s.value}{tag}")

    def _do_skip(self) -> None:
        step = self.workflow.current_step
        if step is None:
            click.echo(NO_STEP_APPROVE)
            return
        self.workflow.approve(comment="skipped", approver="repl_user")
        next_step = self.workflow.advance()
        click.echo(SKIP_OK.format(step=step.value))
        if next_step:
            click.echo(SKIP_NEXT.format(step_label=_step_label(next_step)))
        else:
            click.echo(APPROVE_DONE)

    def _do_clear(self) -> None:
        self.workflow.reset()
        self.workflow.start()
        click.echo(CLEAR_OK)
        click.echo(CLEAR_CURRENT.format(step_label=_step_label(self.workflow.current_step)))
