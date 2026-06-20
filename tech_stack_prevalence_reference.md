# Technology Stack Reference: Prevalence, Inheritance & Multi-Path Collection Intelligence

---

## Purpose

This document answers a different question than the system prompt. The prompt tells you *how* to collect data once you know the environment. This document tells you **what's probably already there** before you ask a single question, and **when multiple collection paths exist, which one to default to and why**.

Use this to walk into a customer conversation already knowing the likely answer before they tell you — and to know the tradeoffs the moment they name their actual stack.

**A note on the percentages in this document:** these are calibrated estimates based on general enterprise infrastructure patterns, not survey data with a citable source. Treat them as "what to expect" priors, not precise statistics. They will shift by industry vertical (e.g., financial services and healthcare skew more heavily toward VMware and legacy monitoring than tech-sector companies) and by company size (larger, older enterprises carry more legacy tooling debt). Where it matters, that variance is called out.

---

## Part 1: The Monitoring/Observability Inheritance Layer

**This is the highest-leverage section in this document.** Before designing any new collection pipeline, find out what's already deployed. In the large majority of enterprise engagements, *something* is already collecting telemetry — the work is extracting FinOps-relevant data from it, not deploying new agents from scratch.

### Likelihood Snapshot — "What's probably already in this environment"

| Tool | Rough Prevalence in Mid-to-Large Enterprise | Strongest Footprint |
|---|---|---|
| **Datadog** | Common in tech-forward orgs, cloud-native shops, ~last 6-8 years of adoption | Cloud + Kubernetes + APM |
| **SolarWinds** | Very common in traditional IT shops, especially network/infra-first orgs | Network, on-prem infra |
| **SCOM (System Center)** | Common where Microsoft/Windows-centric infrastructure dominates | Windows Server, Hyper-V, AD |
| **Splunk** | Common where security/compliance is a major driver (FSI, healthcare, gov) | Logs, security, SIEM-adjacent |
| **Dynatrace** | Common in large enterprises with complex app dependency mapping needs | APM, full-stack, AI-assisted root cause |
| **Prometheus + Grafana** | Very common in any org running Kubernetes; near-default for cloud-native | Containers, cloud-native, custom apps |
| **Nagios / Zabbix** | Common in cost-conscious or legacy on-prem shops, often older deployments | Basic infra uptime/health |
| **New Relic** | Moderate, mostly application-performance-focused orgs | APM, application-layer |
| **LogicMonitor / PRTG / ManageEngine** | Moderate, especially in mid-market and MSP-managed environments | Infra + network, SNMP-heavy |
| **Nothing centralized / native tools only** | Surprisingly common in smaller or recently-merged-via-M&A enterprises | N/A |

**Practical rule of thumb:** in roughly 80% of mid-to-large enterprise engagements, you will find *at least one* of: SCOM, SolarWinds, Datadog, Splunk, or Prometheus already deployed somewhere in the environment. The remaining ~20% either have fragmented point tools per team, or rely entirely on cloud-native monitoring (CloudWatch/Azure Monitor only) with no centralized layer — which is itself useful information, because it tells you there's no inheritance to leverage and you're starting closer to zero.

### Why This Matters for FinOps Data Collection

Existing monitoring tools were deployed for **operational** purposes (uptime, performance, alerting) — not cost. But most of them already capture the utilization metrics (CPU, memory, disk, GPU in some cases) that FinOps needs. The question becomes: *extract from the existing tool, or deploy a parallel collection path?*

**Default guidance:** extract from what's already there whenever the existing tool has API access and retention sufficient for your reporting cadence. Deploying a second telemetry pipeline duplicates agent overhead, creates data reconciliation problems, and is usually a harder sell to the infrastructure team than "give us read access to what you already have."

### Tool-by-Tool: Extraction Path & Tradeoffs

**Datadog**
- Extraction: Datadog API (metrics, host tags) or Datadog's own Cloud Cost Management module if licensed
- **[Low] [Industry Standard] [API] [Near-real-time]**
- Tradeoff: Datadog's own cost module is good but is an additional license; raw metrics API is "free" if Datadog is already paid for, but requires you to build the cost-correlation layer yourself

