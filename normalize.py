#!/usr/bin/env python3
"""
Reference normalizer for the AI cost ingestion-and-normalization layer.

Reads six raw billing fixtures, each in a DIFFERENT native export shape, and maps
every line onto the canonical schema defined in ai-cost-allocation-workbook.xlsx
(Schema_Fields tab). Emits normalized_output.csv and asserts FULL COVERAGE:
no field is left UNMAPPED. If a future raw line touches a service/shape the
mapping does not cover, the assertion fails - that is the regression signal.

Usage:
    python normalize.py            # normalizes raw/, writes normalized_output.csv
    python normalize.py --check    # also fails (non-zero exit) on any UNMAPPED

The adapters intentionally mirror the workbook's Provider_Mapping tab. When you
add a provider/service there, add the corresponding rule here.
"""
import csv, json, os, sys

RAW_DIR = os.path.join(os.path.dirname(__file__), "raw")
OUT = os.path.join(os.path.dirname(__file__), "normalized_output.csv")
UNMAPPED = "UNMAPPED"

CANONICAL = [
    "source_file","ProviderName","ServiceName","CostDomain","DeploymentModel",
    "ModelChannel","ModelProvider","ModelTier","ModelName","WorkloadLifecycle",
    "PricingUnit","PricingModel","CommitmentDiscountType","CommitmentDiscountStatus",
    "CommitmentEligible","ChargeCategory","Environment","BusinessUnit",
    "GovernanceStatus","WasteFlag","Quantity","BilledCost",
]

def rec(**kw):
    r = {c: kw.get(c, "") for c in CANONICAL}
    for c in CANONICAL:
        if r[c] == "":
            r[c] = "none" if c in ("CommitmentDiscountType","WasteFlag") else r[c]
    return r

# ---- shared lookups (mirror workbook Provider_Mapping) --------------------------

# FOCUS ServiceName -> (CostDomain, DeploymentModel, default WorkloadLifecycle)
AWS_SERVICE = {
    "Amazon Bedrock": ("inference", "hyperscaler-platform", "real-time-inference"),
    "Amazon SageMaker": ("compute-infra", "self-hosted-cloud-GPU", "training"),
    "Amazon Elastic Compute Cloud": ("compute-infra", "self-hosted-cloud-GPU", "real-time-inference"),
    "Amazon OpenSearch Service": ("retrieval-RAG", "hyperscaler-platform", "real-time-inference"),
    "Amazon Simple Storage Service": ("storage", "hyperscaler-platform", "data-prep"),
    "Amazon Q": ("licensing-subscription", "SaaS-embedded", "real-time-inference"),
}

def model_tier(name):
    n = (name or "").lower()
    if any(k in n for k in ("opus","gpt-5.4-pro","gpt-5.5","-pro","gemini-3-pro","gemini-3.1-pro")):
        return "frontier"
    if any(k in n for k in ("sonnet","mini","flash")):
        return "mid"
    if any(k in n for k in ("haiku","nano","flash-lite")):
        return "small-efficient"
    if "embedding" in n:
        return "embedding"
    if name:
        return "mid"
    return ""

def model_provider(name):
    n = (name or "").lower()
    if "claude" in n: return "Anthropic"
    if "gpt" in n or n.startswith("ft:gpt"): return "OpenAI"
    if "gemini" in n: return "Google"
    if "llama" in n: return "Meta"
    return ""

# ---- adapters ------------------------------------------------------------------

def adapt_focus_aws(row):
    svc = row["ServiceName"]
    domain, deploy, life = AWS_SERVICE.get(svc, (UNMAPPED, UNMAPPED, UNMAPPED))
    desc = row.get("ChargeDescription","").lower()
    sku = row.get("SkuId","").lower()
    # sub-classify within a service using description/sku hints
    if svc == "Amazon Elastic Compute Cloud" and ("datatransfer" in desc or row.get("ServiceCategory")=="Networking"):
        domain, deploy, life = "networking", "hyperscaler-platform", "serving-idle"
    if svc == "Amazon Bedrock" and "provisioned" in desc:
        life = "real-time-inference"
    if svc == "Amazon SageMaker" and "training" in desc:
        domain, life = "training", "training"
    if svc == "Amazon SageMaker" and "unused" in desc:
        life = "serving-idle"
    tags = json.loads(row.get("Tags") or "{}")
    status = row.get("CommitmentDiscountStatus","") or ""
    waste = "unused-commitment" if status == "Unused" else "none"
    ch = "marketplace" if svc == "Amazon Bedrock" else "n/a"
    mp = "Anthropic" if row.get("PublisherName")=="Anthropic" else ""
    commit = row.get("CommitmentDiscountType","") or "none"
    pmodel = "committed-savings-plan" if commit not in ("","none") else "on-demand"
    return rec(
        source_file="focus_aws_export.csv", ProviderName="AWS", ServiceName=svc,
        CostDomain=domain, DeploymentModel=deploy, ModelChannel=ch, ModelProvider=mp,
        ModelTier="frontier" if svc=="Amazon Bedrock" and "opus" in desc else ("mid" if svc=="Amazon Bedrock" else ""),
        ModelName="claude-opus-4-8" if "opus 4.8" in desc else ("claude-sonnet-4-6" if "sonnet 4.6" in desc else ""),
        WorkloadLifecycle=life, PricingUnit=row.get("PricingUnit",""), PricingModel=pmodel,
        CommitmentDiscountType=commit, CommitmentDiscountStatus=status,
        CommitmentEligible="TRUE" if commit not in ("","none") else "FALSE",
        ChargeCategory=row.get("ChargeCategory",""), Environment=tags.get("env",""),
        BusinessUnit=tags.get("bu",""), GovernanceStatus="governed", WasteFlag=waste,
        Quantity=row.get("PricingQuantity",""), BilledCost=row.get("BilledCost",""),
    )

