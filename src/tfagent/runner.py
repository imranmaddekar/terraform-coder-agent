"""Low-level Terraform CLI wrapper.

This is the deterministic guardrail layer. Even if the model is confused or
adversarial, dangerous flags never reach the shell because they are blocked
here in code, not merely discouraged in a system prompt.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .flow import FlowState

# Flags / subcommands we refuse to run no matter who asks.
FORBIDDEN_TOKENS = {
    "-auto-approve",       # apply must always be human-gated
    "-destroy",            # no destroy plans (run_destroy_plan is the one, gated exception)
    "-target",             # surgical targeting is an easy footgun; opt-in later
    "-replace",
}
FORBIDDEN_SUBCOMMANDS = {"destroy", "import", "state", "taint", "untaint", "force-unlock"}

# The saved destroy plan for greenfield sandbox teardown; kept separate from
# plan.tfplan so a build plan can never be confused with a teardown plan.
DESTROY_PLAN_FILENAME = "destroy.tfplan"

# The only `terraform state` verbs that are read-only.
READ_ONLY_STATE_VERBS = {"list", "show"}


class TerraformError(RuntimeError):
    pass


@dataclass
class TfResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def as_feedback(self) -> str:
        """Compact string handed back to the model."""
        head = f"$ {self.command}\n(exit {self.returncode})"
        body = self.stdout.strip()
        err = self.stderr.strip()
        parts = [head]
        if body:
            parts.append("--- stdout ---\n" + body[-6000:])
        if err:
            parts.append("--- stderr ---\n" + err[-6000:])
        return "\n".join(parts)


def _validate_args(subcommand: str, args: list[str]) -> None:
    if subcommand in FORBIDDEN_SUBCOMMANDS:
        raise TerraformError(f"Subcommand '{subcommand}' is not permitted by this agent.")
    for a in args:
        low = a.lower()
        if low in FORBIDDEN_TOKENS or any(low.startswith(token + "=") for token in FORBIDDEN_TOKENS):
            raise TerraformError(f"Flag '{a}' is blocked (destructive / bypasses approval).")


class TerraformRunner:
    def __init__(
        self,
        workspace: Path,
        timeout_seconds: int = 600,
        flow_state: "FlowState | None" = None,
    ) -> None:
        self.workspace = workspace
        self.timeout = timeout_seconds
        self.flow_state = flow_state
        if shutil.which("terraform") is None:
            raise TerraformError("terraform CLI not found on PATH.")

    def run(self, subcommand: str, *args: str) -> TfResult:
        _validate_args(subcommand, list(args))
        return self._execute(["terraform", subcommand, *args])

    def run_destroy_plan(self) -> TfResult:
        """Run ``terraform plan -destroy -out=destroy.tfplan``.

        The ONLY code path allowed to pass ``-destroy``; ``run()`` keeps
        rejecting it unconditionally. Gated on the session flow being
        greenfield so a brownfield session (real deployed infrastructure)
        can never even produce a destroy plan.
        """
        if self.flow_state is None or self.flow_state.flow != "greenfield":
            raise TerraformError(
                "Destroy planning is only permitted in the greenfield flow, "
                "against the agent's own sandbox resources."
            )
        return self._execute(
            ["terraform", "plan", "-destroy", "-no-color", "-input=false", f"-out={DESTROY_PLAN_FILENAME}"]
        )

    def run_state_read(self, verb: str, *args: str) -> TfResult:
        """Run a read-only ``terraform state list|show``.

        ``run()`` keeps blocking the ``state`` subcommand wholesale; this
        method admits only the two read-only verbs, with no flags, so the
        mutating verbs (rm, mv, push, replace-provider, ...) stay unreachable.
        """
        if verb not in READ_ONLY_STATE_VERBS:
            raise TerraformError(
                f"'terraform state {verb}' is not permitted; only read-only "
                f"{'/'.join(sorted(READ_ONLY_STATE_VERBS))} are."
            )
        for a in args:
            if a.startswith("-"):
                raise TerraformError(f"Flag '{a}' is not permitted on read-only state commands.")
        return self._execute(["terraform", "state", verb, *args])

    def _execute(self, cmd: list[str]) -> TfResult:
        printable = " ".join(cmd)
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return TfResult(printable, 124, exc.stdout or "", f"timed out after {self.timeout}s")
        return TfResult(printable, proc.returncode, proc.stdout, proc.stderr)