**SolarWinds**
- Extraction: SolarWinds Orion SDK / REST API (SWQL query language)
- **[Medium] [Common Practice] [API] [Near-real-time to Batch]**
- Tradeoff: API access is reasonably mature but query language (SWQL) has a learning curve; strong for network and on-prem infra, weak/absent for cloud and SaaS — expect to need a second source for those layers

**SCOM**
- Extraction: SCOM SDK (PowerShell `Get-SCOMPerformanceCounter`), or direct SQL query against the SCOM Data Warehouse database
- **[Medium] [Common Practice] [API/Native DB access] [Batch]**
- Tradeoff: Direct Data Warehouse DB access is more reliable at scale than the SDK for historical reporting, but requires DBA-level access — often a permissions negotiation in larger orgs

**Splunk**
- Extraction: Splunk REST API or saved search export; if infra metrics are being logged into Splunk (common when used as a SIEM with infra forwarders), they're queryable via SPL
- **[Medium] [Common Practice] [API] [Near-real-time to Batch]**
- Tradeoff: Splunk is expensive per-GB-ingested — pulling FinOps data through Splunk specifically (vs. tapping the source directly) can itself become a meaningful cost driver. Worth flagging to the customer.

**Dynatrace**
- Extraction: Dynatrace API (Metrics API v2, Smartscape topology API)
- **[Low] [Industry Standard] [API] [Real-time to Near-real-time]**
- Tradeoff: One of the strongest API layers in this category — full topology mapping included, which helps a lot with the allocation/tagging problem. Higher license cost tier, so less common in cost-conscious orgs.

**Prometheus + Grafana**
- Extraction: Direct PromQL query against Prometheus, or Grafana's own data source API
- **[Low] [Industry Standard] [API] [Real-time]**
- Tradeoff: Excellent for real-time and is usually already collecting the exact metrics you need if Kubernetes/cloud-native is in play. Major limitation: default retention is short (15 days is common) unless long-term storage (Thanos, Cortex, Mimir) is configured — confirm retention before assuming historical data exists.

**Nagios / Zabbix**
- Extraction: Zabbix API (JSON-RPC) is reasonably solid; Nagios is weaker, often requires plugin-specific export or NRPE-based polling
- **[Medium] [Common Practice] [API varies] [Batch]**
- Tradeoff: Zabbix is a credible source; Nagios is usually better treated as an alerting tool than a data source — if Nagios is what's present, plan to deploy a parallel collector rather than fight its export limitations

**No centralized tool present**
- This is itself a finding: it usually means utilization data collection needs to be built from scratch using the native platform tools covered in the system prompt (WMI, vCenter API, CloudWatch, etc.)
- **Signal to the customer:** this is a longer engagement (Medium-to-High complexity) because there's no inheritance to leverage — set expectations accordingly

---

## Part 2: Hardware Vendor / BMC Layer (Bare Metal)

### Likelihood Snapshot

| Vendor | Rough Prevalence in Enterprise Datacenter | BMC / Out-of-Band Tool |
|---|---|---|
| **Dell** | Most common single vendor in general enterprise server fleets | iDRAC |
| **HPE** | Second most common, especially in legacy/longer-tenured datacenters | iLO |
| **Cisco UCS** | Common where blade/converged infrastructure was adopted (often paired with VMware) | CIMC / Intersight |
| **Lenovo** | Moderate, growing especially post-IBM x86 acquisition | XClarity |
| **Supermicro** | Common in GPU-dense / AI infrastructure builds and hyperscale-adjacent shops | IPMI / Redfish-native |

In roughly 80% of traditional enterprise on-prem environments, Dell and HPE together account for the majority of the server fleet. Supermicro shows up disproportionately often specifically in **GPU/AI infrastructure** builds, even in shops that are otherwise Dell- or HPE-standardized — because GPU-dense configurations are often sourced separately for AI initiatives.

### Multi-Path Comparison: Hardware Telemetry Extraction

