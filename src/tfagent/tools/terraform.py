"""Terraform tools exposed to the agent.

Each operation is its OWN tool (not one generic shell) so the approval layer
can key rules off tool names: init/validate/fmt/plan auto-approve, apply and
sandbox teardown are human-gated. The functions are plain typed Python; MAF
turns the signature + docstring into the tool schema the model sees.

Flow gating: mutating tools consult the runner's FlowState. Until the human
chooses a flow they refuse to run; in brownfield tf_apply and the teardown
pair are disabled outright (the plan diff is the deliverable — the user's
pipeline applies).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from agent_framework import tool

from ..flow import BROWNFIELD, GREENFIELD
from ..runner import DESTROY_PLAN_FILENAME, TerraformError, TerraformRunner
from .hcl_guard import assert_hcl_is_safe
from .plan_summary import assert_plan_is_destroy_only, assert_plan_is_non_destructive

# Names the approval layer treats as auto-approvable (read-only-ish).
READ_ONLY_TOOL_NAMES = {
    "tf_fmt", "tf_validate", "tf_init", "tf_plan", "tf_plan_destroy",
    "tf_state_list", "tf_state_show",
}
# Names that always require a human.
APPROVAL_REQUIRED_TOOL_NAMES = {"tf_apply", "tf_destroy_sandbox"}


def _file_fingerprint(path: Path) -> str | None:
    """Hash of a saved plan file, or None if it doesn't exist."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_flow(runner: TerraformRunner) -> str:
    flow_state = runner.flow_state
    if flow_state is None or flow_state.flow is None:
        raise TerraformError(
            "No session flow chosen yet. Ask the human whether this is a "
            "greenfield build or a brownfield change to deployed infrastructure, "
            "then call set_session_flow with their answer."
        )
    return flow_state.flow


def build_terraform_tools(runner: TerraformRunner) -> list:
    """Wire the runner and return the callables to register as agent tools.

    Each tool closes over ``runner`` directly rather than a module-level
    singleton, so multiple agents (or tests) built in the same process each
    get their own isolated runner and plan-fingerprint state.
    """
    # Fingerprints of the plan files produced by tf_plan / tf_plan_destroy in
    # THIS build's session. tf_apply / tf_destroy_sandbox refuse to run
    # against any other file on disk — including a stale file left over from
    # a previous session, or one the model never actually (re-)generated —
    # so an approved apply always corresponds to a plan that was just
    # produced (and can be summarized) in this run, never a leftover on disk.
    last_plan_hash: dict[str, str | None] = {"value": None}
    last_destroy_hash: dict[str, str | None] = {"value": None}

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
        Read-only against real infrastructure; safe to auto-approve. In the
        brownfield flow the resulting diff is the deliverable."""
        assert_hcl_is_safe(runner.workspace)
        result = runner.run("plan", "-no-color", "-input=false", "-out=plan.tfplan")
        last_plan_hash["value"] = _file_fingerprint(runner.workspace / "plan.tfplan") if result.ok else None
        return result.as_feedback()

    @tool(approval_mode="always_require")
    def tf_apply() -> str:
        """Apply the previously saved plan ('plan.tfplan') to the REAL Azure
        sandbox subscription. Greenfield flow only — sandbox self-validation
        before pipeline deployment; disabled in brownfield. This is a
        sensitive, mutating action and requires explicit human approval.
        Never bypasses approval; '-auto-approve' is blocked at the runner level."""
        flow = _require_flow(runner)
        if flow == BROWNFIELD:
            raise TerraformError(
                "tf_apply is disabled in the brownfield flow. The plan diff is "
                "the deliverable; the real change is applied by the user's "
                "pipeline. Offer export_to_repo instead."
            )
        assert_hcl_is_safe(runner.workspace)
        current = _file_fingerprint(runner.workspace / "plan.tfplan")
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
            runner.flow_state.applied_this_session = True
        return result.as_feedback()

    @tool(approval_mode="never_require")
    def tf_plan_destroy() -> str:
        """Create a destroy plan for the greenfield sandbox and save it to
        'destroy.tfplan'. Only valid after a successful tf_apply in this
        session, once the human has confirmed the applied result looks good.
        Read-only; the teardown itself is tf_destroy_sandbox (human-gated)."""
        flow = _require_flow(runner)
        if flow != GREENFIELD:
            raise TerraformError("Sandbox teardown is only available in the greenfield flow.")
        if not runner.flow_state.applied_this_session:
            raise TerraformError(
                "Nothing to tear down: no successful tf_apply has happened in "
                "this session."
            )
        assert_hcl_is_safe(runner.workspace)
        result = runner.run_destroy_plan()
        destroy_path = runner.workspace / DESTROY_PLAN_FILENAME
        last_destroy_hash["value"] = _file_fingerprint(destroy_path) if result.ok else None
        return result.as_feedback()

    @tool(approval_mode="always_require")
    def tf_destroy_sandbox() -> str:
        """Apply the saved destroy plan ('destroy.tfplan'), tearing down the
        greenfield sandbox resources this session created. Requires explicit
        human approval; the approval card shows the destroy diff. Only allowed
        after tf_plan_destroy in this session, and never in brownfield."""
        flow = _require_flow(runner)
        if flow != GREENFIELD:
            raise TerraformError("Sandbox teardown is only available in the greenfield flow.")
        assert_hcl_is_safe(runner.workspace)
        destroy_path = runner.workspace / DESTROY_PLAN_FILENAME
        current = _file_fingerprint(destroy_path)
        if current is None:
            raise TerraformError("No saved destroy plan found. Run tf_plan_destroy first.")
        if current != last_destroy_hash["value"]:
            raise TerraformError(
                "The saved destroy.tfplan does not match a plan produced by "
                "tf_plan_destroy in this session. Run tf_plan_destroy again, "
                "review the diff, and re-request approval."
            )
        assert_plan_is_destroy_only(runner, DESTROY_PLAN_FILENAME)
        result = runner.run("apply", "-no-color", "-input=false", DESTROY_PLAN_FILENAME)
        if result.ok:
            destroy_path.unlink(missing_ok=True)
            last_destroy_hash["value"] = None
            runner.flow_state.applied_this_session = False
        return result.as_feedback()

    @tool(approval_mode="never_require")
    def tf_state_list() -> str:
        """List the resources tracked in the Terraform state (read-only).
        Useful in brownfield to see what is currently deployed."""
        return runner.run_state_read("list").as_feedback()

    @tool(approval_mode="never_require")
    def tf_state_show(address: str) -> str:
        """Show a single resource from the Terraform state (read-only), e.g.
        address='azurerm_resource_group.demo_rg'. Mutating state commands
        (rm, mv, push, ...) are blocked at the runner level."""
        return runner.run_state_read("show", address).as_feedback()

    return [
        tf_fmt, tf_validate, tf_init, tf_plan, tf_apply,
        tf_plan_destroy, tf_destroy_sandbox, tf_state_list, tf_state_show,
    ]
