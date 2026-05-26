"""REPL — interactive natural-language workflow session (Claude Code style)."""

from __future__ import annotations

import itertools
import json
import os
import re
import select
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Windows line-editing support
try:
    import readline  # Unix
except ImportError:
    try:
        import pyreadline3 as readline  # Windows
    except ImportError:
        readline = None

# Windows raw-terminal support
if sys.platform == "win32":
    import msvcrt
else:
    import termios
    import tty
import uuid
from pathlib import Path
from typing import Optional

import click

from cogniforge.core.constants import TaskStatus
from cogniforge.interface_checker import check as check_interfaces, format_report
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
    CHOICE_MODIFY,
    MODIFY_SESSION_SYSTEM_PROMPTS,
    INTERACTIVE_STEPS,
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
    DESIGN_STEP_CHOICES,
    LLD_MODULES_FOUND,
    LLD_AUTO_ALL_CHOICE,
    LLD_PROGRESS,
    WBS_MODULES_FOUND,
    WBS_AUTO_ALL_CHOICE,
    WBS_PROGRESS,
    STEP_SEPARATOR,
)

# ---------------------------------------------------------------------------
# Terminal color theme
# ---------------------------------------------------------------------------

C_PURPLE = "\033[35m"
C_GREEN  = "\033[32m"
C_RED    = "\033[31m"
C_AMBER  = "\033[33m"
C_DIM    = "\033[2m"
C_RESET  = "\033[0m"

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


def _draw_box(top_line: str, lines: list[str], bottom_close: bool = True,
              min_width: int = 0) -> str:
    """Draw a CJK-aware aligned box.

    top_line: title in the top border
    lines: body lines
    min_width: minimum content width (used when body lines will expand dynamically)
    """
    all_lines = [top_line] + lines
    content_w = max(_display_width(ln) for ln in all_lines)
    # Ensure room for ─ padding around title in top border (needs ≥2 extra cols)
    max_w = max(content_w, _display_width(top_line) + 2, min_width)

    def _pad(ln: str) -> str:
        return ln + " " * (max_w - _display_width(ln))

    # Top: ╭─ title ───────╮  (purple borders)
    P, R = C_PURPLE, C_RESET
    fill_w = max_w - _display_width(top_line) - 2  # always ≥ 0 now
    top = f"  {P}╭─{R} {top_line} {P}{'─' * fill_w}─╮{R}"
    body = [f"  {P}│{R} {_pad(ln)} {P}│{R}" for ln in lines]
    bottom = f"  {P}╰─{'─' * max_w}─╯{R}" if bottom_close else None

    return "\n".join([top] + body + ([bottom] if bottom else []))


# ---------------------------------------------------------------------------
# Arrow-key select menu
# ---------------------------------------------------------------------------


def _read_key() -> str:
    """Read a single keypress from stdin in raw mode. Returns 'up'/'down'/'enter'/esc/char."""
    if sys.platform == "win32":
        return _read_key_win()
    else:
        return _read_key_unix()


def _read_key_win() -> str:
    """Windows implementation using msvcrt."""
    ch = msvcrt.getwch()
    if ch == "\r" or ch == "\n":
        return "enter"
    if ch == "\x1b":
        # Arrow keys: \x1b [ A / B / C / D — but on Windows, msvcrt.getwch
        # returns \xe0 or \x00 as first byte for special keys
        return "esc"
    if ch == "\x00" or ch == "\xe0":
        # Extended key prefix — second call gives the actual key
        ch2 = msvcrt.getwch()
        if ch2 == "H":
            return "up"
        elif ch2 == "P":
            return "down"
        elif ch2 == "K":
            return "left"
        elif ch2 == "M":
            return "right"
        return ""
    return ch


