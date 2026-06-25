#!/usr/bin/env python3
"""
Example normalization layer for a customer whose AI stack = AWS + frontier APIs + colo.

Demonstrates the canonical schema absorbing three very different worlds:
  - AWS cloud (FOCUS export)
  - Frontier direct model APIs (OpenAI, Anthropic)
  - Colocation: a colo vendor invoice AND an owned-hardware depreciation schedule

The colo adapters are the interesting part - they populate CostDomain=facilities-hardware,
DeploymentModel=colocation, and the CapexVsOpex / FixedVsVariable fields that cloud bills
never carry. Run with --check to fail on any UNMAPPED field.
"""
import csv, json, os, sys
RAW = os.path.join(os.path.dirname(__file__), "raw")
OUT = os.path.join(os.path.dirname(__file__), "normalized_example_output.csv")
UNMAPPED = "UNMAPPED"

CANON = ["source_file","ProviderName","ServiceName","CostDomain","DeploymentModel",
 "ModelChannel","ModelProvider","ModelTier","ModelName","WorkloadLifecycle","PricingUnit",
 "PricingModel","CommitmentDiscountType","CommitmentEligible","CapexVsOpex","FixedVsVariable",
 "ChargeCategory","Environment","BusinessUnit","GovernanceStatus","WasteFlag","Quantity","BilledCost"]

def rec(**kw):
    r = {c: kw.get(c, "") for c in CANON}
    if r["CommitmentDiscountType"] == "": r["CommitmentDiscountType"] = "none"
    if r["WasteFlag"] == "": r["WasteFlag"] = "none"
    if r["ModelChannel"] == "": r["ModelChannel"] = "n/a"
    if r["GovernanceStatus"] == "": r["GovernanceStatus"] = "governed"
    return r

def tier(name):
    n = (name or "").lower()
    if "opus" in n or "-pro" in n or "gpt-5.5" in n: return "frontier"
    if "sonnet" in n or "mini" in n or "flash" in n: return "mid"
    if "haiku" in n or "nano" in n: return "small-efficient"
    if "embedding" in n: return "embedding"
    return "mid" if name else ""

# --- AWS FOCUS ---
AWS_SVC = {
 "Amazon Bedrock": ("inference","hyperscaler-platform","real-time-inference"),
 "Amazon SageMaker": ("inference","hyperscaler-platform","real-time-inference"),
 "Amazon Elastic Compute Cloud": ("compute-infra","self-hosted-cloud-GPU","real-time-inference"),
 "Amazon Simple Storage Service": ("storage","hyperscaler-platform","data-prep"),
}
def adapt_aws(row):
    svc = row["ServiceName"]; domain, deploy, life = AWS_SVC.get(svc,(UNMAPPED,UNMAPPED,UNMAPPED))
    desc = row.get("ChargeDescription","").lower()
    if svc=="Amazon Elastic Compute Cloud" and (row.get("ServiceCategory")=="Networking" or "datatransfer" in desc):
        domain, deploy, life = "networking","hyperscaler-platform","serving-idle"
    tags = json.loads(row.get("Tags") or "{}")
    COMMIT_MAP = {"Provisioned Throughput":"provisioned-throughput-unit","Savings Plan":"savings-plan",
                  "Reserved Instance":"reserved-instance","":"none","none":"none"}
    commit = COMMIT_MAP.get(row.get("CommitmentDiscountType","") or "none", row.get("CommitmentDiscountType",""))
    return rec(source_file="aws_focus.csv", ProviderName="AWS", ServiceName=svc, CostDomain=domain,
        DeploymentModel=deploy, ModelChannel="hyperscaler-marketplace" if svc=="Amazon Bedrock" else "n/a",
        ModelProvider="Anthropic" if row.get("PublisherName")=="Anthropic" else "",
        ModelTier="mid" if svc=="Amazon Bedrock" else "", WorkloadLifecycle=life,
        PricingUnit=row.get("PricingUnit",""),
        PricingModel="committed-savings-plan" if commit not in ("","none") else "on-demand",
        CommitmentDiscountType=commit, CommitmentEligible="TRUE" if commit not in ("","none") else "FALSE",
        CapexVsOpex="opex", FixedVsVariable="fixed" if commit not in ("","none") else "variable",
        ChargeCategory=row.get("ChargeCategory",""), Environment=tags.get("env",""),
        BusinessUnit=tags.get("bu",""), Quantity=row.get("PricingQuantity",""), BilledCost=row.get("BilledCost",""))

