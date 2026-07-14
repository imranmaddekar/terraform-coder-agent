import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tfagent.flow import BROWNFIELD, GREENFIELD, FlowState
from tfagent.runner import TerraformError, TerraformRunner, TfResult
from tfagent.tools.terraform import build_terraform_tools


def make_runner(tmp_path: Path, flow: str | None = GREENFIELD) -> TerraformRunner:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        return TerraformRunner(tmp_path, flow_state=FlowState(flow=flow))


def make_tools(runner: TerraformRunner) -> SimpleNamespace:
    (
        tf_fmt, tf_validate, tf_init, tf_plan, tf_apply,
        tf_plan_destroy, tf_destroy_sandbox, tf_state_list, tf_state_show,
    ) = build_terraform_tools(runner)
    return SimpleNamespace(
        tf_fmt=tf_fmt, tf_validate=tf_validate, tf_init=tf_init,
        tf_plan=tf_plan, tf_apply=tf_apply, tf_plan_destroy=tf_plan_destroy,
        tf_destroy_sandbox=tf_destroy_sandbox, tf_state_list=tf_state_list,
        tf_state_show=tf_state_show,
    )


def _ok(cmd: str, out: str = "") -> TfResult:
    return TfResult(cmd, 0, out, "")


def test_tf_apply_without_any_plan_is_refused(tmp_path: Path) -> None:
    tools = make_tools(make_runner(tmp_path))
    with pytest.raises(TerraformError, match="No saved plan found"):
        tools.tf_apply()


def test_tf_apply_refuses_a_plan_file_not_produced_by_tf_plan_this_session(tmp_path: Path) -> None:
    # Simulates a plan.tfplan left over from a previous run/session, or one
    # the model never actually (re-)generated in this run.
    (tmp_path / "plan.tfplan").write_bytes(b"stale-plan-bytes")
    tools = make_tools(make_runner(tmp_path))
    with pytest.raises(TerraformError, match="does not match a plan produced"):
        tools.tf_apply()


