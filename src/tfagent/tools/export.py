"""Pipeline hand-off: export the workspace's HCL to the repo the pipeline
deploys from.

The agent never deploys for real — in both flows the actual deployment runs
from the user's repo pipeline. This tool moves ONLY the Terraform source
(`*.tf`, minus `.terraform/`) across that boundary: state files, saved plans,
and `.env` never leave the workspace.

Two targets, chosen by configuration:
- ``TFAGENT_EXPORT_REPO`` points at a local clone of the pipeline repo: the
  files are committed to a new branch there and pushed (push failure is
  reported, not fatal — the commit still exists locally).
- Unset: the files are copied to an ``export/`` bundle directory next to the
  workspace for the human to move themselves.

Git is invoked with argument arrays (never ``shell=True``), mirroring
``runner.py``'s discipline.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from agent_framework import tool

from ..runner import TerraformError, TerraformRunner
from .hcl_guard import assert_hcl_is_safe

EXPORT_TOOL_NAME = "export_to_repo"

_BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_GIT_TIMEOUT_SECONDS = 120


def _collect_tf_files(workspace: Path) -> list[Path]:
    return [p for p in sorted(workspace.rglob("*.tf")) if ".terraform" not in p.parts]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
        check=False,
    )


def _copy_files(files: list[Path], workspace: Path, dest: Path) -> list[str]:
    copied: list[str] = []
    for src in files:
        rel = src.relative_to(workspace)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(str(rel))
    return copied


def _export_via_git(
    files: list[Path],
    workspace: Path,
    repo: Path,
    subdir: str,
    branch_name: str,
    commit_message: str,
) -> str:
    checkout = _git(repo, "checkout", "-B", branch_name)
    if checkout.returncode != 0:
        raise TerraformError(f"git checkout -B {branch_name} failed: {checkout.stderr.strip()}")

    copied = _copy_files(files, workspace, repo / subdir)

    add = _git(repo, "add", "--", subdir)
    if add.returncode != 0:
        raise TerraformError(f"git add failed: {add.stderr.strip()}")

    commit = _git(repo, "commit", "-m", commit_message)
    if commit.returncode != 0:
        combined = (commit.stdout + commit.stderr).lower()
        if "nothing to commit" in combined:
            return (
                f"Nothing to commit: branch '{branch_name}' already matches the "
                f"workspace ({len(copied)} file(s) unchanged)."
            )
        raise TerraformError(f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")

    lines = [
        f"Committed {len(copied)} file(s) to branch '{branch_name}' in {repo} "
        f"(under {subdir}/): " + ", ".join(copied)
    ]
    push = _git(repo, "push", "-u", "origin", branch_name)
    if push.returncode == 0:
        lines.append(f"Pushed to origin/{branch_name}. The pipeline can deploy from there.")
    else:
        lines.append(
            "Push to origin failed (the commit exists locally; the human can push): "
            + (push.stderr.strip() or push.stdout.strip())
        )
    return "\n".join(lines)


def _export_bundle(files: list[Path], workspace: Path, branch_name: str) -> str:
    safe = branch_name.replace("/", "-")
    dest = workspace.parent / "export" / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}"
    dest.mkdir(parents=True, exist_ok=True)
    copied = _copy_files(files, workspace, dest)
    return (
        f"No TFAGENT_EXPORT_REPO configured; wrote an export bundle instead.\n"
        f"Copied {len(copied)} file(s) to {dest}: " + ", ".join(copied) + "\n"
        "Move these into the pipeline repo to deploy."
    )


def build_export_tool(runner: TerraformRunner, export_repo: Path | None, export_subdir: str):
    """Return the human-gated export_to_repo tool, closed over the runner."""

    @tool(approval_mode="always_require")
    def export_to_repo(branch_name: str, commit_message: str) -> str:
        """Export the workspace's Terraform source files (*.tf only — never
        state, saved plans, or .env) for deployment by the user's pipeline.
        With TFAGENT_EXPORT_REPO configured this commits to a new branch of
        that repo and pushes; otherwise it writes an export bundle directory.
        Requires explicit human approval. Use a descriptive branch name such
        as 'tfagent/add-storage-account'."""
        if not _BRANCH_RE.fullmatch(branch_name) or ".." in branch_name:
            raise TerraformError(f"Branch name {branch_name!r} is not a safe git branch name.")
        if not commit_message.strip():
            raise TerraformError("Commit message must not be empty.")

        assert_hcl_is_safe(runner.workspace)
        files = _collect_tf_files(runner.workspace)
        if not files:
            raise TerraformError("No .tf files found in the workspace to export.")

        if export_repo is not None:
            if not (export_repo / ".git").is_dir():
                raise TerraformError(
                    f"TFAGENT_EXPORT_REPO={export_repo} is not a git repository "
                    "(no .git directory)."
                )
            return _export_via_git(
                files, runner.workspace, export_repo, export_subdir, branch_name, commit_message
            )
        return _export_bundle(files, runner.workspace, branch_name)

    return export_to_repo
