"""Project management service — CRUD for CogniForge projects."""

from __future__ import annotations

from pathlib import Path


class ProjectService:
    """Manage CogniForge projects on the local filesystem.

    A "project" is any directory containing a .cogniforge/config.yaml file.
    """

    def __init__(self, scan_base: Path | None = None):
        self._scan_base = scan_base or Path.cwd()

    def list(self) -> list[dict]:
        """Scan the parent directory for CogniForge projects."""
        projects = []
        try:
            parent = self._scan_base.parent
        except Exception:
            parent = self._scan_base

        if not parent.exists():
            return projects

        for child in sorted(parent.iterdir()):
            if not child.is_dir():
                continue
            config_file = child / ".cogniforge" / "config.yaml"
            if config_file.exists():
                projects.append({
                    "project_id": child.name,
                    "name": child.name,
                    "path": str(child.resolve()),
                })
        return projects

    def create(self, path: str, name: str) -> dict:
        """Initialize a new CogniForge project at the given path."""
        target = Path(path).resolve()
        config_file = target / ".cogniforge" / "config.yaml"
        if config_file.exists():
            raise FileExistsError(f"Project already exists at {target}")

        # Create wiki directory structure
        wiki_dirs = ["prd", "sad", "lld", "decisions", "tasks", "qa", "reports", "ops"]
        for d in wiki_dirs:
            (target / ".cogniforge" / "wiki" / d).mkdir(parents=True, exist_ok=True)

        # Write default config
        from cogniforge.core.config import DEFAULT_CONFIG_YAML
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")

        return {
            "project_id": name,
            "name": name,
            "path": str(target),
            "status": "initialized",
        }

    def open(self, project_id: str = "", path: str = "") -> dict:
        """Open a project and return a summary.

        Prefer path if given; otherwise look up by project_id.
        Returns project metadata without initializing the full agent context.
        """
        if path:
            repo_path = Path(path).resolve()
        elif project_id:
            projects = self.list()
            match = next(
                (p for p in projects if p["project_id"] == project_id), None
            )
            if match is None:
                raise FileNotFoundError(
                    f"Project '{project_id}' not found"
                )
            repo_path = Path(match["path"])
        else:
            raise ValueError("Either project_id or path is required")

        if not repo_path.exists():
            raise FileNotFoundError(f"Path does not exist: {repo_path}")

        config_file = repo_path / ".cogniforge" / "config.yaml"
        if not config_file.exists():
            raise FileNotFoundError(
                f"No .cogniforge/config.yaml found at {repo_path}"
            )

        return {
            "project_id": repo_path.name,
            "path": str(repo_path),
            "wiki_path": str(repo_path / ".cogniforge" / "wiki"),
        }
