"""Deterministic guard over the HCL the model writes into the workspace.

`runner.py` blocks dangerous Terraform CLI subcommands and flags (destroy,
import, -target, ...), but the model can reach equivalent behavior by writing
HCL through the (auto-approved) file-access tools instead of asking for a
blocked CLI operation:

- ``provisioner "local-exec"`` / ``"remote-exec"`` run arbitrary shell commands
  at apply time.
- ``data "external"`` runs an arbitrary external program at plan/refresh time.
- ``import { ... }`` blocks perform config-driven import at apply time
  (Terraform 1.5+) — the CLI-level "no import" rule does not cover this.
- ``removed { ... }`` blocks drop resources from state ("forget") at apply
  time, sidestepping the "no state manipulation" rule.
- a non-``local`` ``backend`` block switches state out of the local file the
  rest of this project's safety story assumes.

This is a best-effort regex scan over the raw HCL text, not a real HCL
parser — consistent with the token-matching approach already used in
`runner.py`. It cannot be fooled by a determined adversary rewriting the same
construct in a hard-to-match shape, but the model this project targets is not
one, and the deterministic check still beats relying on the system prompt
alone.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..runner import TerraformError

_PATTERNS: dict[str, re.Pattern[str]] = {
    'provisioner "local-exec" (arbitrary shell execution at apply)': re.compile(
        r'\bprovisioner\s+"local-exec"'
    ),
    'provisioner "remote-exec" (arbitrary shell execution at apply)': re.compile(
        r'\bprovisioner\s+"remote-exec"'
    ),
    'data "external" (arbitrary program execution at plan/refresh)': re.compile(
        r'\bdata\s+"external"'
    ),
    "import block (config-driven import bypasses the no-import rule)": re.compile(
        r"(?m)^\s*import\s*{"
    ),
    'removed block (config-driven state removal / "forget")': re.compile(
        r"(?m)^\s*removed\s*{"
    ),
    "non-local backend (remote state was not authorized)": re.compile(
        r'\bbackend\s+"(?!local")'
    ),
}


def assert_hcl_is_safe(workspace: Path) -> None:
    """Raise TerraformError if any .tf file in the workspace contains a
    blocked construct. Call before any operation that executes HCL
    (init/plan/apply)."""
    violations: list[str] = []
    for tf_file in sorted(workspace.rglob("*.tf")):
        if ".terraform" in tf_file.parts:
            continue
        try:
            text = tf_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for description, pattern in _PATTERNS.items():
            if pattern.search(text):
                violations.append(f"{tf_file.relative_to(workspace)}: {description}")

    if violations:
        raise TerraformError(
            "Blocked by HCL safety guard (destructive, arbitrary-execution, or "
            "approval-bypassing construct found before running Terraform):\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\nRemove the construct and ask the human if the task truly needs it."
        )
