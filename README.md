# Synthetic Billing Fixtures — Normalization Test Harness

A runnable test fixture that proves the canonical schema (from
`ai-cost-allocation-workbook.xlsx`) is complete against **real billing export
shapes** before you point your ingestion layer at live data.

All data is fabricated. Dollar figures are directional (mid-2026) and exist only
to exercise the mapping — treat the *structure* as the durable part.

## What's here

```
raw/
  focus_aws_export.csv       FOCUS-conformant cloud export (real FOCUS columns)
  openai_usage_export.csv    OpenAI usage dump (per-operation token rows)
  anthropic_usage_export.csv Anthropic usage dump (token + agent-runtime rows)
  coreweave_invoice.csv      Neocloud invoice (per-GPU-hour, $0 egress)
  pinecone_invoice.csv       Vector-DB invoice (RU/WU/storage/capacity)
  saas_seats_invoice.csv     Per-seat SaaS (one governed, one shadow-AI)
normalize.py                 Reference normalizer + coverage assertion
normalized_output.csv        Golden output (29 lines on the canonical schema)
```

Six **different native schemas** — different column names for the same concepts —
so the normalizer has to do real work, not a trivial rename.

## Run it

```bash
cd billing-fixtures
python normalize.py            # writes normalized_output.csv + prints coverage
python normalize.py --check    # same, but exits non-zero if anything is UNMAPPED
```

Expected: `PASS: full coverage` and exit 0.

## Why this is a test, not just sample data

`normalize.py` maps every raw line onto the canonical schema and marks any field
it cannot resolve as `UNMAPPED`. The `--check` flag fails the run if a single
`UNMAPPED` survives. So:

- Add a new provider/service to the workbook's `Provider_Mapping` tab → add the
  matching rule to the relevant adapter here → the fixture stays green.
- A real export arrives with a line shape nobody mapped → the run goes **red**,
  pointing at the exact source file, service, and field. That's your regression
  signal that the schema (or an adapter) needs extending.

## What each fixture deliberately exercises

| Fixture | Stresses |
|---|---|
| FOCUS AWS | direct FOCUS-column mapping; sub-classifying *within* one ServiceName (EC2 → compute vs networking); `CommitmentDiscountStatus=Unused` → `WasteFlag=unused-commitment`; Bedrock → `marketplace` channel + commitment-eligible |
| OpenAI | per-operation → CostDomain (chat/embeddings/web_search); `service_tier` → PricingModel (batch); `ft:` prefix → `fine-tuned-hosted` channel; tool call as `per-request` not `per-token` |
| Anthropic | token rows vs a non-token `agent_runtime` row → `orchestration-agents`; batch tier → `batch-inference` lifecycle |
| CoreWeave | per-GPU-hour shape; reserved vs on-demand → commitment; the `$0.00` egress line (no-egress neocloud) |
| Pinecone | retrieval billing units (RU/WU) + storage + the unpublished `Capacity Fee`; monthly-minimum true-up → `serving-idle` |
| SaaS seats | per-seat licensing; `expense_channel=personal-card-reimbursement` → `GovernanceStatus=shadow-AI` |

## Coverage produced (current fixtures)

- **CostDomain:** inference, training, compute-infra, retrieval-RAG, storage, networking, licensing-subscription, orchestration-agents
- **DeploymentModel:** hyperscaler-platform, self-hosted-cloud-GPU, managed-API, neocloud, SaaS-embedded
- **Flags fired:** 1 shadow-AI, 1 unused-commitment

## Adapting to your real data

The adapters in `normalize.py` are intentionally thin and mirror the workbook's
`Provider_Mapping`. To wire up live data: point `RAW_DIR` at your real exports,
adjust column names per provider in the relevant `adapt_*` function, and keep the
`--check` gate in CI so coverage never silently regresses.
