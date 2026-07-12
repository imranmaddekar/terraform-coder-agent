"""Terraform tools exposed to the agent.

Each operation is its OWN tool (not one generic shell) so the approval layer
can key rules off tool names: init/validate/fmt/plan auto-approve, apply is
human-gated. The functions are plain typed Python; MAF turns the signature +
docstring into the tool schema the model sees.
"""
from __future__ import annotations

from agent_framework import tool

from ..runner import TerraformRunner
from .plan_summary import assert_plan_is_non_destructive

# Module-level runner set once at startup by build_terraform_tools().
_runner: TerraformRunner | None = None


def _r() -> TerraformRunner:
    if _runner is None:
        raise RuntimeError("Terraform tools not initialised. Call build_terraform_tools().")
    return _runner


@tool(approval_mode="never_require")
def tf_fmt() -> str:
    """Format all Terraform files in the workspace (terraform fmt -recursive)."""
    return _r().run("fmt", "-recursive").as_feedback()


@tool(approval_mode="never_require")
def tf_validate() -> str:
    """Validate the Terraform configuration syntax and internal consistency."""
    return _r().run("validate", "-no-color").as_feedback()


@tool(approval_mode="never_require")
def tf_init() -> str:
    """Initialise the working directory: download providers and modules.
    Uses LOCAL state (no remote backend configured)."""
    return _r().run("init", "-no-color", "-input=false").as_feedback()


@tool(approval_mode="never_require")
def tf_plan() -> str:
    """Create an execution plan and save it to 'plan.tfplan' for later apply.
    Read-only against real infrastructure; safe to auto-approve."""
    return _r().run("plan", "-no-color", "-input=false", "-out=plan.tfplan").as_feedback()


@tool(approval_mode="always_require")
def tf_apply() -> str:
    """Apply the previously saved plan ('plan.tfplan') to REAL Azure infrastructure.
    This is a sensitive, mutating action and requires explicit human approval.
    Never bypasses approval; '-auto-approve' is blocked at the runner level."""
    assert_plan_is_non_destructive(_r())
    return _r().run("apply", "-no-color", "-input=false", "plan.tfplan").as_feedback()


def build_terraform_tools(runner: TerraformRunner):
    """Wire the runner and return the callables to register as agent tools."""
    global _runner
    _runner = runner
    return [tf_fmt, tf_validate, tf_init, tf_plan, tf_apply]


# Names the approval layer treats as auto-approvable (read-only-ish).
READ_ONLY_TOOL_NAMES = {"tf_fmt", "tf_validate", "tf_init", "tf_plan"}
# Names that always require a human.
APPROVAL_REQUIRED_TOOL_NAMES = {"tf_apply"}
