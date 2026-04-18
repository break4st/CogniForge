"""Worker pool - parallel task execution"""

from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Callable, Any, Optional
from dataclasses import dataclass

from cogniforge.core.config import Config


@dataclass
class WorkerResult:
    """Result from a worker execution"""
    task_id: str
    success: bool
    result: Any
    error: Optional[str] = None


class WorkerPool:
    """
    Worker pool for parallel task execution.

    Manages multiple Dev agents executing tasks in parallel.
    """

    def __init__(self, max_workers: int = 4, config: Optional[Config] = None):
        self.max_workers = max_workers or (config.max_workers if config else 4)
        self.config = config or Config()
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._futures: dict[Future, str] = {}  # future -> task_id mapping
        self._results: dict[str, WorkerResult] = {}

    def submit(
        self,
        fn: Callable,
        task_id: str,
        *args,
        **kwargs
    ) -> Future:
        """
        Submit a task to the worker pool.

        Args:
            fn: Function to execute
            task_id: Unique task identifier
            *args: Positional arguments for fn
            **kwargs: Keyword arguments for fn

        Returns:
            Future object
        """
        future = self.executor.submit(fn, *args, **kwargs)
        self._futures[future] = task_id
        return future

    def wait_all(self, timeout: Optional[float] = None) -> dict[str, WorkerResult]:
        """
        Wait for all submitted tasks to complete.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Dict mapping task_id to WorkerResult
        """
        results = {}

        for future in as_completed(list(self._futures.keys()), timeout=timeout):
            task_id = self._futures[future]
            try:
                result = future.result()
                results[task_id] = WorkerResult(
                    task_id=task_id,
                    success=True,
                    result=result
                )
            except Exception as e:
                results[task_id] = WorkerResult(
                    task_id=task_id,
                    success=False,
                    result=None,
                    error=str(e)
                )

        self._results.update(results)
        return results

    def wait_one(self, timeout: Optional[float] = None) -> Optional[WorkerResult]:
        """
        Wait for the next task to complete.

        Args:
            timeout: Optional timeout in seconds

        Returns:
            WorkerResult or None if timeout
        """
        if not self._futures:
            return None

        try:
            future = next(as_completed(list(self._futures.keys()), timeout=timeout))
            task_id = self._futures.pop(future)

            try:
                result = future.result()
                worker_result = WorkerResult(
                    task_id=task_id,
                    success=True,
                    result=result
                )
            except Exception as e:
                worker_result = WorkerResult(
                    task_id=task_id,
                    success=False,
                    result=None,
                    error=str(e)
                )

            self._results[task_id] = worker_result
            return worker_result

        except StopIteration:
            return None

    def cancel(self, task_id: str) -> bool:
        """Cancel a specific task if still running"""
        for future, tid in self._futures.items():
            if tid == task_id:
                return future.cancel()
        return False

    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the worker pool.

        Args:
            wait: Whether to wait for pending tasks
        """
        self.executor.shutdown(wait=wait)

    @property
    def pending_count(self) -> int:
        """Number of pending tasks"""
        return len(self._futures)

    @property
    def completed_count(self) -> int:
        """Number of completed tasks"""
        return len(self._results)

    def get_result(self, task_id: str) -> Optional[WorkerResult]:
        """Get result for a specific task"""
        return self._results.get(task_id)
