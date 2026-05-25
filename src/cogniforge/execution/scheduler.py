"""Task Scheduler — manage execution order of WBS batches.

Orchestrates the execution of DEV tasks by batch, respecting
file-lock conflicts and dependency ordering from the WBS index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BatchStatus:
    batch_idx: int = 0
    task_ids: list[str] = field(default_factory=list)
    parallel: bool = False
    status: str = "pending"  # pending | running | completed | failed


class TaskScheduler:
    """Manage the execution of WBS batches.

    Reads a WBS index, tracks batch progress, and provides
    the next ready batch for execution.
    """

    def __init__(self, repo_path: Path | None = None):
        self.repo_path = repo_path or Path.cwd()
        self._batches: list[BatchStatus] = []
        self._current_idx: int = 0
        self._task_results: dict[str, dict] = {}

    def load_from_wbs(self, wbs_data: dict, task_engine=None) -> None:
        """Initialize scheduler state from a WBS index dict."""
        batches = wbs_data.get("execution_batches", [])
        self._batches = []

        for b_data in batches:
            if isinstance(b_data, dict):
                self._batches.append(BatchStatus(
                    batch_idx=b_data.get("batch", len(self._batches)),
                    task_ids=b_data.get("task_ids", []),
                    parallel=b_data.get("parallel", False),
                    status="pending",
                ))

        self._current_idx = 0
        self._task_results = {}

    def pre_flight_check(self, batch: BatchStatus, all_tasks: dict[str, dict]) -> list[str]:
        """Verify no file-lock conflicts within a batch before parallel execution.

        Returns a list of conflict descriptions (empty = safe to run).
        """
        conflicts: list[str] = []

        # Collect files locked by each task in the batch
        locks: dict[str, list[str]] = {}
        for tid in batch.task_ids:
            task = all_tasks.get(tid, {})
            for f in task.get("file_locks", []):
                locks.setdefault(f, []).append(tid)

        for f, owners in locks.items():
            if len(owners) > 1:
                conflicts.append(f"文件 '{f}' 被 {owners} 同时锁定")

        return conflicts

    def next_batch(self) -> BatchStatus | None:
        """Return the next pending batch, or None if all done."""
        for b in self._batches:
            if b.status == "pending":
                return b
        return None

    def mark_batch_running(self, batch_idx: int) -> None:
        """Mark a batch as running."""
        if 0 <= batch_idx < len(self._batches):
            self._batches[batch_idx].status = "running"

    def mark_batch_done(self, batch_idx: int, results: list[dict] | None = None) -> None:
        """Mark a batch as completed and store task results."""
        if 0 <= batch_idx < len(self._batches):
            self._batches[batch_idx].status = "completed"
        if results:
            for r in results:
                tid = r.get("task_id", "")
                self._task_results[tid] = r

    def mark_batch_failed(self, batch_idx: int) -> None:
        """Mark a batch as failed."""
        if 0 <= batch_idx < len(self._batches):
            self._batches[batch_idx].status = "failed"

    @property
    def all_done(self) -> bool:
        """True when all batches are completed or failed."""
        return all(
            b.status in ("completed", "failed")
            for b in self._batches
        )

    @property
    def progress(self) -> dict:
        """Return a progress summary."""
        total = len(self._batches)
        done = sum(1 for b in self._batches if b.status == "completed")
        failed = sum(1 for b in self._batches if b.status == "failed")
        running = sum(1 for b in self._batches if b.status == "running")
        return {
            "total_batches": total,
            "completed": done,
            "failed": failed,
            "running": running,
            "pending": total - done - failed - running,
        }
