from pathlib import Path

import pytest

from tfagent.runner import TerraformError
from tfagent.tools.hcl_guard import assert_hcl_is_safe


def test_safe_workspace_passes(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text(
        'resource "azurerm_resource_group" "demo" {\n  name = "demo"\n}\n',
        encoding="utf-8",
    )
    assert_hcl_is_safe(tmp_path)  # should not raise


@pytest.mark.parametrize(
    "hcl",
    [
        'provisioner "local-exec" {\n  command = "echo hi"\n}\n',
        'provisioner "remote-exec" {\n  inline = ["echo hi"]\n}\n',
        'data "external" "x" {\n  program = ["sh", "-c", "echo {}"]\n}\n',
        "import {\n  to = azurerm_resource_group.demo\n  id = \"/subscriptions/x\"\n}\n",
        'removed {\n  from = azurerm_resource_group.demo\n}\n',
        'terraform {\n  backend "azurerm" {}\n}\n',
    ],
)
def test_dangerous_constructs_are_blocked(tmp_path: Path, hcl: str) -> None:
    (tmp_path / "main.tf").write_text(hcl, encoding="utf-8")
    with pytest.raises(TerraformError):
        assert_hcl_is_safe(tmp_path)


def test_local_backend_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text('terraform {\n  backend "local" {}\n}\n', encoding="utf-8")
    assert_hcl_is_safe(tmp_path)  # should not raise


def test_terraform_dir_is_ignored(tmp_path: Path) -> None:
    tf_dir = tmp_path / ".terraform" / "modules" / "some_module"
    tf_dir.mkdir(parents=True)
    (tf_dir / "main.tf").write_text('provisioner "local-exec" {\n  command = "echo hi"\n}\n', encoding="utf-8")
    assert_hcl_is_safe(tmp_path)  # vendored module content is not scanned
