"""Terraform tools exposed to the agent.

Each operation is its OWN tool (not one generic shell) so the approval layer
can key rules off tool names: init/validate/fmt/plan auto-approve, apply is
human-gated. The functions are plain typed Python; MAF turns the signature +
docstring into the tool schema the model sees.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from agent_framework import tool

from ..runner import TerraformError, TerraformRunner
from .hcl_guard import assert_hcl_is_safe
from .plan_summary import assert_plan_is_non_destructive

# Names the approval layer treats as auto-approvable (read-only-ish).
READ_ONLY_TOOL_NAMES = {"tf_fmt", "tf_validate", "tf_init", "tf_plan"}
# Names that always require a human.
APPROVAL_REQUIRED_TOOL_NAMES = {"tf_apply"}


def _plan_fingerprint(workspace: Path) -> str | None:
    """Hash of the saved plan file, or None if it doesn't exist."""
    plan_path = workspace / "plan.tfplan"
    if not plan_path.is_file():
        return None
    return hashlib.sha256(plan_path.read_bytes()).hexdigest()


def build_terraform_tools(runner: TerraformRunner) -> list:
    """Wire the runner and return the callables to register as agent tools.

    Each tool closes over ``runner`` directly rather than a module-level
    singleton, so multiple agents (or tests) built in the same process each
    get their own isolated runner and plan-fingerprint state.
    """
    # Fingerprint of the plan.tfplan produced by tf_plan in THIS build's
    # session. tf_apply refuses to run against any other file on disk —
    # including a stale plan.tfplan left over from a previous session, or one
    # the model never actually (re-)generated — so an approved apply always
    # corresponds to a plan that was just produced (and can be summarized)
    # in this run, never a leftover on disk.
    last_plan_hash: dict[str, str | None] = {"value": None}

    @tool(approval_mode="never_require")
    def tf_fmt() -> str:
        """Format all Terraform files in the workspace (terraform fmt -recursive)."""
        return runner.run("fmt", "-recursive").as_feedback()

    @tool(approval_mode="never_require")
    def tf_validate() -> str:
        """Validate the Terraform configuration syntax and internal consistency."""
        return runner.run("validate", "-no-color").as_feedback()

    @tool(approval_mode="never_require")
    def tf_init() -> str:
        """Initialise the working directory: download providers and modules.
        Uses LOCAL state (no remote backend configured)."""
        assert_hcl_is_safe(runner.workspace)
        return runner.run("init", "-no-color", "-input=false").as_feedback()

    @tool(approval_mode="never_require")
    def tf_plan() -> str:
        """Create an execution plan and save it to 'plan.tfplan' for later apply.
        Read-only against real infrastructure; safe to auto-approve."""
        assert_hcl_is_safe(runner.workspace)
        result = runner.run("plan", "-no-color", "-input=false", "-out=plan.tfplan")
        last_plan_hash["value"] = _plan_fingerprint(runner.workspace) if result.ok else None
        return result.as_feedback()

    @tool(approval_mode="always_require")
    def tf_apply() -> str:
        """Apply the previously saved plan ('plan.tfplan') to REAL Azure infrastructure.
        This is a sensitive, mutating action and requires explicit human approval.
        Never bypasses approval; '-auto-approve' is blocked at the runner level."""
        assert_hcl_is_safe(runner.workspace)
        current = _plan_fingerprint(runner.workspace)
        if current is None:
            raise TerraformError("No saved plan found. Run tf_plan before tf_apply.")
        if current != last_plan_hash["value"]:
            raise TerraformError(
                "The saved plan.tfplan does not match a plan produced by tf_plan in "
                "this session (it may be stale, left over from a previous run, or the "
                "workspace changed since the last tf_plan). Run tf_plan again, review "
                "the new diff, and re-request approval before applying."
            )
        assert_plan_is_non_destructive(runner)
        result = runner.run("apply", "-no-color", "-input=false", "plan.tfplan")
        if result.ok:
            (runner.workspace / "plan.tfplan").unlink(missing_ok=True)
            last_plan_hash["value"] = None
        return result.as_feedback()

    return [tf_fmt, tf_validate, tf_init, tf_plan, tf_apply]
