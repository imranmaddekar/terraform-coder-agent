import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tfagent.flow import GREENFIELD, FlowState
from tfagent.runner import TerraformError, TerraformRunner
from tfagent.tools.export import build_export_tool

GIT = shutil.which("git")


def make_runner(tmp_path: Path) -> TerraformRunner:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        return TerraformRunner(tmp_path, flow_state=FlowState(flow=GREENFIELD))


def seed_workspace(workspace: Path) -> None:
    (workspace / "main.tf").write_text('resource "azurerm_resource_group" "rg" {}\n', encoding="utf-8")
    (workspace / "modules" / "net").mkdir(parents=True)
    (workspace / "modules" / "net" / "vnet.tf").write_text("# vnet\n", encoding="utf-8")
    # Things that must NEVER be exported.
    (workspace / "terraform.tfstate").write_text('{"secret": true}', encoding="utf-8")
    (workspace / "plan.tfplan").write_bytes(b"plan-bytes")
    (workspace / ".env").write_text("ARM_CLIENT_SECRET=hunter2", encoding="utf-8")
    (workspace / ".terraform").mkdir()
    (workspace / ".terraform" / "cached.tf").write_text("# provider cache\n", encoding="utf-8")


def test_export_bundle_copies_tf_files_and_nothing_else(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    seed_workspace(workspace)
    export_to_repo = build_export_tool(make_runner(workspace), None, "terraform")

    feedback = export_to_repo("tfagent/add-rg", "Add resource group")

    bundles = list((tmp_path / "export").iterdir())
    assert len(bundles) == 1
    bundle = bundles[0]
    exported = sorted(str(p.relative_to(bundle)) for p in bundle.rglob("*") if p.is_file())
    assert exported == ["main.tf", "modules/net/vnet.tf"]
    assert "export bundle" in feedback


def test_export_rejects_unsafe_branch_names(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "main.tf").write_text("# tf\n", encoding="utf-8")
    export_to_repo = build_export_tool(make_runner(workspace), None, "terraform")

    for bad in ("-rf", "a..b", "bad name", "", "--force"):
        with pytest.raises(TerraformError, match="not a safe git branch name"):
            export_to_repo(bad, "msg")


def test_export_rejects_empty_workspace_and_empty_message(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    export_to_repo = build_export_tool(make_runner(workspace), None, "terraform")
    with pytest.raises(TerraformError, match="Commit message"):
        export_to_repo("branch", "  ")
    with pytest.raises(TerraformError, match="No .tf files"):
        export_to_repo("branch", "msg")


def test_export_is_blocked_by_the_hcl_guard(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "main.tf").write_text('provisioner "local-exec" {}\n', encoding="utf-8")
    export_to_repo = build_export_tool(make_runner(workspace), None, "terraform")
    with pytest.raises(TerraformError, match="HCL safety guard"):
        export_to_repo("branch", "msg")


def test_export_requires_a_real_git_repo_when_configured(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "main.tf").write_text("# tf\n", encoding="utf-8")
    not_a_repo = tmp_path / "repo"
    not_a_repo.mkdir()
    export_to_repo = build_export_tool(make_runner(workspace), not_a_repo, "terraform")
    with pytest.raises(TerraformError, match="not a git repository"):
        export_to_repo("branch", "msg")


@pytest.mark.skipif(GIT is None, reason="git is not installed")
def test_export_commits_to_a_new_branch_of_the_pipeline_repo(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    seed_workspace(workspace)

    repo = tmp_path / "pipeline-repo"
    repo.mkdir()
    def git(*args: str) -> None:
        subprocess.run(
            [GIT, "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
            check=True, capture_output=True, text=True,
        )
    git("init", "-b", "main")
    (repo / "README.md").write_text("# pipeline\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "init")

    export_to_repo = build_export_tool(make_runner(workspace), repo, "terraform")
    with patch.dict("os.environ", {"GIT_AUTHOR_EMAIL": "t@t", "GIT_AUTHOR_NAME": "t",
                                   "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}):
        feedback = export_to_repo("tfagent/add-rg", "Add resource group")

    assert "Committed 2 file(s) to branch 'tfagent/add-rg'" in feedback
    # No remote configured — push failure is reported, not fatal.
    assert "Push to origin failed" in feedback
    assert (repo / "terraform" / "main.tf").is_file()
    assert (repo / "terraform" / "modules" / "net" / "vnet.tf").is_file()
    assert not (repo / "terraform" / "terraform.tfstate").exists()
    assert not (repo / "terraform" / "plan.tfplan").exists()
    assert not (repo / "terraform" / ".env").exists()

    head = subprocess.run(
        [GIT, "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert head == "tfagent/add-rg"