def test_tf_plan_then_apply_succeeds_and_removes_the_plan_file(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    tools = make_tools(runner)

    plan_json = json.dumps(
        {"resource_changes": [{"address": "azurerm_resource_group.demo", "change": {"actions": ["create"]}}]}
    )

    def fake_run(subcommand, *args):
        if subcommand == "plan":
            (tmp_path / "plan.tfplan").write_bytes(b"fresh-plan-bytes")
            return _ok("terraform plan")
        if subcommand == "show":
            return _ok("terraform show", plan_json)
        if subcommand == "apply":
            return _ok("terraform apply")
        raise AssertionError(f"unexpected subcommand {subcommand}")

    with patch.object(runner, "run", side_effect=fake_run):
        tools.tf_plan()
        tools.tf_apply()

    assert not (tmp_path / "plan.tfplan").exists()
    assert runner.flow_state.applied_this_session is True


def test_tf_apply_refuses_after_plan_file_changes_post_plan(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    tools = make_tools(runner)

    def fake_plan_run(subcommand, *args):
        (tmp_path / "plan.tfplan").write_bytes(b"fresh-plan-bytes")
        return _ok("terraform plan")

    with patch.object(runner, "run", side_effect=fake_plan_run):
        tools.tf_plan()

    # The saved plan changes after tf_plan ran (tampering, or a stale file
    # from another session overwriting it) — the fingerprint no longer matches.
    (tmp_path / "plan.tfplan").write_bytes(b"different-bytes")

    with pytest.raises(TerraformError, match="does not match a plan produced"):
        tools.tf_apply()


def test_tf_init_and_tf_plan_are_blocked_by_the_hcl_guard(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'provisioner "local-exec" {\n  command = "echo hi"\n}\n', encoding="utf-8"
    )
    runner = make_runner(tmp_path)
    tools = make_tools(runner)

    with patch.object(runner, "run") as run_mock:
        with pytest.raises(TerraformError):
            tools.tf_init()
        with pytest.raises(TerraformError):
            tools.tf_plan()
        run_mock.assert_not_called()


def test_tf_apply_is_blocked_by_the_hcl_guard_even_with_a_valid_fresh_plan(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    tools = make_tools(runner)

    with patch.object(runner, "run", side_effect=lambda *a: _write_plan_and_ok(tmp_path)):
        tools.tf_plan()

    # HCL is edited (e.g. by a later file-access write) after tf_plan ran but
    # before apply — the guard must still catch it at apply time.
    (tmp_path / "main.tf").write_text('data "external" "x" {\n  program = ["sh"]\n}\n', encoding="utf-8")

    with pytest.raises(TerraformError):
        tools.tf_apply()


def _write_plan_and_ok(tmp_path: Path) -> TfResult:
    (tmp_path / "plan.tfplan").write_bytes(b"fresh-plan-bytes")
    return _ok("terraform plan")


def test_build_terraform_tools_gives_each_agent_an_isolated_runner(tmp_path: Path) -> None:
    """Regression guard for the old module-level `_runner` singleton: two
    independent builds must not share plan-fingerprint state."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    runner_a = make_runner(tmp_path / "a")
    runner_b = make_runner(tmp_path / "b")

    tools_a = make_tools(runner_a)
    tools_b = make_tools(runner_b)
    assert tools_a is not tools_b

    # A plan produced under runner_a must not satisfy runner_b's apply.
    (runner_a.workspace / "plan.tfplan").write_bytes(b"a-plan")
    with pytest.raises(TerraformError, match="No saved plan found"):
        tools_b.tf_apply()


# ---- Flow gating ----


def test_mutating_tools_refuse_until_a_flow_is_chosen(tmp_path: Path) -> None:
    tools = make_tools(make_runner(tmp_path, flow=None))
    for tool_fn in (tools.tf_apply, tools.tf_plan_destroy, tools.tf_destroy_sandbox):
        with pytest.raises(TerraformError, match="No session flow chosen"):
            tool_fn()


def test_tf_apply_is_disabled_in_the_brownfield_flow(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, flow=BROWNFIELD)
    tools = make_tools(runner)
    with patch.object(runner, "run") as run_mock:
        with pytest.raises(TerraformError, match="disabled in the brownfield flow"):
            tools.tf_apply()
        run_mock.assert_not_called()


def test_teardown_tools_are_disabled_in_the_brownfield_flow(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, flow=BROWNFIELD)
    tools = make_tools(runner)
    for tool_fn in (tools.tf_plan_destroy, tools.tf_destroy_sandbox):
        with pytest.raises(TerraformError, match="only available in the greenfield flow"):
            tool_fn()


def test_tf_plan_destroy_requires_a_successful_apply_first(tmp_path: Path) -> None:
    tools = make_tools(make_runner(tmp_path, flow=GREENFIELD))
    with pytest.raises(TerraformError, match="Nothing to tear down"):
        tools.tf_plan_destroy()


def test_tf_destroy_sandbox_without_a_destroy_plan_is_refused(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, flow=GREENFIELD)
    tools = make_tools(runner)
    with pytest.raises(TerraformError, match="No saved destroy plan"):
        tools.tf_destroy_sandbox()


def test_greenfield_teardown_happy_path_resets_session_state(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, flow=GREENFIELD)
    runner.flow_state.applied_this_session = True
    tools = make_tools(runner)

    destroy_json = json.dumps(
        {"resource_changes": [{"address": "azurerm_resource_group.demo", "change": {"actions": ["delete"]}}]}
    )

    def fake_destroy_plan():
        (tmp_path / "destroy.tfplan").write_bytes(b"destroy-plan-bytes")
        return _ok("terraform plan -destroy")

    def fake_run(subcommand, *args):
        if subcommand == "show":
            return _ok("terraform show", destroy_json)
        if subcommand == "apply":
            assert "destroy.tfplan" in args
            return _ok("terraform apply destroy.tfplan")
        raise AssertionError(f"unexpected subcommand {subcommand}")

    with patch.object(runner, "run_destroy_plan", side_effect=fake_destroy_plan):
        tools.tf_plan_destroy()
    with patch.object(runner, "run", side_effect=fake_run):
        tools.tf_destroy_sandbox()

    assert not (tmp_path / "destroy.tfplan").exists()
    assert runner.flow_state.applied_this_session is False


def test_tf_destroy_sandbox_refuses_a_stale_destroy_plan(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, flow=GREENFIELD)
    runner.flow_state.applied_this_session = True
    tools = make_tools(runner)

    def fake_destroy_plan():
        (tmp_path / "destroy.tfplan").write_bytes(b"destroy-plan-bytes")
        return _ok("terraform plan -destroy")

    with patch.object(runner, "run_destroy_plan", side_effect=fake_destroy_plan):
        tools.tf_plan_destroy()

    (tmp_path / "destroy.tfplan").write_bytes(b"tampered-bytes")
    with pytest.raises(TerraformError, match="does not match a plan produced"):
        tools.tf_destroy_sandbox()


def test_tf_destroy_sandbox_refuses_a_plan_with_non_delete_actions(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, flow=GREENFIELD)
    runner.flow_state.applied_this_session = True
    tools = make_tools(runner)

    sneaky_json = json.dumps(
        {"resource_changes": [{"address": "azurerm_thing.new", "change": {"actions": ["create"]}}]}
    )

    def fake_destroy_plan():
        (tmp_path / "destroy.tfplan").write_bytes(b"destroy-plan-bytes")
        return _ok("terraform plan -destroy")

    def fake_run(subcommand, *args):
        if subcommand == "show":
            return _ok("terraform show", sneaky_json)
        raise AssertionError("apply must not be reached")

    with patch.object(runner, "run_destroy_plan", side_effect=fake_destroy_plan):
        tools.tf_plan_destroy()
    with patch.object(runner, "run", side_effect=fake_run):
        with pytest.raises(TerraformError, match="non-delete"):
            tools.tf_destroy_sandbox()


def test_state_read_tools_pass_through_the_read_only_runner_path(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, flow=BROWNFIELD)
    tools = make_tools(runner)
    with patch.object(runner, "run_state_read", return_value=_ok("terraform state list", "a.b")) as srm:
        tools.tf_state_list()
        tools.tf_state_show("azurerm_resource_group.demo_rg")
    assert srm.call_args_list[0].args == ("list",)
    assert srm.call_args_list[1].args == ("show", "azurerm_resource_group.demo_rg")
