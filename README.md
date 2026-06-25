# Example: AWS + Frontier APIs + Colocation

A worked normalization example for a customer whose AI stack spans three worlds at
once. It proves the canonical schema absorbs not just cloud and managed APIs, but
**owned colocation infrastructure** — the case that breaks most cloud-only cost tools.

## The customer's stack

| Layer | Sources here | What it exercises |
|---|---|---|
| **AWS (cloud)** | `aws_focus.csv` | Bedrock, SageMaker endpoint, EC2 reserved GPU, S3, egress |
| **Frontier direct APIs** | `frontier_openai.csv`, `frontier_anthropic.csv` | per-token inference, batch tier, cache reads, agent runtime |
| **Colocation** | `colo_invoice.csv`, `colo_depreciation.csv` | rack/power/cross-connect/transit/remote-hands + owned-hardware depreciation |

## Run it

```bash
cd example-aws-frontier-colo
python normalize_example.py --check     # maps all 21 lines; exits non-zero on any UNMAPPED
python report.py normalized_example_output.csv   # same reporting layer as the main fixture
```

## Why the colo half matters

Cloud bills never carry capex or facilities lines, so a cloud-only schema silently
drops a huge share of an owned-infrastructure customer's true AI cost. Here that gap
is closed by two colo-specific adapters:

- **`colo_invoice.csv`** → recurring opex: cabinet space and power map to
  `facilities-hardware`; cross-connect and IP transit to `networking`; remote hands
  to `professional-services`. Contract commitments set `FixedVsVariable=fixed` and a
  `enterprise-agreement` commitment type; metered power overage stays `variable`.
- **`colo_depreciation.csv`** → the owned-hardware depreciation schedule. Monthly
  depreciation is the line item; GPU servers map to `compute-infra` (with
  `ModelChannel=self-hosted-weights`), switches to `networking`, storage arrays to
  `storage` — all tagged **`CapexVsOpex=capex`**. This is how owned silicon shows up
  in a cost model that's otherwise all opex.

The result: this customer's biggest cost domain is `compute-infra` (~57%), driven
almost entirely by GPU-server depreciation in the colo — a number that would be
**completely invisible** on the AWS + API bills alone.

## What the run produces

- 21 normalized lines, full coverage (no UNMAPPED)
- CostDomains populated: inference, compute-infra, storage, networking,
  orchestration-agents, **facilities-hardware**, professional-services
- DeploymentModels: hyperscaler-platform, self-hosted-cloud-GPU, managed-API,
  **colocation**
- CapexVsOpex split: opex + **capex** (the 4 depreciation lines)
- Rough mix: total ~$51.3K — AWS ~$16.3K, frontier APIs ~$0.26K, **colo ~$34.6K**

That last line is the whole point: for this customer the colo dwarfs the cloud and
API spend, and only a schema that models facilities + depreciation will show it.

## Extending the schema

This example adds two fields the base fixture didn't use — `CapexVsOpex` and
`FixedVsVariable` — both already defined in the workbook's `Schema_Fields` tab. The
shared `report.py` is schema-tolerant: it runs against either output, treating
absent optional columns gracefully. Add a provider, add its adapter, keep `--check`
in CI, and coverage never silently regresses.
