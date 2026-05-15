"""Task engine - task scheduling and DAG execution"""

from pathlib import Path
from typing import Optional

from cogniforge.core.config import Config
from cogniforge.core.constants import TaskStatus, TaskPriority
from cogniforge.core.exceptions import TaskNotFoundError, TaskDependencyError
from cogniforge.models.task import Task
from cogniforge.storage.git_storage import GitStorage
from cogniforge.task_engine.dag import DAGStep, dag


class TaskEngine:
    """
    Task scheduling engine.

    Responsibilities:
    - Task creation and management
    - DAG scheduling
    - Dependency resolution
    - Parallel task identification
    """

    def __init__(self, config: Config, git_storage: GitStorage):
        self.config = config
        self.git_storage = git_storage
        self._tasks: dict[str, Task] = {}
        self._load_tasks()

    def _load_tasks(self) -> None:
        """Load existing tasks from wiki/tasks/"""
        tasks_dir = self.config.repo_path / ".cogniforge/wiki/tasks"
        if not tasks_dir.exists():
            return

        for task_file in tasks_dir.glob("*.md"):
            try:
                content = task_file.read_text(encoding="utf-8")
                task = Task.from_markdown(str(task_file.relative_to(self.config.repo_path)), content)
                self._tasks[task.task_id] = task
            except Exception:
                # Skip files that can't be parsed
                pass

    def create_task(
        self,
        name: str,
        module: str,
        description: str = "",
        deps: list[str] = None,
        priority: TaskPriority = TaskPriority.P2,
        assignee: Optional[str] = None,
        commit_message: str = "feat: create task"
    ) -> Task:
        """
        Create a new task.

        Args:
            name: Task name
            module: Module this task belongs to
            description: Task description
            deps: List of dependent task IDs
            priority: Task priority (P0-P3)
            assignee: Agent role or ID assigned to this task
            commit_message: Git commit message

        Returns:
            Created task
        """
        # Validate dependencies
        if deps:
            for dep_id in deps:
                if dep_id not in self._tasks:
                    raise TaskDependencyError(f"Dependency task {dep_id} does not exist")

        task_id = self._generate_task_id(module)

        task = Task(
            task_id=task_id,
            name=name,
            module=module,
            description=description,
            deps=deps or [],
            priority=priority,
            assignee=assignee
        )

        self._tasks[task_id] = task
        self._save_task(task, commit_message)

        return task

    def _generate_task_id(self, module: str) -> str:
        """Generate unique task ID for module"""
        existing = [t for t in self._tasks.values() if t.module == module]
        seq = len(existing) + 1
        return f"{module}-{seq:03d}"

    def _save_task(self, task: Task, commit_message: str) -> None:
        """Save task to wiki and commit"""
        task_path = Path(f".cogniforge/wiki/tasks/{task.task_id}.md")
        full_path = self.config.repo_path / task_path

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(task.to_markdown(), encoding="utf-8")

        self.git_storage.repo.index.add([str(task_path)])
        self.git_storage.commit(commit_message)

    def get_task(self, task_id: str) -> Task:
        """Get task by ID"""
        if task_id not in self._tasks:
            raise TaskNotFoundError(f"Task {task_id} not found")
        return self._tasks[task_id]

    def get_tasks_by_module(self, module: str) -> list[Task]:
        """Get all tasks for a module"""
        return [t for t in self._tasks.values() if t.module == module]

    def get_ready_tasks(self) -> list[Task]:
        """
        Get tasks that are ready to execute.

        A task is ready if:
        1. Status is PENDING
        2. All dependencies are DONE
        """
        ready = []

        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue

            # Check if all dependencies are done
            deps_done = all(
                self._tasks.get(dep).status == TaskStatus.DONE
                for dep in task.deps
                if dep in self._tasks
            )

            if deps_done:
                ready.append(task)

        # Sort by priority (P0 first)
        return sorted(ready, key=lambda t: t.priority.value)

    def get_blocked_tasks(self) -> list[Task]:
        """Get tasks that are blocked (dependencies not done)"""
        blocked = []

        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue

            # Check if any dependency is not done
            deps_blocked = any(
                self._tasks.get(dep).status != TaskStatus.DONE
                for dep in task.deps
                if dep in self._tasks
            )

            if deps_blocked:
                blocked.append(task)

        return blocked

    def get_tasks_by_step(self, step: DAGStep) -> list[Task]:
        """Get tasks associated with a DAG step"""
        # Tasks are associated with steps through their module or type
        # For now, return all pending tasks for the coding step
        if step == DAGStep.CODING:
            return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        return []

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        commit_message: str = "chore: update task"
    ) -> Task:
        """Update task status"""
        task = self.get_task(task_id)

        if status == TaskStatus.DONE:
            task.mark_done(result)
        elif status == TaskStatus.FAILED:
            task.mark_failed(error or "Unknown error")
        elif status == TaskStatus.BLOCKED:
            task.mark_blocked()
        elif status == TaskStatus.IN_PROGRESS:
            task.mark_in_progress()
        else:
            task.status = status
            task.updated_at = result

        self._save_task(task, commit_message)
        return task

    def get_parallel_tasks(self, max_count: int = 4) -> list[Task]:
        """Get tasks that can be executed in parallel"""
        ready = self.get_ready_tasks()

        # Filter tasks that have no dependencies on each other
        parallel = []
        remaining = ready

        while remaining and len(parallel) < max_count:
            task = remaining.pop(0)

            # Check if this task depends on any task already in parallel set
            has_dep_in_parallel = any(
                dep in [t.task_id for t in parallel]
                for dep in task.deps
            )

            if not has_dep_in_parallel:
                parallel.append(task)
            else:
                # Put at end, will be scheduled in next batch
                remaining.append(task)

        return parallel

    def is_complete(self) -> bool:
        """Check if all tasks are done or failed"""
        return all(
            t.status in (TaskStatus.DONE, TaskStatus.FAILED)
            for t in self._tasks.values()
        )

    def get_statistics(self) -> dict:
        """Get task statistics"""
        stats = {
            "total": len(self._tasks),
            "pending": 0,
            "in_progress": 0,
            "done": 0,
            "blocked": 0,
            "failed": 0,
        }

        for task in self._tasks.values():
            stats[task.status.value] += 1

        return stats

    def list_tasks(self, status: Optional[TaskStatus] = None) -> list[Task]:
        """List all tasks, optionally filtered by status"""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: (t.priority.value, t.task_id))