| Path | Works On | Status | Tradeoff |
|---|---|---|---|
| **Vendor REST API (iDRAC RESTful API, iLO RESTful API, XClarity API)** | Single vendor only | **Industry Standard for that vendor** | Most complete data, but you build a separate integration per vendor in a mixed fleet |
| **Redfish (DMTF open standard)** | Cross-vendor — Dell, HPE, Lenovo, Supermicro all support it | **Industry Standard, increasingly the default recommendation** | One integration works across vendors; some older firmware versions have incomplete Redfish implementations — worth a firmware version check before committing to this path as the sole source |
| **IPMI (legacy protocol)** | Nearly universal, including older hardware | **Common Practice, considered legacy** | Works almost everywhere but exposes less data than Redfish (no detailed inventory, weaker security model); fallback when Redfish isn't available |
| **SNMP polling of BMC** | Broad, vendor-dependent OID sets | **Common Practice** | Reliable for basic health/power but MIB structures differ by vendor — more normalization work than Redfish |

**Default recommendation for mixed-vendor fleets:** standardize on **Redfish** as the primary collection path. It's the one approach in this table built explicitly to solve the multi-vendor problem, and vendor adoption is now broad enough (all five vendors above support it) that it's a defensible default rather than a bet on emerging tech. Use IPMI only as a fallback for hardware too old to support Redfish.

---

## Part 3: GPU Vendor Layer

### Likelihood Snapshot

NVIDIA holds a dominant share of enterprise datacenter AI accelerator deployments as of 2025 — in most customer conversations, assume NVIDIA unless told otherwise; it will be correct the substantial majority of the time. AMD (MI300-series) has a growing but still clearly minority footprint, concentrated in a smaller number of large-scale or HPC-oriented deployments. Intel Gaudi has a niche presence, occasionally specifically because of price/availability arbitrage during NVIDIA supply constraints.

**Practical rule of thumb:** ask "NVIDIA, or something else?" rather than "what GPU vendor do you use?" — framing it this way reflects the actual base rate and gets you to the real answer faster.

### Multi-Path Comparison: GPU Telemetry Extraction

| Path | Vendor | Status | Tradeoff |
|---|---|---|---|
| **DCGM (Data Center GPU Manager)** | NVIDIA only | **Industry Standard** | The default for any NVIDIA datacenter deployment. Deep metric set (SM activity, NVLink, thermal, ECC errors), Prometheus-native export. No reason not to use this if NVIDIA is in play. |
| **nvidia-smi (CLI/XML)** | NVIDIA only | **Industry Standard for ad hoc, not for pipelines** | Always available, zero setup, but not designed for continuous pipeline ingestion at scale — use for verification/troubleshooting, not production telemetry |
| **AMD ROCm SMI / AMD SMI** | AMD only | **Common Practice, less mature ecosystem** | Functional equivalent to nvidia-smi for AMD GPUs; Prometheus exporter support exists but is less standardized and has a smaller community/tooling base than DCGM — expect more custom integration work |
| **Intel Habana Gaudi Monitoring (hl-smi)** | Intel Gaudi only | **Emerging** | Workable but the smallest ecosystem of the three; expect to build more from scratch, including dashboards and alerting that come pre-built for NVIDIA |
| **Cloud-native GPU metrics (CloudWatch GPU metrics, Azure Monitor GPU metrics)** | Any vendor, cloud-hosted GPU instances only | **Common Practice** | Easiest path if GPUs are in a hyperscaler (not neocloud or on-prem); coverage and granularity vary by cloud provider and instance type — verify before assuming parity with DCGM-level detail |

**Key tradeoff to flag to customers explicitly:** if a customer is mixing NVIDIA and AMD GPUs (increasingly common as orgs hedge against NVIDIA supply/pricing), there is no single tool that gives unified telemetry across both today. Plan for two collection paths feeding the same normalized schema (per the Resource/Metric schema in the system prompt) rather than searching for a unified tool that doesn't yet exist at production maturity.

---

## Part 4: Hypervisor / Virtualization Layer

### Likelihood Snapshot