def adapt_openai(row):
    op = row["operation"]
    op_map = {
        "chat.completions": ("inference","real-time-inference"),
        "embeddings": ("inference","data-prep"),
        "web_search": ("retrieval-RAG","real-time-inference"),
        "file_search": ("retrieval-RAG","real-time-inference"),
        "code_interpreter": ("orchestration-agents","real-time-inference"),
    }
    domain, life = op_map.get(op, (UNMAPPED, UNMAPPED))
    tier_map = {"standard":"on-demand","batch":"batch","flex":"flex-tier","priority":"priority-tier"}
    pmodel = tier_map.get(row.get("service_tier","standard"), "on-demand")
    if op == "batch" or row.get("service_tier") == "batch":
        life = "batch-inference"
    name = row["model"]
    channel = "fine-tuned-hosted" if name.startswith("ft:") else "direct-lab-API"
    life2 = "real-time-inference" if channel == "fine-tuned-hosted" and op=="chat.completions" else life
    unit = "per-request" if op == "web_search" else "per-token"
    return rec(
        source_file="openai_usage_export.csv", ProviderName="OpenAI", ServiceName=f"OpenAI {op}",
        CostDomain=domain, DeploymentModel="managed-API", ModelChannel=channel,
        ModelProvider="OpenAI", ModelTier=model_tier(name), ModelName=name,
        WorkloadLifecycle=life2, PricingUnit=unit, PricingModel=pmodel,
        CommitmentDiscountType="none", CommitmentEligible="FALSE",
        ChargeCategory="Usage", Environment="prod" if row["project"].startswith("prod") else "non-prod",
        BusinessUnit=row["project"], GovernanceStatus="governed", WasteFlag="none",
        Quantity=row.get("input_tokens","") or row.get("num_requests",""),
        BilledCost=row["amount_usd"],
    )

def adapt_anthropic(row):
    ut = row["usage_type"]
    if ut == "tokens":
        domain, life, unit = "inference", "real-time-inference", "per-token"
    elif ut == "agent_runtime":
        domain, life, unit = "orchestration-agents", "real-time-inference", "per-instance-hour"
    else:
        domain, life, unit = UNMAPPED, UNMAPPED, UNMAPPED
    pmodel = "batch" if row.get("service_tier") == "batch" else "on-demand"
    if pmodel == "batch":
        life = "batch-inference"
    name = row.get("model","")
    return rec(
        source_file="anthropic_usage_export.csv", ProviderName="Anthropic",
        ServiceName="Claude API" if ut == "tokens" else "Claude Managed Agents",
        CostDomain=domain, DeploymentModel="managed-API", ModelChannel="direct-lab-API",
        ModelProvider="Anthropic", ModelTier=model_tier(name), ModelName=name,
        WorkloadLifecycle=life, PricingUnit=unit, PricingModel=pmodel,
        CommitmentDiscountType="none", CommitmentEligible="FALSE", ChargeCategory="Usage",
        Environment="prod", BusinessUnit=row.get("workspace",""), GovernanceStatus="governed",
        WasteFlag="none",
        Quantity=row.get("input_tokens","") or row.get("quantity_hours",""),
        BilledCost=row["amount_usd"],
    )

def adapt_coreweave(row):
    rt = row["resource_type"]
    rt_map = {
        "gpu_compute": ("compute-infra","self-hosted-weights","per-GPU-hour"),
        "distributed_file_storage": ("storage","n/a","per-GB-month"),
        "object_storage": ("storage","n/a","per-GB-month"),
        "network_egress": ("networking","n/a","per-GB-transfer"),
    }
    domain, channel, unit = rt_map.get(rt, (UNMAPPED, UNMAPPED, UNMAPPED))
    res = row.get("reservation_type","")
    pmodel = {"on_demand":"on-demand","reserved_1yr":"committed-savings-plan","spot":"spot"}.get(res,"on-demand")
    life = "training" if (rt == "gpu_compute" and int(row.get("gpu_count") or 0) >= 16) else ("real-time-inference" if rt=="gpu_compute" else "serving-idle")
    commit = "reserved-instance" if res.startswith("reserved") else "none"
    return rec(
        source_file="coreweave_invoice.csv", ProviderName="CoreWeave", ServiceName=rt,
        CostDomain=domain, DeploymentModel="neocloud", ModelChannel=channel,
        ModelTier="", ModelName="", WorkloadLifecycle=life, PricingUnit=unit,
        PricingModel=pmodel, CommitmentDiscountType=commit,
        CommitmentDiscountStatus="Used" if commit != "none" else "",
        CommitmentEligible="TRUE" if commit != "none" else "FALSE",
        ChargeCategory="Usage", Environment="prod" if rt!="gpu_compute" else "non-prod",
        BusinessUnit="ml-platform", GovernanceStatus="governed", WasteFlag="none",
        Quantity=row.get("hours",""), BilledCost=row["amount_usd"],
    )