def _read_key_unix() -> str:
    """Unix implementation using termios/tty."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        b = os.read(fd, 1)
        if b == b"\x1b":
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


def _select(options: list[tuple[str, str]], default: int = 0,
            colors: list[str] | None = None) -> str:
    """Arrow-key navigable menu.  Falls back to plain input if no TTY.

    options: [(value, label), ...]
    default: index of default selection
    colors: optional list of ANSI color codes per option (applied when highlighted)
    """
    n = len(options)
    labels = [label for _val, label in options]

    # Fallback for non-TTY (tests, pipes)
    if not sys.stdin.isatty():
        for i, label in enumerate(labels):
            c = (colors[i] if colors and i < len(colors) else "") if i == default else ""
            r = C_RESET if c else ""
            mark = f"{c}→{r}" if i == default else " "
            click.echo(f"  {mark} {c}{label}{r}")
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
            if i == idx:
                c = colors[i] if colors and i < len(colors) else C_PURPLE
                sys.stdout.write(f"\r\033[K  {c}❯ {label}{C_RESET}\n")
            else:
                sys.stdout.write(f"\r\033[K     {label}\n")
        # Move cursor back to first option
        sys.stdout.write(f"\033[{n}A")
        sys.stdout.flush()

    # Initial draw
    sys.stdout.write("\n")
    _redraw()

    while True:
        try:
            key = _read_key()
        except KeyboardInterrupt:
            key = "\x03"
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
        elif key == "\x03":  # Ctrl+C — cancel
            sys.stdout.write(f"\033[J")
            sys.stdout.flush()
            return None


# ---------------------------------------------------------------------------
# Spinner — visual feedback during LLM / agent execution
# ---------------------------------------------------------------------------


class Spinner:
    """Braille spinner that runs in a background thread.

    When ``message`` is updated externally (e.g. by a progress callback),
    the next spin cycle picks it up and clears any leftover characters.
    Automatically appends an elapsed-time indicator for long-running steps.
    """

    _chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "处理中") -> None:
        self._base_message = message
        self._running = False
        self._thread: threading.Thread | None = None
        self._max_len = 0
        self._start_time = 0.0

    @property
    def message(self) -> str:
        return self._base_message

    @message.setter
    def message(self, value: str) -> None:
        self._base_message = value
        self._start_time = time.time()  # reset elapsed timer on each new status

    def start(self) -> None:
        self._running = True
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        sys.stderr.write("\r" + " " * max(self._max_len + 10, 40) + "\r")
        sys.stderr.flush()

    def _spin(self) -> None:
        for char in itertools.cycle(self._chars):
            if not self._running:
                break
            elapsed = int(time.time() - self._start_time)
            if elapsed >= 2:
                display = f"{self._base_message} ({elapsed}s)"
            else:
                display = self._base_message
            text = f"  {C_AMBER}{char}{C_RESET} {display}"
            self._max_len = max(self._max_len, _display_width(display))
            pad = max(0, self._max_len - _display_width(display))
            sys.stderr.write(f"\r{text}{' ' * pad}")
            sys.stderr.flush()
            time.sleep(0.1)


class ParallelProgress:
    """Multi-line live status panel for parallel agent tasks.

    Renders one line per task on stderr, refreshed in-place via ANSI
    escape codes.  Each line shows a spinner (running), checkmark (done),
    or cross (failed), plus the current phase and elapsed seconds.

    Caller should:
      1. register() all tasks
      2. start() the panel
      3. call mark_done() as each task finishes (no stop/start needed)
      4. call stop() once after ALL tasks finish
      5. print results to stdout AFTER stop()
    """

    _SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, str] = {}          # name -> phase
        self._statuses: dict[str, str] = {}       # name -> "running"|"success"|"failed"
        self._start_times: dict[str, float] = {}  # name -> time.time()
        self._frame = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self._lines = 0

    # -- public API -------------------------------------------------------

    def register(self, name: str) -> None:
        with self._lock:
            self._tasks[name] = "准备中"
            self._statuses[name] = "running"
            self._start_times[name] = time.time()

    def update(self, name: str, phase: str) -> None:
        with self._lock:
            if name in self._tasks:
                self._tasks[name] = phase

    def mark_done(self, name: str, success: bool) -> None:
        """Mark a task as finished (✓ or ✗) without removing it from the panel."""
        with self._lock:
            if name in self._statuses:
                self._statuses[name] = "success" if success else "failed"

    def remove(self, name: str) -> None:
        with self._lock:
            self._tasks.pop(name, None)
            self._statuses.pop(name, None)
            self._start_times.pop(name, None)

    @property
    def active(self) -> bool:
        with self._lock:
            return len(self._tasks) > 0

    def start(self) -> None:
        if not self.active:
            return
        self._running = True
        self._lines = 0
        self._thread = threading.Thread(target=self._draw_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
        # Erase every line the panel previously rendered
        for _ in range(self._lines):
            sys.stderr.write("\r\033[K\033[A")
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()
        self._lines = 0

    # -- internals --------------------------------------------------------

    def _draw_loop(self) -> None:
        while self._running:
            self._draw()
            time.sleep(0.1)

    def _draw(self) -> None:
        with self._lock:
            if not self._tasks:
                return

            self._frame += 1
            frame = self._frame
            now = time.time()

            entries = sorted(self._tasks.items(), key=lambda x: x[0])

            lines: list[str] = []
            for name, phase in entries:
                elapsed = int(now - self._start_times.get(name, now))
                elapsed_str = f" ({elapsed}s)" if elapsed >= 1 else ""
                status = self._statuses.get(name, "running")

                if status == "success":
                    lines.append(
                        f"  {C_GREEN}✓{C_RESET} {name}  [{phase}]{elapsed_str}"
                    )
                elif status == "failed":
                    lines.append(
                        f"  {C_RED}✗{C_RESET} {name}  [{phase}]{elapsed_str}"
                    )
                else:
                    char = self._SPINNER_CHARS[
                        (frame + hash(name)) % len(self._SPINNER_CHARS)
                    ]
                    lines.append(
                        f"  {C_AMBER}{char}{C_RESET} {name}  [{phase}]{elapsed_str}"
                    )

            # Move cursor back up to overwrite previous render
            if self._lines > 0:
                sys.stderr.write(f"\033[{self._lines}A")

            for line in lines:
                sys.stderr.write("\r\033[K" + line + "\n")

            # Clear leftover lines when task count shrinks
            if len(lines) < self._lines:
                for _ in range(self._lines - len(lines)):
                    sys.stderr.write("\r\033[K\n")
                sys.stderr.write(f"\033[{self._lines - len(lines)}A")

            self._lines = len(lines)
            sys.stderr.flush()


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
        wiki_system=None,
    ) -> None:
        self.workflow = workflow
        self.agents = agents
        self.task_engine = task_engine
        self.agent = agent
        self.wiki_system = wiki_system
        self._last_printed_step: Optional[str] = None

    # ---- module discovery ------------------------------------------------

    def _get_sad_modules(self) -> list[dict]:
        """Read the latest SAD JSON and extract the component list."""
        import glob as _glob
        from pathlib import Path as _Path

        pattern = str(_Path.cwd() / ".cogniforge/wiki/sad/*.json")
        files = sorted(_glob.glob(pattern))
        if not files:
            return []
        try:
            with open(files[-1], "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("components", [])
        except Exception:
            return []

    def _get_lld_modules(self) -> list[dict]:
        """Return SAD components that have an existing LLD JSON file."""
        import glob as _glob
        from pathlib import Path as _Path

        sad_modules = self._get_sad_modules()
        lld_dir = _Path.cwd() / ".cogniforge/wiki/lld"
        result: list[dict] = []
        for comp in sad_modules:
            mod_name = comp.get("name", "")
            pattern = str(lld_dir / mod_name / "*.json")
            files = sorted(_glob.glob(pattern))
            if files:
                result.append(comp)
        return result

    @staticmethod
    def _lld_layer(comp: dict) -> int:
        """Return dependency layer for topological sort.
        Layer 0 (database/infrastructure) → 1 (service) → 2 (gateway) → 3 (frontend).
        SAD component types are normalized to canonical values by ArchitectAgent."""
        ctype = comp.get("type", "service")
        if ctype in ("database", "infrastructure"):
            return 0
        if ctype == "service":
            return 1
        if ctype == "gateway":
            return 2
        if ctype == "frontend":
            return 3
        return 1  # fallback to service layer

    _LAYER_LABELS = {0: "基础设施", 1: "业务服务", 2: "网关", 3: "前端"}

    @staticmethod
    def _print_lld_result(mod_name: str, result: dict) -> None:
        """Print a single LLD generation result."""
        status_icon = (
            f"{C_GREEN}✓{C_RESET}"
            if result.get("status") == "success"
            else f"{C_RED}✗{C_RESET}"
        )
        click.echo(f"  [{status_icon}] {result.get('message', '')}")
        for a in result.get("artifacts", []):
            if a.endswith(".html"):
                abs_path = (Path.cwd() / a).resolve()
                link = f"\033]8;;file://{abs_path}\033\\{a}\033]8;;\033\\"
                click.echo(f"       {link}")

    def _exec_lld_auto_all(self, modules: list[dict]) -> str:
        """Generate LLD for all modules in dependency-layered order.
        Modules within the same layer run in parallel."""
        from collections import defaultdict
        from concurrent.futures import ThreadPoolExecutor, as_completed

        ordered = sorted(modules, key=self._lld_layer)
        total = len(ordered)

        # Group by layer
        layer_groups: dict[int, list[dict]] = defaultdict(list)
        for comp in ordered:
            layer_groups[self._lld_layer(comp)].append(comp)

        results: list[dict] = []
        agent = self.agents.get("design")
        counter = 0

        for layer_num in sorted(layer_groups.keys()):
            group = layer_groups[layer_num]
            label = self._LAYER_LABELS.get(layer_num, f"Layer {layer_num}")
            click.echo(
                C_DIM + f"\n  ══ Layer {layer_num}: {label} "
                f"({len(group)} 模块) ══" + C_RESET
            )

            if len(group) == 1:
                # Single module — no parallelism overhead
                comp = group[0]
                counter += 1
                mod_name = comp.get("name", "unknown")
                click.echo(
                    f"\n  [{C_AMBER}{counter}/{total}{C_RESET}] "
                    + LLD_PROGRESS.format(module=mod_name)
                )
                input_data = {
                    "module": mod_name,
                    "title": f"LLD - {mod_name}",
                    "overview": comp.get("description", ""),
                }
                spinner = Spinner(SPINNER_RUNNING.format(agent="design"))
                spinner.start()
                try:
                    result = agent.run(input_data)
                finally:
                    spinner.stop()
                self._print_lld_result(mod_name, result)
                results.append(result)
            else:
                # Parallel within layer
                max_w = min(len(group), 10)
                batch_start = counter + 1
                batch_end = counter + len(group)
                counter = batch_end
                click.echo(
                    f"\n  [{C_AMBER}{batch_start}-{batch_end}/{total}{C_RESET}] "
                    f"并行生成 {len(group)} 个 {label} 模块 ..."
                )

                progress = ParallelProgress()
                result_map: dict[str, dict] = {}

                with ThreadPoolExecutor(max_workers=max_w) as executor:
                    future_map: dict = {}
                    for comp in group:
                        mod_name = comp.get("name", "unknown")
                        progress.register(mod_name)
                        input_data = {
                            "module": mod_name,
                            "title": f"LLD - {mod_name}",
                            "overview": comp.get("description", ""),
                        }
                        def _cb(phase: str, _name: str = mod_name) -> None:
                            progress.update(_name, phase)
                        future = executor.submit(agent.run, input_data, _cb)
                        future_map[future] = mod_name

                    progress.start()
                    try:
                        for future in as_completed(future_map):
                            mod_name = future_map[future]
                            try:
                                result = future.result()
                                success = result.get("status") == "success"
                            except Exception as e:
                                result = {"status": "failed", "message": str(e)}
                                success = False
                            progress.mark_done(mod_name, success)
                            result_map[mod_name] = result
                            results.append(result)
                    finally:
                        progress.stop()

                # Print results in group submission order
                for comp in group:
                    mod_name = comp.get("name", "unknown")
                    if mod_name in result_map:
                        self._print_lld_result(mod_name, result_map[mod_name])

        # Summary
        success_count = sum(1 for r in results if r.get("status") == "success")
        click.echo(
            f"\n  {C_GREEN}{success_count}/{total} 模块 LLD 生成成功{C_RESET}"
        )

        # Post-agent menu (approve/reject for the whole LLD step)
        step = self.workflow.current_step
        if step:
            action_choice = self._post_agent_menu(step)
            if action_choice == "approve":
                return self._exec_approve({"comment": ""})
            elif action_choice == "reject":
                reason = click.prompt(REJECT_PROMPT, default=REJECT_DEFAULT)
                return self._exec_reject({"comment": reason})

        return ""

    def _exec_wbs_auto_all(self, modules: list[dict]) -> str:
        """Generate WBS for all modules in parallel.

        Each module gets its own LLM call; all modules run concurrently
        via ThreadPoolExecutor.  Task registration (git I/O) runs
        sequentially after all LLM work completes.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from datetime import datetime
        from cogniforge.wbs.enriched_wbs_assembler import WBSAssembler, WBSResult
        from cogniforge.wiki.wiki_renderer import render_wbs_module_html

        total = len(modules)
        agent = self.agents.get("techlead")
        if agent is None:
            return AGENT_NO_ROLE.format(role="techlead")

        # ── Build (module_name, lld_path) specs ──
        specs: list[tuple[str, Path]] = []
        for comp in modules:
            mod_name = comp.get("name", "unknown")
            lld_dir = Path.cwd() / ".cogniforge/wiki/lld" / mod_name
            lld_files = sorted(lld_dir.glob("*.json"))
            if lld_files:
                specs.append((mod_name, lld_files[-1]))

        if not specs:
            return f"  [{C_RED}✗{C_RESET}] 没有找到 LLD JSON 文件"

        total = len(specs)
        max_w = min(total, 10)
        module_names = ", ".join(name for name, _ in specs)
        click.echo(
            f"\n  [{C_AMBER}1-{total}/{total}{C_RESET}] "
            f"并行 WBS ({max_w} 并发): {module_names}"
        )

        # ── Per-module worker (runs in thread) ──
        def _assemble_one(mod_name: str, lld_path: Path,
                          progress_cb=None):
            """Run full assemble pipeline for one module.  Each thread gets
            its own WBSAssembler so there is no shared mutable state."""
            assembler = WBSAssembler(
                agent.wiki_system, agent.task_engine, agent.agent,
                conventions=agent.config.build_repo_conventions(),
            )
            return assembler.assemble(mod_name, lld_path,
                                       progress_callback=progress_cb)

        # ── Parallel phase: LLM enrichment per module ──
        progress = ParallelProgress()
        future_map: dict = {}
        with ThreadPoolExecutor(max_workers=max_w) as executor:
            for mod_name, lld_path in specs:
                progress.register(mod_name)
                def _wbs_cb(phase: str, _name: str = mod_name) -> None:
                    progress.update(_name, phase)
                future = executor.submit(_assemble_one, mod_name, lld_path, _wbs_cb)
                future_map[future] = mod_name

            progress.start()
            per_module: dict[str, WBSResult | Exception] = {}
            try:
                for future in as_completed(future_map):
                    mod_name = future_map[future]
                    try:
                        per_module[mod_name] = future.result()
                        success = True
                    except Exception as exc:
                        per_module[mod_name] = exc
                        success = False
                    progress.mark_done(mod_name, success)
            finally:
                progress.stop()

        # ── Sequential phase: register tasks & print (git I/O serialised) ──
        sequential_spinner = Spinner("注册 WBS 任务到知识库")
        sequential_spinner.start()
        final_results: list[dict] = []
        try:
            for mod_name, _ in specs:
                raw = per_module.get(mod_name)
                if raw is None:
                    err = {"status": "failed", "message": "no result (unexpected)"}
                    self._print_lld_result(mod_name, err)
                    final_results.append(err)
                    continue

                if isinstance(raw, Exception):
                    err = {"status": "failed", "message": str(raw)}
                    self._print_lld_result(mod_name, err)
                    final_results.append(err)
                    continue

                # raw is WBSResult
                try:
                    count = agent._register_wbs_tasks(raw.tasks, mod_name)

                    # Render combined WBS HTML for this module
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    task_dicts = [
                        t if isinstance(t, dict) else (
                            t.to_json() if hasattr(t, "to_json") else {}
                        )
                        for t in raw.tasks
                    ]
                    html_path = render_wbs_module_html(
                        mod_name, task_dicts,
                        created=now, repo_path=Path.cwd(),
                    )
                    if html_path:
                        rel_html = html_path.relative_to(Path.cwd()).as_posix()
                        self.wiki_system.git_storage.repo.index.add([rel_html])

                    report = raw.coverage
                    coverage_msg = (
                        f", coverage={report.coverage_pct:.0f}%" if report else ""
                    )
                    res = agent.format_result(
                        status="success",
                        message=f"WBS: {count} tasks for {mod_name}{coverage_msg}",
                        data={"task_count": count},
                    )
                    self._print_lld_result(mod_name, res)
                    final_results.append(res)
                except Exception as exc:
                    err = {"status": "failed", "message": str(exc)}
                    self._print_lld_result(mod_name, err)
                    final_results.append(err)
        finally:
            sequential_spinner.stop()

        success_count = sum(1 for r in final_results if r.get("status") == "success")
        click.echo(
            f"\n  {C_GREEN}{success_count}/{total} 模块 WBS 生成成功{C_RESET}"
        )

        # ── Post-agent menu ──
        step = self.workflow.current_step
        if step:
            action_choice = self._post_agent_menu(step)
            if action_choice == "approve":
                return self._exec_approve({"comment": ""})
            elif action_choice == "reject":
                reason = click.prompt(REJECT_PROMPT, default=REJECT_DEFAULT)
                return self._exec_reject({"comment": reason})

        return ""

    # ---- main loop -------------------------------------------------------

    def run(self) -> None:
        """Start (or resume) the interactive REPL."""
        if not self.workflow.is_started:
            self.workflow.start()

        step = self.workflow.current_step
        click.echo()
        click.echo(f"  {C_PURPLE}CogniForge REPL{C_RESET}")
        click.echo(WELCOME_LINE_2.format(step_label=_step_label(step)))
        click.echo(C_DIM + WELCOME_LINE_3 + C_RESET)
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
                    click.echo(C_DIM + f"\n  {STEP_SEPARATOR}" + C_RESET)
                    self._print_step_hint(step)
                    self._last_printed_step = step_key

                # Auto-skip review steps — no user input needed
                if step and step.value in REVIEW_STEPS:
                    # For design_review: run interface consistency check
                    if step.value == "design_review":
                        result = check_interfaces(Path.cwd())
                        click.echo(format_report(result))
                        if result["status"] == "conflict":
                            click.echo(
                                f"\n  {C_AMBER}检测到接口契约冲突，请修复后再审批。{C_RESET}"
                            )
                            # Don't auto-approve — let user review violations
                            self.workflow.reject("interface consistency check failed")
                            continue
                    click.echo(self._exec_approve({"comment": ""}))
                    continue

                # Design steps (SAD/LLD/WBS): let user choose between manual and auto-design
                if step and step.value in DESIGN_STEP_CHOICES:
                    _, label_auto, label_manual, auto_prompt = DESIGN_STEP_CHOICES[step.value]

                    # Multi-module support
                    if step.value == "lld":
                        modules = self._get_sad_modules()
                    elif step.value == "wbs":
                        modules = self._get_lld_modules()
                    else:
                        modules = []

                    if step.value == "wbs" and len(modules) == 0:
                        click.echo(
                            f"\n  {C_AMBER}没有找到 LLD 文档，无法生成 WBS。"
                            f"请先完成 LLD 步骤。{C_RESET}"
                        )
                        continue

                    if step.value == "lld" and len(modules) > 1:
                        # Multi-module: offer "generate all" option
                        module_names = ", ".join(
                            c.get("name", "?") for c in modules
                        )
                        click.echo(
                            LLD_MODULES_FOUND.format(
                                count=len(modules), modules=module_names
                            )
                        )
                        choice = _select(
                            [
                                (
                                    "auto_all",
                                    LLD_AUTO_ALL_CHOICE.format(count=len(modules)),
                                ),
                                ("auto", label_auto),
                                ("manual", label_manual),
                            ],
                            default=0,
                        )
                        if choice is None:
                            continue
                        elif choice == "auto_all":
                            result_text = self._exec_lld_auto_all(modules)
                            click.echo(result_text)
                            continue
                        elif choice == "auto":
                            user_input = auto_prompt
                        else:
                            click.echo()
                            user_input = input("cogniforge []: ").strip()
                    elif step.value == "wbs" and len(modules) > 1:
                        # WBS multi-module: auto-decompose for all modules with LLD
                        module_names = ", ".join(
                            c.get("name", "?") for c in modules
                        )
                        click.echo(
                            WBS_MODULES_FOUND.format(
                                count=len(modules), modules=module_names
                            )
                        )
                        choice = _select(
                            [
                                (
                                    "auto_all",
                                    WBS_AUTO_ALL_CHOICE.format(count=len(modules)),
                                ),
                                ("auto", label_auto),
                                ("manual", label_manual),
                            ],
                            default=0,
                        )
                        if choice is None:
                            continue
                        elif choice == "auto_all":
                            result_text = self._exec_wbs_auto_all(modules)
                            click.echo(result_text)
                            continue
                        elif choice == "auto":
                            user_input = auto_prompt
                        else:
                            click.echo()
                            user_input = input("cogniforge []: ").strip()
                    else:
                        # Single module (or SAD) — if WBS has exactly 1 LLD module, go direct
                        if step.value == "wbs" and len(modules) == 1:
                            click.echo(
                                WBS_MODULES_FOUND.format(
                                    count=1, modules=modules[0].get("name", "?")
                                )
                            )
                            choice = _select(
                                [
                                    ("auto_all", WBS_AUTO_ALL_CHOICE.format(count=1)),
                                    ("auto", label_auto),
                                    ("manual", label_manual),
                                ],
                                default=0,
                            )
                            if choice is None:
                                continue
                            elif choice == "auto_all":
                                result_text = self._exec_wbs_auto_all(modules)
                                click.echo(result_text)
                                continue
                            elif choice == "auto":
                                user_input = auto_prompt
                            else:
                                click.echo()
                                user_input = input("cogniforge []: ").strip()
                        else:
                            choice = _select(
                                [
                                    ("auto", label_auto),
                                    ("manual", label_manual),
                                ],
                                default=0,
                            )
                            if choice is None:
                                continue
                            elif choice == "auto":
                                user_input = auto_prompt
                            else:
                                click.echo()
                                user_input = input("cogniforge []: ").strip()
                else:
                    user_input = input("cogniforge []: ").strip()

                if not user_input:
                    continue

                # Slash commands
                if user_input.startswith("/"):
                    if self._handle_slash(user_input):
                        break
                    continue

                # PRD step shortcut: skip LLM interpretation, go direct to agent
                if step and step.value == "prd":
                    lower = user_input.lower()
                    # Approve intent: direct approval without LLM
                    if lower in ("approve", "yes", "ok", "y", "审批", "通过", "确认"):
                        result_text = self._exec_approve({"comment": ""})
                        click.echo(result_text)
                        continue
                    # NL → run PM agent directly with raw text
                    result_text = self._exec_run_agent({
                        "agent": "pm",
                        "input": {"raw_text": user_input},
                    })
                    click.echo(result_text)
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
            click.echo(f"\n  {C_DIM}已退出。运行 'cogniforge repl' 可随时恢复。{C_RESET}")
            return

    # ---- card-based PRD wizard -------------------------------------------

    def _card_header(self, icon: str, title: str, color: str = "purple") -> None:
        """Draw a colored card header line."""
        c = {
            "purple": C_PURPLE,
            "blue":   "\033[34m",
            "cyan":   "\033[36m",
            "green":  C_GREEN,
            "amber":  C_AMBER,
        }.get(color, C_PURPLE)
        width = 52
        text = f"  {icon}  {title}  "
        pad = width - _display_width(text)
        click.echo(f"\n  {c}┌{text}{'─' * max(pad, 0)}┐{C_RESET}")

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
                self._card_hint(f"{C_DIM}从你的描述中提取: {initial[:60]}...{C_RESET}")
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

        # Design steps (SAD/LLD): choice menu handles input — don't show "请描述"
        if step.value in DESIGN_STEP_CHOICES:
            title, _, _, _ = DESIGN_STEP_CHOICES[step.value]
            click.echo(_draw_box(
                top_line=title,
                lines=["使用 ↑↓ 选择，回车确认"],
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

        if agent_role == "dev" and "task" not in input_data:
            input_data["task"] = self._pick_or_create_task(input_data)

        spinner = Spinner(f"[{agent_role}] {SPINNER_RUNNING.format(agent=agent_role)}")
        spinner.start()
        # Progress callback: update spinner text with tool-level detail
        def _on_progress(status: str):
            spinner.message = f"[{agent_role}] {status}"
        input_data["_progress_callback"] = _on_progress
        try:
            result = agent.run(input_data)
        finally:
            spinner.stop()

        if result.get("status") == "success":
            status_icon = f"{C_GREEN}✓{C_RESET}"
        else:
            status_icon = f"{C_RED}✗{C_RESET}"
        lines = [f"\n  [{status_icon}] {result.get('message', '')}"]
        # Only show user-facing files (HTML), not internal JSON
        for a in result.get("artifacts", []):
            if a.endswith(".json"):
                continue
            abs_path = (Path.cwd() / a).resolve()
            link = f"\033]8;;file://{abs_path}\033\\{a}\033]8;;\033\\"
            lines.append(f"       {link}")

        # Show phase timings if available
        timings = result.get("data", {}).get("timings", [])
        if timings:
            parts = []
            for t in timings:
                label = t.get("phase", "")
                dur = t.get("duration_s", 0)
                if label == "总计":
                    parts.append(f"  {C_DIM}⏱ {label} {dur}s{C_RESET}")
                else:
                    parts.append(f"{C_DIM}{label} {dur}s{C_RESET}")
            lines.append("  " + "  |  ".join(parts))

        # Print artifacts immediately so the user can preview before approving
        click.echo("\n".join(lines))

        step = self.workflow.current_step
        if not step:
            return ""

        # Loop menu: user can modify repeatedly until satisfied, then approve
        while True:
            action_choice = self._post_agent_menu(step)
            if action_choice is None:
                return f"\n  {C_DIM}已取消{C_RESET}"
            elif action_choice == "approve":
                return self._exec_approve({"comment": ""})
            elif action_choice == "reject":
                reason = click.prompt(REJECT_PROMPT, default=REJECT_DEFAULT)
                return self._exec_reject({"comment": reason})
            elif action_choice == "modify":
                self._exec_interactive_session(agent_role)
                # Session handles its own rendering; loop back to menu
            elif action_choice == "retry":
                click.echo(f"\n  {C_DIM}请直接输入新的描述来重新执行此步骤{C_RESET}")
                return ""

    def _exec_interactive_session(self, agent_role: str) -> None:
        """REPL-managed multi-turn modification via adapter.

        Each turn calls adapter.generate_interactive() — for Claude Code this
        uses --session-id; for DeepSeek this is stateless API calls.
        """
        import glob as _glob

        repo_path = Path(getattr(self.agent, 'repo_path', Path.cwd()))

        # ── Find artifact ─────────────────────────────────────────────────
        role_dir_map = {
            "pm": ".cogniforge/wiki/prd",
            "architect": ".cogniforge/wiki/sad",
            "design": ".cogniforge/wiki/lld",
            "techlead": ".cogniforge/wiki/tasks",
            "reviewer": ".cogniforge/wiki/reports",
            "qa": ".cogniforge/wiki/qa",
            "devops": ".cogniforge/wiki/ops",
        }
        dir_path = role_dir_map.get(agent_role)
        artifact_path = None
        if artifact_path is None and dir_path:
            files = sorted(_glob.glob(str(repo_path / dir_path / "*.json")))
            artifact_path = Path(files[-1]) if files else None

        if artifact_path is None:
            click.echo(
                f"\n  {C_AMBER}⚠ 未找到 {agent_role} 的产物文件，"
                f"无法进入交互模式{C_RESET}"
            )
            return

        # ── Session setup ─────────────────────────────────────────────────
        step_value = self._agent_role_to_step(agent_role)
        session_id = str(uuid.uuid4())
        schema_path = repo_path / f"schemas/{step_value}-schema.json"

        # Get the adapter for this role (not the REPL's llm_adapter)
        role_agent = self.agents.get(agent_role)
        agent_adapter = getattr(role_agent, 'agent', self.agent) if role_agent else self.agent

        system_prompt = MODIFY_SESSION_SYSTEM_PROMPTS.get(
            agent_role, MODIFY_SESSION_SYSTEM_PROMPTS.get("pm", "")
        )

        # ── Open purple box (no bottom — loop runs inside) ────────────────
        box_title = f"交互式修改 — {step_value.upper()}" if step_value else "交互式修改"
        box_lines = [
            f"产物: {artifact_path.relative_to(repo_path)}",
            "输入修改意见，Agent 逐轮修改文档。输入 /done 完成。",
        ]
        # Box width: start from header, auto-expand when content is wider
        _all = [box_title] + box_lines
        _box_w = max(_display_width(ln) for ln in _all)
        _box_w = max(_box_w, _display_width(box_title) + 2)
        click.echo()
        click.echo(_draw_box(
            top_line=box_title, lines=box_lines, bottom_close=False,
            min_width=_box_w,
        ))

        # ── Helper: re-render and commit ──────────────────────────────────
        def _save_and_render(json_text: str) -> None:
            from cogniforge.wiki.wiki_renderer import render_file
            artifact_path.write_text(json_text, encoding="utf-8")
            try:
                html_path = render_file(artifact_path)
                _box_print(f"{C_GREEN}✓{C_RESET} 文档已更新")
                if html_path:
                    rel_link = html_path.relative_to(repo_path).as_posix()
                    _box_print(f"{C_DIM}{rel_link}{C_RESET}")
                if self.wiki_system:
                    try:
                        self.wiki_system.git_storage.repo.index.add([
                            artifact_path.relative_to(repo_path).as_posix(),
                        ])
                        if html_path:
                            self.wiki_system.git_storage.repo.index.add([
                                html_path.relative_to(repo_path).as_posix(),
                            ])
                        self.wiki_system.git_storage.commit(
                            "docs: update after interactive refinement", "pm_agent"
                        )
                    except Exception:
                        pass
            except Exception as exc:
                _box_print(f"{C_AMBER}⚠ HTML 渲染失败: {exc}{C_RESET}")

        # ── Helpers for bordered output ───────────────────────────────────
        def _strip_ansi(text: str) -> str:
            """Remove ANSI escape sequences so display-width is accurate."""
            return re.sub(r"\033\[[0-9;]*m", "", text)

        def _box_print(text: str) -> None:
            """Print lines inside the open purple box; expand _box_w if needed."""
            nonlocal _box_w
            P, R = C_PURPLE, C_RESET
            for line in str(text).split("\n"):
                dw = _display_width(_strip_ansi(line))
                if dw > _box_w:
                    _box_w = dw
                pad = " " * (_box_w - dw)
                click.echo(f"  {P}│{R} {line}{pad} {P}│{R}")

        def _box_empty() -> None:
            """Print an empty line inside the box."""
            P, R = C_PURPLE, C_RESET
            click.echo(f"  {P}│{R}{' ' * (_box_w + 2)} {P}│{R}")

        def _box_input(prompt_text: str) -> str:
            """Read user input with left border (right border not drawn during typing)."""
            P, R = C_PURPLE, C_RESET
            try:
                return input(f"  {P}│{R} {prompt_text}").strip()
            except (EOFError, KeyboardInterrupt):
                return ""

        # ── Multi-turn loop ───────────────────────────────────────────────
        _box_empty()
        while True:
            try:
                user_input = _box_input(
                    f"cogniforge [修改 {step_value or agent_role}]: "
                )
            except (EOFError, KeyboardInterrupt):
                break

            if user_input in ("", "/done", "/exit", "/quit"):
                break

            if user_input.startswith("/"):
                continue

            # Read current JSON
            try:
                current_json = artifact_path.read_text(encoding="utf-8")
            except Exception:
                _box_print(f"{C_RED}✗{C_RESET} 无法读取产物文件")
                continue

            # ── PM role: use patch-based modify_interactive ──────────────
            if agent_role == "pm" and role_agent and hasattr(role_agent, "modify_interactive"):
                spinner = Spinner("PM 正在处理修改")
                spinner.start()
                try:
                    result = role_agent.modify_interactive(user_request=user_input)
                except Exception as e:
                    spinner.stop()
                    _box_print(f"{C_RED}✗{C_RESET} 请求失败: {e}")
                    continue
                finally:
                    spinner.stop()

                if result.get("status") == "success":
                    _box_print(f"{C_GREEN}✓{C_RESET} {result.get('message', '已更新')}")
                    open_qs = result.get("data", {}).get("open_questions", [])
                    for q in open_qs:
                        _box_print(f"{C_AMBER}?{C_RESET} {q}")
                    # Re-render HTML
                    try:
                        from cogniforge.wiki.wiki_renderer import render_file
                        html_path = render_file(Path(repo_path) / "docs" / "prd.json")
                        if html_path:
                            rel_link = html_path.relative_to(repo_path).as_posix()
                            _box_print(f"{C_DIM}{rel_link}{C_RESET}")
                    except Exception as exc:
                        _box_print(f"{C_AMBER}⚠ HTML 渲染失败: {exc}{C_RESET}")
                else:
                    _box_print(f"{C_RED}✗{C_RESET} {result.get('message', '修改失败')}")
                _box_empty()
                continue

            # ── Non-PM roles: full-replace via generate_interactive ──────
            spinner = Spinner("Agent 正在修改")
            spinner.start()
            try:
                kwargs = {"session_id": session_id}
                if schema_path.exists():
                    kwargs["schema_path"] = str(schema_path)
                response = agent_adapter.generate_interactive(
                    current_document=current_json,
                    user_request=user_input,
                    system_prompt=system_prompt,
                    **kwargs,
                )
            except RuntimeError as e:
                spinner.stop()
                _box_print(f"{C_RED}✗{C_RESET} {e}")
                continue
            except Exception as e:
                spinner.stop()
                _box_print(f"{C_RED}✗{C_RESET} 请求失败: {e}")
                continue
            finally:
                spinner.stop()

            json_output = response.content if hasattr(response, "content") else str(response)

            # Strip markdown code fences if present
            json_output = _extract_json(json_output)

            # Validate it's parseable JSON
            try:
                json.loads(json_output)
            except json.JSONDecodeError as e:
                # Auto-retry: ask LLM to fix the JSON syntax error
                _box_print(
                    f"{C_AMBER}⚠ JSON 解析失败: {e}，正在自动修复...{C_RESET}"
                )
                try:
                    fix_prompt = (
                        f"以下 JSON 有语法错误，请直接修复并返回正确的 JSON:\n\n"
                        f"错误: {e}\n\n"
                        f"原始输出:\n{json_output}\n\n"
                        f"只返回修复后的纯 JSON，不要任何解释。"
                    )
                    if hasattr(agent_adapter, "generate"):
                        fix_response = agent_adapter.generate(fix_prompt)
                        json_output = _extract_json(
                            fix_response.content if hasattr(fix_response, "content")
                            else str(fix_response)
                        )
                        json.loads(json_output)  # Validate fix
                    else:
                        raise e
                except Exception:
                    _box_print(f"{C_RED}✗{C_RESET} 自动修复失败，请重试")
                    continue

            # Save and re-render
            _save_and_render(json_output)
            _box_empty()

        # ── Close purple box ───────────────────────────────────────────
        # Match _draw_box bottom: ╰─{'─' * content_w}─╯  →  content_w + 1 dashes
        click.echo(f"  {C_PURPLE}╰─{'─' * _box_w}─╯{C_RESET}")
        click.echo(f"  {C_DIM}已返回 CogniForge 审批流程。{C_RESET}")

    @staticmethod
    def _agent_role_to_step(agent_role: str) -> Optional[str]:
        """Map agent role to workflow step."""
        for step_key, schema in AGENT_SCHEMAS.items():
            if schema.get("agent") == agent_role:
                return step_key
        return None

    def _post_agent_menu(self, step) -> str:
        """Interactive menu shown after each agent execution.

        PRD/SAD steps: approve / modify (interactive Claude Code session).
        Other agent steps: approve / reject / retry.
        """
        # Interactive steps: modification replaces both reject and retry
        if step.value in INTERACTIVE_STEPS:
            click.echo(_draw_box(
                top_line=step.get_approval_prompt(),
                lines=["使用 ↑↓ 选择，回车确认"],
                bottom_close=False,
            ))
            return _select([
                ("approve", CHOICE_APPROVE),
                ("modify", CHOICE_MODIFY),
            ], default=0, colors=[C_GREEN, C_AMBER])

        # Other agent steps: approve / reject / retry
        click.echo(_draw_box(
            top_line=step.get_approval_prompt(),
            lines=["使用 ↑↓ 选择，回车确认"],
            bottom_close=False,
        ))
        return _select([
            ("approve", CHOICE_APPROVE),
            ("reject", CHOICE_REJECT),
            ("retry", CHOICE_RETRY),
        ], default=0, colors=[C_GREEN, C_RED, C_AMBER])

    def _exec_approve(self, action: dict) -> str:
        step = self.workflow.current_step
        if step is None:
            return NO_STEP_APPROVE

        self.workflow.approve(comment=action.get("comment", ""), approver="repl_user")
        next_step = self.workflow.advance()

        # Auto-skip review steps — no need for a second confirmation
        while next_step and next_step.value in REVIEW_STEPS:
            self.workflow.approve(comment="", approver="repl_user")
            next_step = self.workflow.advance()

        lines = [C_DIM + STEP_SEPARATOR + C_RESET,
                 f"  {C_GREEN}✓{C_RESET} 已审批: {step.value}"]
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
            C_DIM + STEP_SEPARATOR + C_RESET,
            f"  {C_RED}✗{C_RESET} 已拒绝: {step.value}",
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
                prefix = f"{C_PURPLE}→{C_RESET}"
            elif s.value in completed:
                prefix = f"{C_GREEN}✓{C_RESET}"
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
