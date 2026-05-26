"""Git storage - persistent storage layer using Git"""

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from datetime import datetime

from git import Repo, GitCommandError, InvalidGitRepositoryError

from cogniforge.core.config import Config
from cogniforge.core.exceptions import GitStorageError


class GitStorage:
    """
    Git-based persistent storage.

    All operations (code + docs + reports) must be committed to Git.
    """

    def __init__(self, repo_path: Path, config: Config | None = None):
        self.repo_path = Path(repo_path)
        self.config = config or Config(repo_path=self.repo_path)
        self._write_lock = threading.Lock()
        try:
            self.repo = Repo(self.repo_path)
        except (GitCommandError, InvalidGitRepositoryError):
            self.repo = Repo.init(self.repo_path)

    @contextmanager
    def atomic_write(self):
        """Context manager serializing index.add() + commit() across threads."""
        with self._write_lock:
            yield

    def read_file(self, relative_path: str) -> Optional[str]:
        """Read file content from Git working directory"""
        file_path = self.repo_path / relative_path
        if not file_path.exists():
            return None

        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as e:
            raise GitStorageError(f"Failed to read {relative_path}: {e}")

    def write_file(
        self,
        relative_path: str,
        content: str,
        message: Optional[str] = None,
        author: str = "system"
    ) -> None:
        """Write file content and optionally commit"""
        file_path = self.repo_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            file_path.write_text(content, encoding="utf-8")
            self.repo.index.add([relative_path])

            if message:
                self.commit(message, author)
        except Exception as e:
            raise GitStorageError(f"Failed to write {relative_path}: {e}")

    def delete_file(self, relative_path: str, message: Optional[str] = None) -> None:
        """Delete file and optionally commit"""
        file_path = self.repo_path / relative_path
        if not file_path.exists():
            return

        try:
            file_path.unlink()
            self.repo.index.remove([relative_path])

            if message:
                self.commit(message)
        except Exception as e:
            raise GitStorageError(f"Failed to delete {relative_path}: {e}")

    def commit(self, message: str, author: str = "system") -> str:
        """Commit staged changes (thread-safe when used inside atomic_write())."""
        try:
            commit = self.repo.index.commit(message)
            return commit.hexsha
        except GitCommandError as e:
            raise GitStorageError(f"Failed to commit: {e}")

    def _wiki_repo(self) -> Repo:
        """获取 wiki 独立仓库，不是 git repo 则自动初始化。"""
        wiki_path = self.repo_path / ".cogniforge/wiki"
        try:
            return Repo(wiki_path)
        except (GitCommandError, InvalidGitRepositoryError):
            return self._init_wiki_repo(wiki_path)

    def _init_wiki_repo(self, wiki_path: Path) -> Repo:
        """在 wiki_path 初始化独立 git 仓库，配置 remote，提交存量文件。"""
        wiki_repo = Repo.init(wiki_path)
        remote_url = self.config.wiki.repo_url
        if remote_url:
            try:
                wiki_repo.create_remote("origin", remote_url)
            except GitCommandError:
                pass  # remote 已存在

        # 将已有文件全部纳入初始 commit
        wiki_repo.index.add("*")
        wiki_repo.index.commit("chore: wiki 仓库初始化")
        return wiki_repo

    def commit_wiki(self, files: list[str], message: str,
                    author: str = "system") -> str | None:
        """在 wiki 独立仓库内提交。无变更时返回 None。

        files 参数是主仓库相对路径（如 .cogniforge/wiki/prd/x.json），
        方法内部自动转换为 wiki 仓库相对路径（如 prd/x.json）。
        """
        wiki_repo = self._wiki_repo()
        prefix = ".cogniforge/wiki" + "/"
        wiki_files = [f[len(prefix):] if f.startswith(prefix) else f for f in files]

        wiki_repo.index.add(wiki_files)

        try:
            head_valid = wiki_repo.head.is_valid()
        except (ValueError, GitCommandError):
            head_valid = False

        if head_valid and not wiki_repo.index.diff("HEAD"):
            return None

        commit = wiki_repo.index.commit(message)
        return commit.hexsha

    def push_wiki(self) -> None:
        """推送 wiki 仓库到远程。无 remote 或 push 失败时 warning，不阻断。"""
        wiki_path = self.repo_path / ".cogniforge/wiki"
        if not (wiki_path / ".git").exists():
            return
        try:
            wiki_repo = Repo(wiki_path)
            wiki_repo.remote("origin").push()
        except (GitCommandError, ValueError):
            pass  # 无 remote 或无网络时静默跳过

    def get_status(self) -> dict:
        """Get Git status"""
        status = {
            "modified": [],
            "staged": [],
            "untracked": [],
            "branch": self.repo.active_branch.name,
        }

        for item in self.repo.index.diff("HEAD"):
            status["modified"].append(item.a_path)

        for item in self.repo.index.diff(None):
            if item.b_path not in status["modified"]:
                status["modified"].append(item.b_path)

        for path in self.repo.untracked_files:
            status["untracked"].append(path)

        staged = [item.a_path for item in self.repo.index.diff("HEAD")]
        status["staged"] = staged

        return status

    def log(self, max_count: int = 10) -> list[dict]:
        """Get commit log"""
        commits = []
        for commit in self.repo.iter_commits(max_count=max_count):
            commits.append({
                "hexsha": commit.hexsha,
                "message": commit.message.strip(),
                "author": str(commit.author),
                "committed_date": datetime.fromtimestamp(commit.committed_date),
            })
        return commits

    def checkout(self, branch: str) -> None:
        """Checkout a branch"""
        try:
            if branch not in [b.name for b in self.repo.branches]:
                self.repo.git.checkout("-b", branch)
            else:
                self.repo.git.checkout(branch)
        except GitCommandError as e:
            raise GitStorageError(f"Failed to checkout {branch}: {e}")

    def create_branch(self, branch_name: str) -> None:
        """Create a new branch"""
        try:
            self.repo.git.checkout("-b", branch_name)
        except GitCommandError as e:
            raise GitStorageError(f"Failed to create branch {branch_name}: {e}")

    def get_file_history(self, relative_path: str, max_count: int = 10) -> list[dict]:
        """Get file change history"""
        try:
            commits = []
            for commit in self.repo.iter_commits(paths=relative_path, max_count=max_count):
                commits.append({
                    "hexsha": commit.hexsha,
                    "message": commit.message.strip(),
                    "author": str(commit.author),
                    "committed_date": datetime.fromtimestamp(commit.committed_date),
                })
            return commits
        except GitCommandError:
            return []

    def get_latest_commit(self, relative_path: str) -> Optional[dict]:
        """Get the latest commit for a file"""
        try:
            commit = self.repo.git.log("-1", "--format=%H|%s|%an|%at", "--", relative_path)
            if not commit:
                return None

            parts = commit.split("|")
            if len(parts) == 4:
                return {
                    "hexsha": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "committed_date": datetime.fromtimestamp(int(parts[3])),
                }
        except GitCommandError:
            return None

        return None