def adapt_pinecone(row):
    li = row["line_item"]
    li_map = {
        "Read Units": ("retrieval-RAG","per-query / per-RU / per-WU / per-AU","real-time-inference","on-demand"),
        "Write Units": ("retrieval-RAG","per-query / per-RU / per-WU / per-AU","data-prep","on-demand"),
        "Storage": ("storage","per-GB-month","serving-idle","on-demand"),
        "Capacity Fee": ("retrieval-RAG","per-request","real-time-inference","on-demand"),
        "Monthly Minimum True-up": ("retrieval-RAG","flat","serving-idle","subscription"),
    }
    domain, unit, life, pmodel = li_map.get(li, (UNMAPPED, UNMAPPED, UNMAPPED, UNMAPPED))
    return rec(
        source_file="pinecone_invoice.csv", ProviderName="Pinecone", ServiceName=f"Pinecone {li}",
        CostDomain=domain, DeploymentModel="SaaS-embedded", ModelChannel="n/a",
        ModelTier="", ModelName="", WorkloadLifecycle=life, PricingUnit=unit, PricingModel=pmodel,
        CommitmentDiscountType="none", CommitmentEligible="FALSE", ChargeCategory="Usage",
        Environment="prod" if row["project"].endswith("prod") else "non-prod",
        BusinessUnit=row["project"], GovernanceStatus="governed", WasteFlag="none",
        Quantity=row.get("quantity",""), BilledCost=row["amount_usd"],
    )

def adapt_saas(row):
    shadow = row.get("expense_channel") == "personal-card-reimbursement"
    return rec(
        source_file="saas_seats_invoice.csv", ProviderName=row["vendor"], ServiceName=row["product"],
        CostDomain="licensing-subscription", DeploymentModel="SaaS-embedded", ModelChannel="n/a",
        ModelTier="", ModelName="", WorkloadLifecycle="real-time-inference", PricingUnit="per-seat",
        PricingModel="subscription", CommitmentDiscountType="none", CommitmentEligible="FALSE",
        ChargeCategory="Purchase", Environment="prod", BusinessUnit="unknown" if shadow else "engineering",
        GovernanceStatus="shadow-AI" if shadow else "governed", WasteFlag="none",
        Quantity=row.get("seats",""), BilledCost=row["amount_usd"],
    )

ADAPTERS = {
    "focus_aws_export.csv": adapt_focus_aws,
    "openai_usage_export.csv": adapt_openai,
    "anthropic_usage_export.csv": adapt_anthropic,
    "coreweave_invoice.csv": adapt_coreweave,
    "pinecone_invoice.csv": adapt_pinecone,
    "saas_seats_invoice.csv": adapt_saas,
}

def run(check=False):
    out_rows = []
    for fname, adapter in ADAPTERS.items():
        with open(os.path.join(RAW_DIR, fname)) as f:
            for raw in csv.DictReader(f):
                out_rows.append(adapter(raw))

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CANONICAL)
        w.writeheader()
        w.writerows(out_rows)

    # coverage check
    unmapped = [(r["source_file"], r["ServiceName"], c)
                for r in out_rows for c in CANONICAL if r[c] == UNMAPPED]
    total = len(out_rows)
    print(f"normalized {total} line items across {len(ADAPTERS)} source shapes -> {os.path.basename(OUT)}")
    # quick domain + deployment coverage summary
    from collections import Counter
    dom = Counter(r["CostDomain"] for r in out_rows)
    dep = Counter(r["DeploymentModel"] for r in out_rows)
    print("CostDomain coverage:", dict(dom))
    print("DeploymentModel coverage:", dict(dep))
    shadow = sum(1 for r in out_rows if r["GovernanceStatus"] == "shadow-AI")
    waste = sum(1 for r in out_rows if r["WasteFlag"] != "none")
    print(f"flags: shadow-AI={shadow}, waste-flagged={waste}")
    if unmapped:
        print(f"\nFAIL: {len(unmapped)} UNMAPPED field(s):")
        for u in unmapped:
            print("  ", u)
        if check:
            sys.exit(1)
    else:
        print("\nPASS: full coverage - every line maps cleanly onto the canonical schema.")

if __name__ == "__main__":
    run(check="--check" in sys.argv)
