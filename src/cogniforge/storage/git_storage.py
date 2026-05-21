"""Git storage - persistent storage layer using Git"""

from pathlib import Path
from typing import Optional
from datetime import datetime

from git import Repo, GitCommandError, InvalidGitRepositoryError

from cogniforge.core.exceptions import GitStorageError


class GitStorage:
    """
    Git-based persistent storage.

    All operations (code + docs + reports) must be committed to Git.
    """

    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path)
        try:
            self.repo = Repo(self.repo_path)
        except (GitCommandError, InvalidGitRepositoryError):
            self.repo = Repo.init(self.repo_path)

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
        """Commit staged changes"""
        try:
            # Format: system <system@local>
            repo = self.repo
            commit = repo.index.commit(message)
            return commit.hexsha
        except GitCommandError as e:
            raise GitStorageError(f"Failed to commit: {e}")

    def commit_to_wiki_branch(self, files: list[str], message: str,
                              author: str = "system") -> str | None:
        """将指定文件提交到 wiki 分支（通过临时 worktree）。

        files 会被复制到 wiki 分支的 worktree 中提交，
        提交后当前索引中的这些文件会被 unstage。
        """
        import shutil
        import tempfile

        repo = self.repo
        wiki_branch = "wiki"

        # 确保 wiki 分支存在
        if wiki_branch not in [b.name for b in repo.branches]:
            repo.create_head(wiki_branch)

        worktree_dir = None
        try:
            worktree_dir = tempfile.mkdtemp(prefix="cogniforge-wiki-")
            repo.git.worktree("add", worktree_dir, wiki_branch)

            wt_root = Path(worktree_dir)

            # 复制文件到 worktree
            for f in files:
                src = self.repo_path / f
                dst = wt_root / f
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                else:
                    # 文件已删除 — 在 worktree 中也删除
                    if dst.exists():
                        dst.unlink()

            # 在 worktree 中提交
            wt_repo = Repo(worktree_dir)
            if files:
                wt_repo.index.add(files)
            commit = wt_repo.index.commit(message)
            commit_hash = commit.hexsha

            return commit_hash
        except GitCommandError as e:
            raise GitStorageError(f"Failed to commit to wiki branch: {e}")
        finally:
            if worktree_dir and Path(worktree_dir).exists():
                try:
                    repo.git.worktree("remove", worktree_dir, "--force")
                except GitCommandError:
                    pass
                shutil.rmtree(worktree_dir, ignore_errors=True)

            # 从当前索引中 unstage wiki 文件
            try:
                repo.index.remove(files, working_tree=False)
            except GitCommandError:
                pass

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
