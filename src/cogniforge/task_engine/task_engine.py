"""Task engine - task scheduling and DAG execution"""

import json
from pathlib import Path
from typing import Optional

from cogniforge.core.config import Config
from cogniforge.core.constants import TaskStatus, TaskPriority
from cogniforge.core.exceptions import TaskNotFoundError, TaskDependencyError
from cogniforge.models.task import Task
from cogniforge.storage.git_storage import GitStorage
from cogniforge.task_engine.dag import DAGStep, dag


def _has_cycle(tasks: dict[str, Task], start_id: str) -> bool:
    """Check if start_id's dependencies lead back to start_id (cycle)."""
    start_task = tasks.get(start_id)
    if not start_task:
        return False

    visited: set[str] = set()
    stack: list[str] = []

    for dep_id in start_task.deps:
        if dep_id in tasks:
            stack.append(dep_id)

    while stack:
        current = stack.pop()
        if current == start_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        task = tasks.get(current)
        if task:
            stack.extend(task.deps)

    return False


class TaskEngine:
    """Task scheduling engine.

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
        """Load existing tasks from wiki/tasks/ (JSON format)."""
        tasks_dir = self.config.repo_path / ".cogniforge/wiki/tasks"
        if not tasks_dir.exists():
            return

        for task_file in tasks_dir.glob("*.json"):
            # Skip WBS aggregate files
            if task_file.name.startswith("wbs_"):
                continue
            try:
                data = json.loads(task_file.read_text(encoding="utf-8"))
                task = Task.from_json_dict(data)
                self._tasks[task.task_id] = task
            except Exception:
                pass

    def create_task(
        self,
        name: str,
        module: str,
        description: str = "",
        deps: list[str] = None,
        priority: TaskPriority = TaskPriority.P2,
        assignee: Optional[str] = None,
        estimated_hours: Optional[float] = None,
        category: Optional[str] = None,
        commit_message: str = "feat: create task",
    ) -> Task:
        """Create a new task.

        Args:
            name: Task name
            module: Module this task belongs to
            description: Task description
            deps: List of dependent task IDs
            priority: Task priority (P0-P3)
            assignee: Agent role or ID assigned to this task
            estimated_hours: Estimated effort in hours
            category: Task category (model, service, endpoint, test, etc.)
            commit_message: Git commit message

        Returns:
            Created task

        Raises:
            TaskDependencyError: if a dependency doesn't exist or creates a cycle
        """
        deps = deps or []

        # Validate dependencies exist
        for dep_id in deps:
            if dep_id not in self._tasks:
                raise TaskDependencyError(f"Dependency task {dep_id} does not exist")

        task_id = self._generate_task_id(module)

        task = Task(
            task_id=task_id,
            name=name,
            module=module,
            description=description,
            deps=deps,
            priority=priority,
            assignee=assignee,
            estimated_hours=estimated_hours,
            category=category,
        )

        self._tasks[task_id] = task

        # Check for cycles after insertion
        if _has_cycle(self._tasks, task_id):
            del self._tasks[task_id]
            raise TaskDependencyError(f"Adding task {task_id} would create a circular dependency")

        self._save_task(task, commit_message)
        return task

    def add_task(self, task: Task, commit_message: str = "feat: add task") -> Task:
        """Add a pre-built task mid-execution (dynamic replanning).

        Raises TaskDependencyError if deps create a cycle.
        """
        # Validate dependencies
        for dep_id in task.deps:
            if dep_id not in self._tasks:
                raise TaskDependencyError(f"Dependency task {dep_id} does not exist")

        self._tasks[task.task_id] = task
        if _has_cycle(self._tasks, task.task_id):
            del self._tasks[task.task_id]
            raise TaskDependencyError(f"Adding task {task.task_id} would create a circular dependency")

        self._save_task(task, commit_message)
        return task

    def remove_task(self, task_id: str, commit_message: str = "chore: remove task") -> bool:
        """Remove a PENDING task that is no longer needed.

        Refuses to remove tasks that are IN_PROGRESS, DONE, or FAILED.
        Also refuses if other tasks depend on this one.
        """
        if task_id not in self._tasks:
            return False

        task = self._tasks[task_id]
        if task.status != TaskStatus.PENDING:
            return False

        # Check if any other task depends on this one
        for other_id, other_task in self._tasks.items():
            if other_id != task_id and task_id in other_task.deps:
                return False

        del self._tasks[task_id]

        task_path = Path(f".cogniforge/wiki/tasks/{task_id}.json")
        full_path = self.config.repo_path / task_path
        if full_path.exists():
            full_path.unlink()
            self.git_storage.repo.index.remove([str(task_path)])
            self.git_storage.commit(commit_message)

        return True

    def replan(self, task_specs: list[dict], commit_message: str = "feat: replan tasks") -> dict:
        """Batch replan: add/update/remove tasks from a new WBS snapshot.

        Each spec dict must have: name, module.  Optional: description, deps,
        priority, assignee, estimated_hours, category.

        Existing tasks not in the new spec are removed (if PENDING).
        New tasks in the spec but not in _tasks are created.
        Existing tasks are updated in-place.
        """
        spec_ids: set[str] = set()
        added: list[str] = []
        updated: list[str] = []
        removed: list[str] = []

        new_tasks: dict[str, Task] = {}

        for spec in task_specs:
            name = spec["name"]
            module = spec["module"]
            task_id = self._generate_task_id(module)
            spec_ids.add(task_id)

            # Build task — resolve deps to actual task IDs where possible
            deps = spec.get("deps", [])
            priority_val = spec.get("priority", 2)
            if isinstance(priority_val, str):
                try:
                    priority_val = int(priority_val)
                except ValueError:
                    priority_val = 2
            priority = TaskPriority(priority_val) if isinstance(priority_val, int) else TaskPriority.P2

            task = Task(
                task_id=task_id,
                name=name,
                module=module,
                description=spec.get("description", ""),
                deps=deps,
                priority=priority,
                assignee=spec.get("assignee"),
                estimated_hours=spec.get("estimated_hours"),
                category=spec.get("category"),
            )

            if task_id in self._tasks:
                existing = self._tasks[task_id]
                existing.name = name
                existing.description = spec.get("description", existing.description)
                existing.deps = deps
                existing.priority = priority
                existing.assignee = spec.get("assignee", existing.assignee)
                existing.estimated_hours = spec.get("estimated_hours", existing.estimated_hours)
                existing.category = spec.get("category", existing.category)
                existing.updated_at = task.created_at
                new_tasks[task_id] = existing
                updated.append(task_id)
                self._save_task(existing, commit_message)
            else:
                new_tasks[task_id] = task
                added.append(task_id)

        # Remove tasks not in the new spec (only PENDING ones)
        for task_id in list(self._tasks.keys()):
            if task_id not in spec_ids and self._tasks[task_id].status == TaskStatus.PENDING:
                if self.remove_task(task_id, commit_message):
                    removed.append(task_id)

        # Now add new tasks and check for cycles
        for task_id in added:
            task = new_tasks[task_id]
            self._tasks[task_id] = task
            if _has_cycle(self._tasks, task_id):
                del self._tasks[task_id]
                added.remove(task_id)
                continue
            self._save_task(task, commit_message)

        self._tasks.update(new_tasks)

        return {"added": added, "updated": updated, "removed": removed}

    def _generate_task_id(self, module: str) -> str:
        """Generate unique task ID for module"""
        existing = [t for t in self._tasks.values() if t.module == module]
        seq = len(existing) + 1
        return f"{module}-{seq:03d}"

    def _save_task(self, task: Task, commit_message: str) -> None:
        """Save task to wiki as JSON and commit"""
        task_path = Path(f".cogniforge/wiki/tasks/{task.task_id}.json")
        full_path = self.config.repo_path / task_path

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(
            json.dumps(task.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
        """Get tasks that are ready to execute.

        A task is ready if:
        1. Status is PENDING
        2. All dependencies are DONE
        """
        ready = []

        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue

            deps_done = all(
                self._tasks.get(dep).status == TaskStatus.DONE
                for dep in task.deps
                if dep in self._tasks
            )

            if deps_done:
                ready.append(task)

        return sorted(ready, key=lambda t: t.priority.value)

    def get_blocked_tasks(self) -> list[Task]:
        """Get tasks that are blocked (dependencies not done)"""
        blocked = []

        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue

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
        if step == DAGStep.CODING:
            return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
        return []

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        changed_files: list[str] | None = None,
        commit_message: str = "chore: update task",
    ) -> Task:
        """Update task status"""
        task = self.get_task(task_id)

        if status == TaskStatus.DONE:
            task.mark_done(result, changed_files)
        elif status == TaskStatus.FAILED:
            task.mark_failed(error or "Unknown error")
        elif status == TaskStatus.BLOCKED:
            task.mark_blocked()
        elif status == TaskStatus.IN_PROGRESS:
            task.mark_in_progress()
        else:
            task.status = status
            task.updated_at = None  # Force refresh

        self._save_task(task, commit_message)
        return task

    def get_parallel_tasks(self, max_count: int = 4) -> list[Task]:
        """Get tasks that can be executed in parallel"""
        return self.get_parallel_tasks_with_conflict_check(max_count)

    def get_parallel_tasks_with_conflict_check(self, max_count: int = 4) -> list[Task]:
        """Get parallel-ready tasks with file conflict detection.

        Two tasks cannot run in parallel if they write to the same files.
        """
        ready = self.get_ready_tasks()

        parallel: list[Task] = []
        remaining = list(ready)
        files_locked: set[str] = set()

        while remaining and len(parallel) < max_count:
            task = remaining.pop(0)

            # Dep already in parallel → skip
            has_dep_in_parallel = any(
                dep in [t.task_id for t in parallel]
                for dep in task.deps
            )
            if has_dep_in_parallel:
                continue

            # File conflict check
            task_files = set(getattr(task, "expected_output_files", []) or [])
            if task_files & files_locked:
                continue  # Would write to same file as a parallel task

            parallel.append(task)
            files_locked |= task_files

        return parallel

    def inject_upstream_context(self, task: Task) -> Task:
        """Inject upstream artifacts into task context before DEV execution.

        Looks up all completed dependency tasks and collects their
        changed_files, then writes them into task.context.upstream_artifacts.
        """
        upstream: list[dict] = []
        for dep_id in task.deps:
            dep_task = self._tasks.get(dep_id)
            if dep_task and dep_task.status == TaskStatus.DONE:
                upstream.append({
                    "task_id": dep_task.task_id,
                    "name": dep_task.name,
                    "files": dep_task.changed_files,
                    "category": dep_task.category or "",
                })

        if upstream and task.context:
            task.context.upstream_artifacts = upstream

        return task

    def get_external_artifacts(self, module: str, exclude_task_id: str = "") -> list[dict]:
        """Get completed task artifacts from a different module.

        Used when a task depends on another module's interface being implemented.
        """
        artifacts: list[dict] = []
        for t in self._tasks.values():
            if t.module != module:
                continue
            if t.task_id == exclude_task_id:
                continue
            if t.status != TaskStatus.DONE:
                continue
            artifacts.append({
                "task_id": t.task_id,
                "name": t.name,
                "module": t.module,
                "files": t.changed_files,
                "category": t.category or "",
            })
        return artifacts

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