# --- OpenAI ---
def adapt_openai(row):
    op = row["operation"]; dom = {"chat.completions":("inference","real-time-inference"),
        "embeddings":("inference","data-prep"),"web_search":("retrieval-RAG","real-time-inference")}
    domain, life = dom.get(op,(UNMAPPED,UNMAPPED))
    pm = {"standard":"on-demand","batch":"batch","flex":"flex-tier","priority":"priority-tier"}.get(row.get("service_tier","standard"),"on-demand")
    if pm=="batch": life="batch-inference"
    name=row["model"]; chan="fine-tuned-hosted" if name.startswith("ft:") else "direct-lab-API"
    return rec(source_file="frontier_openai.csv", ProviderName="OpenAI", ServiceName=f"OpenAI {op}",
        CostDomain=domain, DeploymentModel="managed-API", ModelChannel=chan, ModelProvider="OpenAI",
        ModelTier=tier(name), ModelName=name, WorkloadLifecycle=life,
        PricingUnit="per-request" if op=="web_search" else "per-token", PricingModel=pm,
        CommitmentEligible="FALSE", CapexVsOpex="opex", FixedVsVariable="variable", ChargeCategory="Usage",
        Environment="prod" if row["project"].startswith("prod") else "non-prod", BusinessUnit=row["project"],
        Quantity=row.get("input_tokens",""), BilledCost=row["amount_usd"])

# --- Anthropic ---
def adapt_anthropic(row):
    ut=row["usage_type"]
    if ut=="tokens": domain,life,unit="inference","real-time-inference","per-token"
    elif ut=="agent_runtime": domain,life,unit="orchestration-agents","real-time-inference","per-instance-hour"
    else: domain,life,unit=UNMAPPED,UNMAPPED,UNMAPPED
    pm="batch" if row.get("service_tier")=="batch" else "on-demand"
    if pm=="batch": life="batch-inference"
    name=row.get("model","")
    return rec(source_file="frontier_anthropic.csv", ProviderName="Anthropic",
        ServiceName="Claude API" if ut=="tokens" else "Claude Managed Agents", CostDomain=domain,
        DeploymentModel="managed-API", ModelChannel="direct-lab-API", ModelProvider="Anthropic",
        ModelTier=tier(name), ModelName=name, WorkloadLifecycle=life, PricingUnit=unit, PricingModel=pm,
        CommitmentEligible="FALSE", CapexVsOpex="opex", FixedVsVariable="variable", ChargeCategory="Usage",
        Environment="prod", BusinessUnit=row.get("workspace",""),
        Quantity=row.get("input_tokens","") or row.get("quantity_hours",""), BilledCost=row["amount_usd"])