| Hypervisor | Rough Prevalence in Enterprise On-Prem | Notes |
|---|---|---|
| **VMware vSphere** | Historically the dominant enterprise hypervisor by a wide margin | Still the most likely default in any legacy enterprise on-prem footprint; Broadcom's licensing changes (post-2023 acquisition) are actively pushing some customers toward alternatives — expect more in-flight migrations than in past years |
| **Microsoft Hyper-V** | Common, especially in Microsoft-centric or Windows Server-heavy shops | Often coexists with VMware rather than fully replacing it |
| **Nutanix AHV** | Growing, especially among customers who adopted Nutanix for hyperconverged infrastructure | Often a deliberate alternative chosen partly *because of* VMware licensing concerns |
| **KVM / Proxmox / open source** | Smaller but real, more common in cost-conscious or engineering-culture-heavy orgs | Less common in traditional enterprise, more common in tech-sector or cloud-native-adjacent companies |
| **Bare metal / no hypervisor** | Common specifically for GPU-dense AI workloads and Oracle RAC-style database tiers | Virtualization overhead avoidance is a deliberate choice in these cases, not an oversight |

**Practical rule of thumb:** assume VMware is present *somewhere* in a traditional enterprise on-prem footprint in the large majority of cases, even if it's not the only hypervisor in play. The open question is usually "what else is alongside it," not "is VMware here."

**Active trend worth raising proactively with customers:** Broadcom's VMware licensing changes have measurably accelerated hypervisor migration conversations since 2023–2024. If a customer mentions VMware, it's worth asking directly whether a migration to Hyper-V, Nutanix AHV, or KVM is under consideration — this materially changes the data collection roadmap, since you'd otherwise build a pipeline for a platform that may not be there in 18 months.

---

## Part 5: Storage Layer

### Likelihood Snapshot

| Vendor | Rough Prevalence | API Maturity |
|---|---|---|
| **Dell EMC (PowerStore, PowerMax, Unity, Isilon/PowerScale)** | Most common single vendor footprint in large enterprise | Strong, REST API across product lines |
| **NetApp (ONTAP)** | Very common, especially in mixed/hybrid and file-storage-heavy environments | Strong — ONTAP REST API is mature and well-documented |
| **Pure Storage** | Growing, especially in newer or refresh-cycle deployments | Strong — API-first design philosophy from the start |
| **HPE (3PAR/Primera/Nimble/Alletra)** | Common alongside HPE compute standardization | Moderate-to-strong, varies by product line/generation |

### Multi-Path Comparison: Storage Telemetry

| Path | Status | Tradeoff |
|---|---|---|
| **Vendor REST API (ONTAP API, PowerStore API, Pure1 API)** | **Industry Standard** | Richest data (IOPS, latency, capacity, dedup ratios), but vendor-specific integration work in mixed environments |
| **SNMP** | **Common Practice, legacy** | Universal fallback, much shallower data set — capacity and basic health only |
| **SMI-S (Storage Management Initiative Specification)** | **Emerging → Declining** | Was meant to be the cross-vendor standard; adoption has been inconsistent and most vendors now push their own REST APIs instead — generally not worth building around today despite being "the standard" on paper |

**Practical guidance:** unlike the BMC layer (where Redfish has succeeded as a real cross-vendor standard), storage has not converged on an equivalent. Plan for vendor-specific integrations per storage platform present in the environment.

---

## Part 6: Decision Framework — When Multiple Paths Exist

When you find more than one viable collection path for the same data, apply this priority order:

1. **Is there already a deployed tool that captures this data for operational purposes?** (Part 1 of this document) — extracting from it is almost always lower effort and lower political friction than deploying something new.

2. **Does a cross-vendor/cross-platform standard exist and is it mature?** (Redfish for hardware = yes; SMI-S for storage = no, in practice) — prefer the standard when it's genuinely mature, not just nominally available.

3. **What's the freshness requirement?** (per the Data Freshness Decision Guide in the system prompt) — don't build a real-time streaming pipeline for a monthly chargeback report; don't rely on a 24-hour-lagged billing export for real-time GPU alerting.

4. **What access will the customer actually grant?** Often the deciding factor in practice isn't technical superiority — it's whether the infrastructure or security team will approve API credentials, agent installation, or database access. Always ask about this constraint before designing the "ideal" architecture; an elegant pipeline the customer won't approve is worth less than a slightly-less-elegant one they will.

5. **Is this a one-time assessment or an ongoing managed pipeline?** A one-time FinOps assessment can tolerate manual exports and on-demand pulls. An ongoing managed service needs API-based, automatable paths — re-evaluate any "Trivial / On-demand" path if the engagement is meant to be continuous.
