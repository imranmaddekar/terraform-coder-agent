import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tfagent.runner import TerraformError, TerraformRunner, TfResult
from tfagent.tools.terraform import build_terraform_tools


def make_runner(tmp_path: Path) -> TerraformRunner:
    with patch("tfagent.runner.shutil.which", return_value="/usr/bin/terraform"):
        return TerraformRunner(tmp_path)


def _ok(cmd: str, out: str = "") -> TfResult:
    return TfResult(cmd, 0, out, "")


def test_tf_apply_without_any_plan_is_refused(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    _tf_fmt, _tf_validate, _tf_init, _tf_plan, tf_apply = build_terraform_tools(runner)
    with pytest.raises(TerraformError, match="No saved plan found"):
        tf_apply()


def test_tf_apply_refuses_a_plan_file_not_produced_by_tf_plan_this_session(tmp_path: Path) -> None:
    # Simulates a plan.tfplan left over from a previous run/session, or one
    # the model never actually (re-)generated in this run.
    (tmp_path / "plan.tfplan").write_bytes(b"stale-plan-bytes")
    runner = make_runner(tmp_path)
    _tf_fmt, _tf_validate, _tf_init, _tf_plan, tf_apply = build_terraform_tools(runner)
    with pytest.raises(TerraformError, match="does not match a plan produced"):
        tf_apply()


def test_tf_plan_then_apply_succeeds_and_removes_the_plan_file(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    _tf_fmt, _tf_validate, _tf_init, tf_plan, tf_apply = build_terraform_tools(runner)

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
        tf_plan()
        tf_apply()

    assert not (tmp_path / "plan.tfplan").exists()


def test_tf_apply_refuses_after_plan_file_changes_post_plan(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    _tf_fmt, _tf_validate, _tf_init, tf_plan, tf_apply = build_terraform_tools(runner)

    def fake_plan_run(subcommand, *args):
        (tmp_path / "plan.tfplan").write_bytes(b"fresh-plan-bytes")
        return _ok("terraform plan")

    with patch.object(runner, "run", side_effect=fake_plan_run):
        tf_plan()

    # The saved plan changes after tf_plan ran (tampering, or a stale file
    # from another session overwriting it) — the fingerprint no longer matches.
    (tmp_path / "plan.tfplan").write_bytes(b"different-bytes")

    with pytest.raises(TerraformError, match="does not match a plan produced"):
        tf_apply()


def test_tf_init_and_tf_plan_are_blocked_by_the_hcl_guard(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'provisioner "local-exec" {\n  command = "echo hi"\n}\n', encoding="utf-8"
    )
    runner = make_runner(tmp_path)
    _tf_fmt, _tf_validate, tf_init, tf_plan, _tf_apply = build_terraform_tools(runner)

    with patch.object(runner, "run") as run_mock:
        with pytest.raises(TerraformError):
            tf_init()
        with pytest.raises(TerraformError):
            tf_plan()
        run_mock.assert_not_called()


def test_tf_apply_is_blocked_by_the_hcl_guard_even_with_a_valid_fresh_plan(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)
    _tf_fmt, _tf_validate, _tf_init, tf_plan, tf_apply = build_terraform_tools(runner)

    with patch.object(runner, "run", side_effect=lambda *a: _write_plan_and_ok(tmp_path)):
        tf_plan()

    # HCL is edited (e.g. by a later file-access write) after tf_plan ran but
    # before apply — the guard must still catch it at apply time.
    (tmp_path / "main.tf").write_text('data "external" "x" {\n  program = ["sh"]\n}\n', encoding="utf-8")

    with pytest.raises(TerraformError):
        tf_apply()


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

    _fa, _va, _ia, _pa, apply_a = build_terraform_tools(runner_a)
    _fb, _vb, _ib, _pb, apply_b = build_terraform_tools(runner_b)

    # A plan produced under runner_a must not satisfy runner_b's apply.
    (runner_a.workspace / "plan.tfplan").write_bytes(b"a-plan")
    with pytest.raises(TerraformError, match="No saved plan found"):
        apply_b()