# --- Colo vendor invoice ---
COLO_CAT = {
 "space":      ("facilities-hardware","per-instance-hour","serving-idle"),
 "power":      ("facilities-hardware","per-instance-hour","serving-idle"),
 "interconnect":("networking","per-GB-transfer","serving-idle"),
 "network":    ("networking","per-GB-transfer","serving-idle"),
 "services":   ("professional-services","per-instance-hour","serving-idle"),
}
def adapt_colo(row):
    cat=row["category"]; domain,unit,life=COLO_CAT.get(cat,(UNMAPPED,UNMAPPED,UNMAPPED))
    committed = row.get("commitment")=="contract"
    return rec(source_file="colo_invoice.csv", ProviderName="Colo (Equinix-class)", ServiceName=row["line_item"],
        CostDomain=domain, DeploymentModel="colocation", ModelChannel="n/a", WorkloadLifecycle=life,
        PricingUnit=row.get("unit",unit),
        PricingModel="committed-savings-plan" if committed else "on-demand",
        CommitmentDiscountType="enterprise-agreement" if committed else "none",
        CommitmentEligible="TRUE" if committed else "FALSE", CapexVsOpex="opex",
        FixedVsVariable="fixed" if committed else "variable", ChargeCategory="Usage",
        Environment="prod", BusinessUnit="platform", Quantity=row.get("quantity",""), BilledCost=row["amount_usd"])

# --- Colo owned-hardware depreciation ---
DEP_CLASS = {
 "gpu_server":   ("compute-infra","real-time-inference"),
 "network_switch":("networking","serving-idle"),
 "storage_array":("storage","serving-idle"),
}
def adapt_depreciation(row):
    ac=row["asset_class"]; domain,life=DEP_CLASS.get(ac,(UNMAPPED,UNMAPPED))
    return rec(source_file="colo_depreciation.csv", ProviderName="Owned hardware (colo)",
        ServiceName=f"{row['asset_id']} depreciation", CostDomain=domain, DeploymentModel="colocation",
        ModelChannel="self-hosted-weights" if ac=="gpu_server" else "n/a", WorkloadLifecycle=life,
        PricingUnit="flat", PricingModel="subscription", CommitmentDiscountType="none",
        CommitmentEligible="FALSE", CapexVsOpex="capex", FixedVsVariable="fixed", ChargeCategory="Purchase",
        Environment="prod", BusinessUnit="platform", Quantity=row.get("useful_life_months",""),
        BilledCost=row["monthly_depreciation"])

ADAPTERS = {
 "aws_focus.csv": adapt_aws,
 "frontier_openai.csv": adapt_openai,
 "frontier_anthropic.csv": adapt_anthropic,
 "colo_invoice.csv": adapt_colo,
 "colo_depreciation.csv": adapt_depreciation,
}

def run(check=False):
    out=[]
    for fn,ad in ADAPTERS.items():
        with open(os.path.join(RAW,fn)) as f:
            for raw in csv.DictReader(f): out.append(ad(raw))
    with open(OUT,"w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=CANON); w.writeheader(); w.writerows(out)
    from collections import Counter
    unmapped=[(r["source_file"],r["ServiceName"],c) for r in out for c in CANON if r[c]==UNMAPPED]
    print(f"normalized {len(out)} lines across {len(ADAPTERS)} shapes -> {os.path.basename(OUT)}")
    print("CostDomain:", dict(Counter(r['CostDomain'] for r in out)))
    print("DeploymentModel:", dict(Counter(r['DeploymentModel'] for r in out)))
    print("CapexVsOpex:", dict(Counter(r['CapexVsOpex'] for r in out)))
    total=sum(float(r['BilledCost']) for r in out)
    colo=sum(float(r['BilledCost']) for r in out if r['DeploymentModel']=='colocation')
    api=sum(float(r['BilledCost']) for r in out if r['DeploymentModel']=='managed-API')
    aws=sum(float(r['BilledCost']) for r in out if r['ProviderName']=='AWS')
    print(f"total ${total:,.2f}  |  AWS ${aws:,.2f}  |  frontier-API ${api:,.2f}  |  colo ${colo:,.2f}")
    if unmapped:
        print(f"\nFAIL: {len(unmapped)} UNMAPPED"); [print("  ",u) for u in unmapped]
        if check: sys.exit(1)
    else:
        print("\nPASS: full coverage across cloud + API + colo.")

if __name__=="__main__":
    run(check="--check" in sys.argv)
