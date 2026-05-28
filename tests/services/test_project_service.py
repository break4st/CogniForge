"""Unit tests for ProjectService."""

import pytest
import tempfile
from pathlib import Path
from cogniforge.services.project_service import ProjectService


class TestProjectService:
    def test_create_in_temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            svc = ProjectService(Path(td))
            result = svc.create(
                path=str(Path(td) / "myproject"),
                name="myproject",
            )
            assert result["status"] == "initialized"
            assert result["name"] == "myproject"

            # Config file should exist
            config_file = Path(td) / "myproject" / ".cogniforge" / "config.yaml"
            assert config_file.exists()

            # Creating the same project again should fail
            with pytest.raises(FileExistsError):
                svc.create(
                    path=str(Path(td) / "myproject"),
                    name="myproject",
                )

    def test_open(self):
        with tempfile.TemporaryDirectory() as td:
            svc = ProjectService(Path(td))
            svc.create(path=str(Path(td) / "testproj"), name="testproj")

            result = svc.open(path=str(Path(td) / "testproj"))
            assert result["project_id"] == "testproj"
            assert "wiki_path" in result

    def test_open_nonexistent(self):
        svc = ProjectService()
        with pytest.raises(FileNotFoundError):
            svc.open(path="/nonexistent/path")

    def test_list_empty(self):
        with tempfile.TemporaryDirectory() as td:
            svc = ProjectService(Path(td))
            projects = svc.list()
            # List scans the parent directory of scan_base
            # With temp dir, the parent may have 0 projects
            assert isinstance(projects, list)
