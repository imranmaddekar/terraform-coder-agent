# Org Terraform Conventions

The agent loads this as durable memory and should follow it. Edit to taste.

## Naming
- Resource name prefix: `demo-`
- Pattern: `<prefix>-<workload>-<env>-<region-short>` (e.g. `demo-web-dev-eus`)
- Region short codes: eastus=eus, westeurope=weu, swedencentral=sdc

## Required tags (every resource that supports tags)
- `environment` (dev | test | prod)
- `owner`
- `managed-by = "terraform-coder-agent"`
- `cost-center`

## Provider / region
- Default region: `swedencentral` (change this convention to suit your sandbox)
- Pin the azurerm provider to a `~>` major version (currently `~> 4.0`); do not
  float wide, and do not pin an old major (`~> 3.x` is end-of-support).
- Set `required_version` on the `terraform` block (currently `>= 1.7`) so the
  CLI version is reproducible alongside the provider version.
- Every variable defined in `variables.tf` must be referenced somewhere in the
  configuration; do not hardcode a value that duplicates an unused variable.

## Sandbox teardown scope (greenfield flow)
- Every resource the agent creates must carry `managed-by = "terraform-coder-agent"`
  (already required above) plus `tfagent-session-scope = "sandbox"` so what the
  teardown removes is provably only what this agent created.
- Sandbox validation resources are disposable: never store data in them that
  must outlive the session.

## Safety
- Local state only for this project; do not add a remote backend without asking.
- No public network exposure by default; ask before opening inbound ports.
- The sandbox subscription is for validation only; the pipeline repo
  (export_to_repo) is the only path to real environments.
