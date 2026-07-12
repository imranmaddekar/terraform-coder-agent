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
- Pin the azurerm provider to a `~>` minor version; do not float wide.

## Safety
- Local state only for this project; do not add a remote backend without asking.
- No public network exposure by default; ask before opening inbound ports.
