# Terraform Coder Agent

A Claude-Code-style terminal application for authoring and safely applying
Terraform to Azure. It uses the Microsoft Agent Framework (MAF) harness,
GitHub Models, and Microsoft's official Textual harness console.

## What works

- Plan and execute modes with a visible todo list
- Streaming responses and tool-call output in a Textual TUI
- GitHub Models through MAF's `OpenAIChatCompletionClient`
- Scoped workspace file access and session file memory
- `terraform fmt`, `init`, `validate`, and saved `plan`
- Human approval before every `terraform apply`
- Automatic todo-driven execution with a bounded iteration count
- Deterministic rejection of destructive commands, bypass flags, HCL-level
  equivalents (provisioners, `data "external"`, `import`/`removed` blocks,
  remote backends), and any saved plan containing deletion, replacement, or
  state-removal actions
- Approval card that shows the actual plan diff, and a `/plan` command to
  check it independent of the model
- Headless TUI, harness construction, plan parsing, and safety tests

## Versions

Dependencies are resolved to their latest compatible releases by `uv` and
recorded in `uv.lock`. At the time of the latest verification:

- Python 3.14.6
- `agent-framework-core` 1.11.0
- `agent-framework-openai` 1.10.1
- Textual 8.2.8
- Rich 15.0.0
- OpenAI Python 2.45.0 (transitive)

Run `uv lock --upgrade && uv sync --all-groups` to deliberately upgrade all
packages, then run the tests.

## Prerequisites

1. A GitHub account with access to GitHub Models.
2. A fine-grained GitHub PAT with `models: read` permission.
3. Terraform installed and available on `PATH`.
4. An Azure sandbox subscription.
5. An Azure service principal scoped with least privilege to that sandbox.

## Setup

```bash
cd terraform-coder-agent
cp .env.example .env
# Edit .env with your GitHub and Azure values.
uv sync --all-groups
uv run tfagent --check
uv run tfagent
```

The default model is `openai/gpt-4.1` at
`https://models.github.ai/inference`. Change `GITHUB_MODEL` in `.env` to use a
different tool-capable model available to your account.

## Expected workflow

1. Describe the desired infrastructure in plan mode.
2. Answer questions about region, SKU, naming, tags, and networking.
3. Review the generated todos and use `/mode execute` when ready.
4. The agent writes HCL and runs `fmt`, `init`, `validate`, and `plan`.
5. It summarizes the saved plan.
6. The console displays an approval prompt for `tf_apply`, showing the saved
   plan's diff directly (computed from `plan.tfplan`, not the model's
   paraphrase) — no "always approve" option is offered for this tool.
7. Approval applies the exact saved plan. Rejection returns control to you;
   the agent will ask what to change rather than re-requesting approval.

Useful console commands include `/mode`, `/todos`, `/plan` (show the saved
plan's diff on demand, without asking the model), `/session-export`,
`/session-import`, and `/exit`.

## Safety boundaries

- The agent does not receive a generic shell tool.
- Terraform is invoked with argument arrays, never `shell=True`.
- `destroy`, `state`, `import`, `taint`, `force-unlock`, `-target`, `-replace`,
  `-destroy`, and `-auto-approve` are blocked in code.
- A deterministic HCL guard runs before `init`/`plan`/`apply` and rejects
  `provisioner "local-exec"` / `"remote-exec"`, `data "external"`, config-driven
  `import {}` / `removed {}` blocks, and any non-`local` `backend` block —
  the HCL-level equivalents of the CLI operations above.
- Before apply, `terraform show -json plan.tfplan` is checked and any plan
  with a delete, replace, or forget (state-removal) action is rejected.
- `tf_apply` only applies the exact `plan.tfplan` produced by `tf_plan` in the
  current session (checked by content hash) — a stale or leftover plan file
  on disk is refused, and the file is deleted after a successful apply.
- The `tf_apply` approval card shows the plan diff itself, computed straight
  from disk; approving is never based solely on the model's own summary.
- `tf_apply` is registered with MAF's `always_require` approval mode, with no
  "always approve" bypass offered in the console.
- File access is rooted at `workspace/`.
- State is local and excluded from version control.
- The autonomous execute loop is capped by `TFAGENT_MAX_ITERATIONS`.

This is a local demonstration, not a production control plane. Use a dedicated
sandbox subscription. Remote state, locking, multi-user authorization,
container isolation, policy-as-code, cost controls, and audit export are future
hardening work.

## Tests

```bash
uv run pytest -q
```

The test suite does not call GitHub Models, Terraform, or Azure. A real-provider
smoke test requires your token; a real Terraform test requires Terraform and
Azure credentials. No test automatically runs `apply`.

## Microsoft console provenance

`src/tfagent/console/` is Microsoft's official Python harness console vendored
from `microsoft/agent-framework` commit
`68136ee081dbbee6983e6bb92a834f9ad30d20dc`. See `THIRD_PARTY_NOTICES.md`.
