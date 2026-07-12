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

# Flags / subcommands we refuse to run no matter who asks.
FORBIDDEN_TOKENS = {
    "-auto-approve",       # apply must always be human-gated
    "-destroy",            # no destroy plans
    "-target",             # surgical targeting is an easy footgun; opt-in later
    "-replace",
}
FORBIDDEN_SUBCOMMANDS = {"destroy", "import", "state", "taint", "untaint", "force-unlock"}


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
    def __init__(self, workspace: Path, timeout_seconds: int = 600) -> None:
        self.workspace = workspace
        self.timeout = timeout_seconds
        if shutil.which("terraform") is None:
            raise TerraformError("terraform CLI not found on PATH.")

    def run(self, subcommand: str, *args: str) -> TfResult:
        _validate_args(subcommand, list(args))
        cmd = ["terraform", subcommand, *args]
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
