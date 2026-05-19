"""REPL — interactive natural-language workflow session (Claude Code style)."""

from __future__ import annotations

import itertools
import json
import os
import re
import readline
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
    PROMPT_AGENT_PRD,
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
# Multi-line input helper
# ---------------------------------------------------------------------------


def _collect_multiline(prompt: str) -> list[str]:
    """Collect multiple lines of input until an empty line."""
    lines: list[str] = []
    while True:
        line = input(prompt)
        if not line.strip():
            break
        lines.append(line)
    return lines


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
        agent: BaseLLMAdapter,
    ) -> None:
        self.workflow = workflow
        self.agents = agents
        self.task_engine = task_engine
        self.agent = agent
        self._last_printed_step: Optional[str] = None
        self._last_prd_input: dict = {}  # stored for retry modification

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
                    user_input = input("cogniforge []: ").strip()
                    if user_input in ("/quit", "/exit", "/q"):
                        break
                    continue

                # Reprint hint when step changes
                step_key = step.value
                if step_key != self._last_printed_step:
                    self._print_step_hint(step)
                    self._last_printed_step = step_key

                user_input = input("cogniforge []: ").strip()

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

                # PRD step: LLM decides if more info needed, wizard fills gaps
                if (step and step.value == "prd"
                        and action.get("action") == "respond"):
                    try:
                        seed = action.get("input", {})
                        click.echo(f"\n  {action.get('message', '需要补充一些信息')}")
                        result = self._wizard_prd(seed=seed, initial=user_input)
                        click.echo(result or "")
                    except (KeyboardInterrupt, EOFError):
                        click.echo("\n  ⚠ 已取消\n")
                    continue

                # Execute
                try:
                    result_text = self._execute(action)
                    click.echo(result_text)
                except Exception as exc:
                    click.echo(AGENT_EXEC_ERROR.format(error=exc))

        except (KeyboardInterrupt, EOFError):
            click.echo(PAUSE_MESSAGE.format(step_label=_step_label(self.workflow.current_step)))

    # ---- card-based PRD wizard -------------------------------------------

    # ANSI color codes for card headers
    _CARD_COLORS = {
        "purple": "\033[35m",
        "blue":   "\033[34m",
        "cyan":   "\033[36m",
        "green":  "\033[32m",
        "amber":  "\033[33m",
        "reset":  "\033[0m",
    }

    def _card_header(self, icon: str, title: str, color: str = "blue") -> None:
        """Draw a colored card header line."""
        c = self._CARD_COLORS.get(color, self._CARD_COLORS["blue"])
        width = 52
        text = f"  {icon}  {title}  "
        pad = width - _display_width(text)
        click.echo(f"\n  {c}┌{text}{'─' * max(pad, 0)}┐{self._CARD_COLORS['reset']}")

    def _card_hint(self, text: str) -> None:
        """Draw a hint line inside the card."""
        click.echo(f"  │  {text}")

    def _card_prompt(self, prompt: str = "> ") -> str:
        """Read input inside a card context."""
        return input(f"  │  {prompt}").strip()

    def _wizard_prd(self, seed: dict | None = None, initial: str = "") -> str | None:
        """Card-based PRD wizard — only shows cards for missing fields.

        Args:
            seed: Already-extracted fields from a prior LLM pass.
            initial: The user's original natural-language input.

        Returns the approval result string, or None if user cancelled.
        """
        click.echo()
        seed = seed or {}

        # What we already have
        title = seed.get("title", "")
        overview = seed.get("overview", "")
        reqs = seed.get("requirements", [])
        stories = seed.get("user_stories", [])
        priorities = seed.get("priorities", {})

        # --- Card 1: 项目名称 (only if missing) ---
        if not title:
            self._card_header("📋", "项目名称", "purple")
            self._card_hint("这个项目叫什么名字？")
            if initial:
                self._card_hint(f"\033[2m从你的描述中提取: {initial[:60]}...\033[0m")
            title = input("  > ").strip()
        if not title:
            click.echo("  ⚠ 已取消")
            return None

        # --- Card 2: 项目概述 (only if missing) ---
        if not overview:
            self._card_header("📄", "项目概述", "blue")
            self._card_hint(f"「{title}」要解决什么问题？目标用户是谁？")
            overview = input("  > ").strip()
        if not overview:
            overview = title

        # --- Card 3: 功能需求 (only if missing) ---
        requirements_text = ""
        if not reqs:
            self._card_header("📝", "功能需求", "cyan")
            self._card_hint("需要哪些核心功能？用自然语言描述。")
            self._card_hint("（例如：「用户注册 - 支持手机号和邮箱」）")
            lines = _collect_multiline("  > ")
            requirements_text = "\n".join(lines) if lines else ""

        # --- Card 4: 用户故事 (only if missing) ---
        stories_text = ""
        if not stories:
            self._card_header("👥", "用户故事", "green")
            self._card_hint("谁会使用这个系统？他们想做什么？")
            self._card_hint("（例如：「作为学生，我想要查看成绩单」）")
            lines = _collect_multiline("  > ")
            stories_text = "\n".join(lines) if lines else ""

        # --- Card 5: 优先级 (only if missing) ---
        priorities_text = ""
        if not priorities:
            self._card_header("🎯", "优先级", "amber")
            self._card_hint("哪些功能最重要？按高/中/低标注优先级。")
            self._card_hint("（直接回车跳过）")
            priorities_text = input("  > ").strip()

        # --- Build structured input via LLM ---
        spinner = Spinner(SPINNER_INTERPRETING)
        spinner.start()
        try:
            schema = AGENT_SCHEMAS.get("prd", {})
            parts = [
                f"当前工作流步骤: prd",
                f"要运行的 agent: pm",
                f"需要的 JSON 字段: {schema.get('fields', '')}",
                "",
                f"用户初始描述: {initial}",
                f"已有字段: title={title!r}, overview={overview!r}",
                f"已有 requirements: {json.dumps(reqs, ensure_ascii=False)}",
                f"已有 user_stories: {json.dumps(stories, ensure_ascii=False)}",
                f"已有 priorities: {json.dumps(priorities, ensure_ascii=False)}",
            ]
            if requirements_text:
                parts.append(f"补充需求描述: {requirements_text}")
            if stories_text:
                parts.append(f"补充用户故事: {stories_text}")
            if priorities_text:
                parts.append(f"补充优先级: {priorities_text}")
            parts.extend([
                "",
                '返回 JSON: {"action": "run_agent", "agent": "pm", "input": {从以上信息提取}}',
                "如果信息仍然不足以生成 PRD，返回 run_agent 并尽力填充已有字段。",
                "只返回合法 JSON。不要 markdown。不要多余文字。",
            ])
            prompt = "\n".join(parts)
            response = self.agent.generate(prompt)
            raw = response.content if hasattr(response, "content") else str(response)
            action = json.loads(_extract_json(raw))
        except Exception:
            # Fallback: build input directly
            input_data = {
                "title": title,
                "overview": overview,
                "requirements": reqs or [
                    {"name": "核心需求", "description": requirements_text or initial,
                     "acceptance_criteria": []}
                ],
                "user_stories": stories or [
                    {"role": "用户", "action": stories_text or initial, "goal": ""}
                ],
                "priorities": priorities or {},
            }
            action = {"action": "run_agent", "agent": "pm", "input": input_data}
        finally:
            spinner.stop()

        click.echo()
        return self._execute(action)

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
        elif step_value == "prd":
            schema = AGENT_SCHEMAS.get(step_value, {})
            prompt = PROMPT_AGENT_PRD.format(
                fields=schema.get("fields", ""),
                user_input=user_input,
            )
        else:
            schema = AGENT_SCHEMAS.get(step_value, {})
            prompt = PROMPT_AGENT.format(
                step_value=step_value,
                agent_name=schema.get("agent", "unknown"),
                fields=schema.get("fields", ""),
                user_input=user_input,
            )

        response = self.agent.generate(prompt)
        raw = response.content if hasattr(response, "content") else str(response)

        try:
            return json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            click.echo(PARSE_RETRY)
            retry = self.agent.generate(prompt + PROMPT_RETRY_SUFFIX)
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

        # Store PRD input for retry modification
        if agent_role == "pm":
            self._last_prd_input = dict(input_data)

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

        # Print artifacts immediately so the user can preview before approving
        click.echo("\n".join(lines))

        step = self.workflow.current_step
        if step:
            action_choice = self._post_agent_menu(step)
            if action_choice == "approve":
                return self._exec_approve({"comment": ""})
            elif action_choice == "reject":
                reason = click.prompt(REJECT_PROMPT, default=REJECT_DEFAULT)
                return self._exec_reject({"comment": reason})
            elif action_choice == "retry":
                return self._exec_retry_modify(agent_role)

        return ""

    def _exec_retry_modify(self, agent_role: str) -> str:
        """Retry with modifications: prompt user, let LLM merge changes, re-run agent."""
        if agent_role != "pm" or not self._last_prd_input:
            return f"  {CHOICE_RETRY}"

        click.echo()
        self._card_header("✏️", "修改内容", "amber")
        self._card_hint("请描述需要修改的地方，LLM 会基于上一版进行修改。")
        modifications = input("  > ").strip()
        if not modifications:
            return "  ⚠ 未输入修改内容，已取消"

        # LLM merges original input + modification request
        spinner = Spinner("正在根据你的反馈修改")
        spinner.start()
        try:
            schema = AGENT_SCHEMAS.get("prd", {})
            prompt = (
                f"当前工作流步骤: prd\n"
                f"要运行的 agent: pm\n"
                f"需要的 JSON 字段: {schema.get('fields', '')}\n\n"
                f"当前 PRD 数据:\n{json.dumps(self._last_prd_input, ensure_ascii=False, indent=2)}\n\n"
                f"用户要求做以下修改:\n{modifications}\n\n"
                f"基于用户的修改要求，返回修改后的完整 PRD 数据。\n"
                f'返回 JSON: {{"action": "run_agent", "agent": "pm", '
                f'"input": {{...修改后的完整字段...}} }}\n'
                f"只返回合法 JSON。不要 markdown。不要多余文字。"
            )
            response = self.agent.generate(prompt)
            raw = response.content if hasattr(response, "content") else str(response)
            action = json.loads(_extract_json(raw))
        except Exception:
            # Fallback: keep original data unchanged
            action = {"action": "run_agent", "agent": "pm",
                       "input": self._last_prd_input}
        finally:
            spinner.stop()

        # Re-execute: run agent + show links + show menu (recursive call)
        return self._exec_run_agent(action)

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
