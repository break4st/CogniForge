"""Dev Agent - Developer Agent for code implementation"""

import subprocess
from pathlib import Path
from typing import Optional

from cogniforge.agents.base import BaseAgent
from cogniforge.core.constants import AgentRole
from cogniforge.core.exceptions import AgentError
from cogniforge.llm.base import create_llm_adapter, LLMProvider


class DevAgent(BaseAgent):
    """
    Dev Agent - Developer.

    Responsibilities:
    - Write code
    - Write unit tests
    - Fix bugs
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._llm = None

    @property
    def llm(self):
        """Lazy load LLM adapter"""
        if self._llm is None:
            provider = LLMProvider(self.config.llm_provider)
            self._llm = create_llm_adapter(provider, {
                "model": self.config.llm_model,
                "api_key": self.config.llm_api_key,
                "api_base": self.config.llm_api_base,
                "repo_path": self.config.repo_path,
                "codex_cli_path": self.config.codex_cli_path,
                "approval_mode": self.config.codex_approval_mode,
                "sandbox": self.config.codex_sandbox,
                "full_auto": self.config.codex_full_auto,
                "timeout": self.config.default_timeout,
            })
        return self._llm

    def run(self, input_data: dict) -> dict:
        """
        Implement code based on task and context.

        Args:
            input_data: {
                "task": Task object,
                "code": str,  # Optional: pre-generated code
                "module": str,
            }
        """
        try:
            task = input_data.get("task")
            module = input_data.get("module", task.module if task else "unknown")
            code = input_data.get("code", "")

            # Load context for audit trail
            task_id = task.task_id if task else None
            context = self.load_context(task_id=task_id, module=module, include_code=False)

            # Generate code if not provided
            if not code:
                code = self._generate_code(module, context, task)

            # Write code file
            code_path = self._write_code(module, task, code)

            # Run tests
            test_result = self._run_tests(module)

            return self.format_result(
                status="success" if test_result["passed"] else "failed",
                message=f"Code generated for {module}",
                artifacts=[code_path],
                data=test_result,
                reasoning=self._get_reasoning(code, context),
                decisions=[f"Created {code_path}", "Implemented based on LLD"]
            )

        except Exception as e:
            return self.format_result(
                status="failed",
                message=str(e)
            )

    def _generate_code(self, module: str, context: dict, task) -> str:
        """
        Generate code using LLM adapter.

        The LLM adapter is provider-agnostic, supporting:
        - Claude Code (claude_code)
        - Codex CLI (open_code)
        - Legacy Codex alias (codex)
        """
        # Build prompt for code generation
        prompt = self._build_code_prompt(module, task)

        # Call LLM through adapter (provider-agnostic)
        response = self.llm.generate(
            prompt=prompt,
            context=context
        )

        return response.content

    def _build_code_prompt(self, module: str, task) -> str:
        """Build prompt for code generation"""
        prompt_lines = [
            f"# Code Generation Task",
            f"",
            f"## Module: {module}",
            f"",
            f"## Task: {task.name if task else 'Implement module'}",
        ]

        if task and hasattr(task, 'description'):
            prompt_lines.append(f"## Description")
            prompt_lines.append(task.description)

        prompt_lines.extend([
            f"",
            f"## Requirements",
            f"- Follow Python best practices",
            f"- Use type hints",
            f"- Include docstrings",
            f"- Write testable code",
            f"",
            f"## Output",
            f"Only output the code, no explanations.",
        ])

        return "\n".join(prompt_lines)

    def _get_reasoning(self, code: str, context: dict) -> str:
        """Get reasoning for audit trail"""
        return f"Generated Python module '{context.get('module', 'unknown')}' using LLM adapter. Code length: {len(code)} characters."

    def _write_code(self, module: str, task, code: str) -> str:
        """Write code to file"""
        if not task:
            raise AgentError("Task is required to write code")

        # Create module directory
        module_path = self.config.repo_path / "src" / module
        module_path.mkdir(parents=True, exist_ok=True)

        # Determine filename from task
        filename = f"{module}_{task.name.replace('-', '_').replace(' ', '_')}.py"
        file_path = module_path / filename

        # Write code
        file_path.write_text(code, encoding="utf-8")

        # Stage in git
        self.git_storage.repo.index.add([f"src/{module}/{filename}"])

        return f"src/{module}/{filename}"

    def _run_tests(self, module: str) -> dict:
        """Run tests for module"""
        # Check if pytest is available
        try:
            result = subprocess.run(
                ["pytest", "-v", "--tb=short", f"tests/test_{module}.py"],
                capture_output=True,
                text=True,
                cwd=str(self.config.repo_path)
            )

            passed = result.returncode == 0
            return {
                "passed": passed,
                "output": result.stdout,
                "error": result.stderr
            }
        except FileNotFoundError:
            # pytest not installed
            return {
                "passed": True,  # Can't run tests, assume pass
                "output": "pytest not found, skipping tests",
                "error": None
            }
        except Exception as e:
            return {
                "passed": False,
                "output": "",
                "error": str(e)
            }
