"""REPL — interactive natural-language workflow session (Claude Code style)."""

from __future__ import annotations

import itertools
import json
import re
import sys
import threading
import time
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
    CHOICE_PROMPT,
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
    """Terminal display width — CJK characters count as 2."""
    w = 0
    for ch in text:
        if ord(ch) > 0x2000:  # broad coverage for CJK + full-width
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
    max_w = max(_display_width(ln) for ln in all_lines)

    def _pad(ln: str, fill: str = " ") -> str:
        return ln + fill * (max_w - _display_width(ln))

    # Top: ╭─ title ───────────╮  (filled with ─ after title)
    title_dw = _display_width(top_line)
    # Space before title, space after, then fill with ─
    fill_w = max_w - title_dw - 2  # 2 = leading space + trailing space
    if fill_w >= 0:
        top = f"  ╭─ {top_line} {'─' * fill_w}─╮"
    else:
        top = f"  ╭─ {top_line} ─╮"

    body = [f"  │ {_pad(ln)} │" for ln in lines]
    bottom = f"  ╰─{'─' * max_w}─╯" if bottom_close else None

    return "\n".join([top] + body + ([bottom] if bottom else []))


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
            lines.append(f"       {a}")

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
            lines=[
                f"[approve] {CHOICE_APPROVE}",
                f"[reject]  {CHOICE_REJECT}",
                f"[retry]   {CHOICE_RETRY}",
            ],
            bottom_close=False,
        ))
        choice = click.prompt(
            CHOICE_PROMPT,
            type=click.Choice(["approve", "reject", "retry"]),
            default="approve",
            show_choices=False,
            prompt_suffix=" → ",
        ).strip()
        return choice

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
