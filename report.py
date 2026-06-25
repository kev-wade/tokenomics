#!/usr/bin/env python3
"""
AI cost reporting layer (pandas).

Reads a normalized cost file (canonical schema from ai-cost-allocation-workbook.xlsx),
pivots on CostDomain / DeploymentModel / WorkloadLifecycle, and surfaces totals,
commitment-coverage rates, and waste/governance flags.

Usage:
    python report.py [normalized_output.csv] [--xlsx cost_report.xlsx]

Prints a console summary and (optionally) writes a multi-sheet workbook of pivots.
"""
import sys
import pandas as pd

# domains where on-demand spend could plausibly be moved onto a commitment
COVERAGE_ELIGIBLE_DOMAINS = {"compute-infra", "inference", "training"}


def load(path):
    df = pd.read_csv(path)
    df["BilledCost"] = pd.to_numeric(df["BilledCost"], errors="coerce").fillna(0.0)
    return df


def pct(part, whole):
    return 0.0 if whole == 0 else part / whole


def breakdown(df, dim):
    g = (df.groupby(dim)["BilledCost"].sum().sort_values(ascending=False))
    out = g.reset_index()
    total = df["BilledCost"].sum()
    out["pct_of_total"] = out["BilledCost"].apply(lambda x: pct(x, total))
    return out


def commitment_metrics(df):
    total = df["BilledCost"].sum()
    committed_mask = df["CommitmentDiscountType"].ne("none")
    committed = df.loc[committed_mask, "BilledCost"].sum()
    unused = df.loc[df["WasteFlag"].eq("unused-commitment"), "BilledCost"].sum()
    # CommitmentDiscountStatus is optional; if absent, treat committed-minus-unused as used
    if "CommitmentDiscountStatus" in df.columns:
        used = df.loc[committed_mask & df["CommitmentDiscountStatus"].eq("Used"), "BilledCost"].sum()
    else:
        used = committed - unused
    opportunity = df.loc[df["PricingModel"].eq("on-demand") &
                         df["CostDomain"].isin(COVERAGE_ELIGIBLE_DOMAINS), "BilledCost"].sum()
    coverage = pct(used, used + opportunity)
    return {
        "total_spend": total,
        "committed_spend": committed,
        "committed_used": used,
        "committed_unused_waste": unused,
        "coverage_eligible_ondemand_opportunity": opportunity,
        "effective_coverage_rate": coverage,
        "committed_pct_of_total": pct(committed, total),
    }


def waste_governance(df):
    total = df["BilledCost"].sum()
    waste = (df.loc[df["WasteFlag"].ne("none")]
             .groupby("WasteFlag")["BilledCost"].sum().sort_values(ascending=False)
             .reset_index())
    waste["pct_of_total"] = waste["BilledCost"].apply(lambda x: pct(x, total))
    shadow = df.loc[df["GovernanceStatus"].eq("shadow-AI"), "BilledCost"].sum()
    return waste, shadow, df["WasteFlag"].ne("none").pipe(lambda m: df.loc[m, "BilledCost"].sum())


def money(x):
    return f"${x:,.2f}"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "normalized_output.csv"
    xlsx_out = None
    if "--xlsx" in sys.argv:
        i = sys.argv.index("--xlsx")
        xlsx_out = sys.argv[i + 1] if i + 1 < len(sys.argv) else "cost_report.xlsx"

    df = load(path)
    total = df["BilledCost"].sum()

    by_domain = breakdown(df, "CostDomain")
    by_deploy = breakdown(df, "DeploymentModel")
    by_life = breakdown(df, "WorkloadLifecycle")
    by_provider = breakdown(df, "ProviderName")
    pivot = pd.pivot_table(df, values="BilledCost", index="CostDomain",
                           columns="DeploymentModel", aggfunc="sum", fill_value=0.0,
                           margins=True, margins_name="Total")
    cm = commitment_metrics(df)
    waste, shadow, total_waste = waste_governance(df)

    print("=" * 64)
    print(f"AI SPEND REPORT   |   {len(df)} line items   |   total {money(total)}")
    print("=" * 64)

    def table(title, frame):
        print(f"\n-- {title} --")
        f = frame.copy()
        f["BilledCost"] = f["BilledCost"].map(money)
        if "pct_of_total" in f:
            f["pct_of_total"] = f["pct_of_total"].map(lambda x: f"{x:5.1%}")
        print(f.to_string(index=False))

    table("Spend by CostDomain", by_domain)
    table("Spend by DeploymentModel", by_deploy)
    table("Spend by WorkloadLifecycle", by_life)
    table("Spend by Provider", by_provider)

    print("\n-- Pivot: CostDomain x DeploymentModel --")
    fmt = pivot.map if hasattr(pivot, "map") else pivot.applymap
    print(fmt(lambda x: f"{x:,.0f}").to_string())

    print("\n-- Commitment Coverage --")
    print(f"  Total spend ................................ {money(cm['total_spend'])}")
    print(f"  On-commitment (committed) .................. {money(cm['committed_spend'])}  ({cm['committed_pct_of_total']:.1%} of total)")
    print(f"    of which actively used ................... {money(cm['committed_used'])}")
    print(f"    of which UNUSED (waste) ................. {money(cm['committed_unused_waste'])}")
    print(f"  Coverage-eligible on-demand (opportunity) .. {money(cm['coverage_eligible_ondemand_opportunity'])}")
    print(f"  EFFECTIVE COVERAGE RATE .................... {cm['effective_coverage_rate']:.1%}")

    print("\n-- Waste & Governance --")
    if len(waste):
        for _, r in waste.iterrows():
            print(f"  {r['WasteFlag']:22} {money(r['BilledCost']):>14}  ({r['pct_of_total']:.1%})")
    print(f"  {'TOTAL flagged waste':22} {money(total_waste):>14}  ({pct(total_waste, total):.1%})")
    print(f"  {'Shadow-AI spend':22} {money(shadow):>14}  ({pct(shadow, total):.1%})")

    if xlsx_out:
        from openpyxl import Workbook
        from openpyxl.utils.dataframe import dataframe_to_rows
        wb = Workbook()
        wb.remove(wb.active)
        sheets = {
            "by_CostDomain": (by_domain, False),
            "by_DeploymentModel": (by_deploy, False),
            "by_WorkloadLifecycle": (by_life, False),
            "by_Provider": (by_provider, False),
            "pivot_domain_x_deploy": (pivot.reset_index(), False),
            "commitment_coverage": (pd.DataFrame(list(cm.items()), columns=["metric", "value"]), False),
            "waste": (waste, False),
        }
        for name, (frame, idx) in sheets.items():
            ws = wb.create_sheet(name[:31])
            for row in dataframe_to_rows(frame, index=idx, header=True):
                ws.append(row)
        wb.active = 0
        wb.save(xlsx_out)
        print(f"\nwrote {xlsx_out}")


if __name__ == "__main__":
    main()
