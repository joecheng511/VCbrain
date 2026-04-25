"""
Mock Layer 2 API server for VCbrain development & testing.

Run with:  uvicorn mock_layer2:app --port 8000

Serves GET /entity/{name} with realistic VC-relevant fact graphs for 20
EnterpriseBench-style companies. Mirrors the exact schema of the real Layer 2 API.
"""

from fastapi import FastAPI, HTTPException

app = FastAPI(title="VCbrain Layer 2 Mock")

# ──────────────────────────────────────────────────────────────────────────────
# Mock entity database — 20 companies
# ──────────────────────────────────────────────────────────────────────────────

ENTITIES: dict[str, dict] = {

    "Acme Analytics": {
        "entity": {"id": "ent-001", "type": "Company", "name": "Acme Analytics"},
        "facts": [
            {"attribute": "sector", "value": "B2B SaaS / Data Analytics",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-001"}},
            {"attribute": "ARR", "value": "$2M",
             "confidence": 0.95, "source": {"type": "crm", "external_id": "crm-002"}},
            {"attribute": "revenue_growth_yoy", "value": "3x YoY",
             "confidence": 0.90, "source": {"type": "data_room", "external_id": "dr-001"}},
            {"attribute": "employees", "value": "12",
             "confidence": 0.98, "source": {"type": "linkedin", "external_id": "li-001"}},
            {"attribute": "founded", "value": "2021",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-001"}},
            {"attribute": "funding_raised", "value": "Seed $1.5M",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-003"}},
            {"attribute": "key_customers", "value": "Fortune 500 pilot with 3 enterprise clients",
             "confidence": 0.85, "source": {"type": "data_room", "external_id": "dr-002"}},
        ],
        "conflicts": [],
    },

    "DataVault Inc": {
        "entity": {"id": "ent-002", "type": "Company", "name": "DataVault Inc"},
        "facts": [
            {"attribute": "sector", "value": "Data Infrastructure",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-010"}},
            {"attribute": "ARR", "value": "$500K",
             "confidence": 0.88, "source": {"type": "crm", "external_id": "crm-011"}},
            {"attribute": "revenue_growth_yoy", "value": "2x YoY",
             "confidence": 0.80, "source": {"type": "data_room", "external_id": "dr-010"}},
            {"attribute": "employees", "value": "8",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-010"}},
            {"attribute": "founded", "value": "2022",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-010"}},
            {"attribute": "technology", "value": "Encrypted data lake with zero-knowledge proofs",
             "confidence": 0.92, "source": {"type": "data_room", "external_id": "dr-011"}},
        ],
        "conflicts": [],
    },

    "NeuralEdge Systems": {
        "entity": {"id": "ent-003", "type": "Company", "name": "NeuralEdge Systems"},
        "facts": [
            {"attribute": "sector", "value": "AI/ML Infrastructure",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-020"}},
            {"attribute": "ARR", "value": "$0 (pre-revenue)",
             "confidence": 0.95, "source": {"type": "crm", "external_id": "crm-021"}},
            {"attribute": "employees", "value": "6",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-020"}},
            {"attribute": "founded", "value": "2023",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-020"}},
            {"attribute": "technology", "value": "Edge inference engine, 10x latency reduction vs cloud",
             "confidence": 0.65, "source": {"type": "pitch_deck", "external_id": "pd-020"}},
            {"attribute": "patents", "value": "2 provisional patents filed",
             "confidence": 0.80, "source": {"type": "data_room", "external_id": "dr-020"}},
            {"attribute": "pilot_customers", "value": "1 unpaid pilot with automotive OEM",
             "confidence": 0.75, "source": {"type": "crm", "external_id": "crm-022"}},
        ],
        "conflicts": [],
    },

    "CloudStream Tech": {
        "entity": {"id": "ent-004", "type": "Company", "name": "CloudStream Tech"},
        "facts": [
            {"attribute": "sector", "value": "Cloud Infrastructure",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-030"}},
            {"attribute": "ARR", "value": "$5M",
             "confidence": 0.96, "source": {"type": "data_room", "external_id": "dr-030"}},
            {"attribute": "revenue_growth_yoy", "value": "2.5x YoY",
             "confidence": 0.93, "source": {"type": "data_room", "external_id": "dr-031"}},
            {"attribute": "employees", "value": "35",
             "confidence": 0.98, "source": {"type": "linkedin", "external_id": "li-030"}},
            {"attribute": "founded", "value": "2020",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-030"}},
            {"attribute": "funding_raised", "value": "Series A $8M",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-031"}},
            {"attribute": "net_revenue_retention", "value": "128%",
             "confidence": 0.91, "source": {"type": "data_room", "external_id": "dr-032"}},
            {"attribute": "customers", "value": "47 paying enterprise customers",
             "confidence": 0.95, "source": {"type": "crm", "external_id": "crm-032"}},
        ],
        "conflicts": [],
    },

    "FinFlow Solutions": {
        "entity": {"id": "ent-005", "type": "Company", "name": "FinFlow Solutions"},
        "facts": [
            {"attribute": "sector", "value": "Fintech / Payments",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-040"}},
            {"attribute": "employees", "value": "22",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-040"}},
            {"attribute": "founded", "value": "2021",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-040"}},
            {"attribute": "regulatory_status", "value": "EMI licence pending UK FCA",
             "confidence": 0.85, "source": {"type": "data_room", "external_id": "dr-040"}},
        ],
        "conflicts": [
            {
                "attribute": "ARR",
                "value_a": "$1.2M", "value_b": "$800K",
                "status": "open",
            }
        ],
    },

    "MediTrack AI": {
        "entity": {"id": "ent-006", "type": "Company", "name": "MediTrack AI"},
        "facts": [
            {"attribute": "sector", "value": "Healthcare AI",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-050"}},
            {"attribute": "ARR", "value": "$300K",
             "confidence": 0.82, "source": {"type": "crm", "external_id": "crm-051"}},
            {"attribute": "employees", "value": "15",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-050"}},
            {"attribute": "founded", "value": "2020",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-050"}},
            {"attribute": "regulatory_block", "value": "FDA 510k rejected twice; resubmission timeline unknown",
             "confidence": 0.95, "source": {"type": "data_room", "external_id": "dr-050"}},
            {"attribute": "burn_rate", "value": "$180K/month with 4 months runway",
             "confidence": 0.90, "source": {"type": "data_room", "external_id": "dr-051"}},
        ],
        "conflicts": [],
    },

    "Quantum Compute Labs": {
        "entity": {"id": "ent-007", "type": "Company", "name": "Quantum Compute Labs"},
        "facts": [
            {"attribute": "sector", "value": "Deep Tech / Quantum Computing",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-060"}},
            {"attribute": "ARR", "value": "$0 (pre-revenue)",
             "confidence": 0.95, "source": {"type": "crm", "external_id": "crm-061"}},
            {"attribute": "employees", "value": "9",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-060"}},
            {"attribute": "founded", "value": "2022",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-060"}},
            {"attribute": "team_background", "value": "2x PhD quantum physics MIT, 1x ex-IBM Quantum",
             "confidence": 0.93, "source": {"type": "data_room", "external_id": "dr-060"}},
            {"attribute": "grant_funding", "value": "DARPA grant $2M awarded",
             "confidence": 0.98, "source": {"type": "data_room", "external_id": "dr-061"}},
            {"attribute": "technology_readiness", "value": "TRL 3 — experimental proof of concept",
             "confidence": 0.60, "source": {"type": "pitch_deck", "external_id": "pd-060"}},
        ],
        "conflicts": [],
    },

    "RetailGenius": {
        "entity": {"id": "ent-008", "type": "Company", "name": "RetailGenius"},
        "facts": [
            {"attribute": "sector", "value": "E-commerce AI / Retail Tech",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-070"}},
            {"attribute": "ARR", "value": "$3.2M",
             "confidence": 0.94, "source": {"type": "data_room", "external_id": "dr-070"}},
            {"attribute": "revenue_growth_yoy", "value": "4x YoY",
             "confidence": 0.92, "source": {"type": "data_room", "external_id": "dr-071"}},
            {"attribute": "employees", "value": "28",
             "confidence": 0.98, "source": {"type": "linkedin", "external_id": "li-070"}},
            {"attribute": "founded", "value": "2021",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-070"}},
            {"attribute": "funding_raised", "value": "Seed $2M",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-071"}},
            {"attribute": "gross_margin", "value": "72%",
             "confidence": 0.88, "source": {"type": "data_room", "external_id": "dr-072"}},
        ],
        "conflicts": [],
    },

    "SecureVault Networks": {
        "entity": {"id": "ent-009", "type": "Company", "name": "SecureVault Networks"},
        "facts": [
            {"attribute": "sector", "value": "Cybersecurity / Zero Trust",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-080"}},
            {"attribute": "ARR", "value": "$1.8M",
             "confidence": 0.91, "source": {"type": "crm", "external_id": "crm-081"}},
            {"attribute": "revenue_growth_yoy", "value": "2.2x YoY",
             "confidence": 0.87, "source": {"type": "data_room", "external_id": "dr-080"}},
            {"attribute": "employees", "value": "18",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-080"}},
            {"attribute": "founded", "value": "2021",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-080"}},
            {"attribute": "certifications", "value": "SOC2 Type II, ISO 27001",
             "confidence": 0.98, "source": {"type": "data_room", "external_id": "dr-081"}},
        ],
        "conflicts": [],
    },

    "TalentBridge Pro": {
        "entity": {"id": "ent-010", "type": "Company", "name": "TalentBridge Pro"},
        "facts": [
            {"attribute": "sector", "value": "HR Tech / Recruiting",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-090"}},
            {"attribute": "ARR", "value": "$900K (down from $1.4M prior year)",
             "confidence": 0.93, "source": {"type": "data_room", "external_id": "dr-090"}},
            {"attribute": "churn_rate", "value": "38% annual customer churn",
             "confidence": 0.90, "source": {"type": "data_room", "external_id": "dr-091"}},
            {"attribute": "employees", "value": "14",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-090"}},
            {"attribute": "founded", "value": "2019",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-090"}},
            {"attribute": "reason_for_churn", "value": "Core feature replicated by LinkedIn Talent Insights",
             "confidence": 0.85, "source": {"type": "crm", "external_id": "crm-091"}},
        ],
        "conflicts": [],
    },

    "EcoLogic Systems": {
        "entity": {"id": "ent-011", "type": "Company", "name": "EcoLogic Systems"},
        "facts": [
            {"attribute": "sector", "value": "Climate Tech / Carbon Markets",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-100"}},
            {"attribute": "ARR", "value": "$1.1M",
             "confidence": 0.89, "source": {"type": "crm", "external_id": "crm-101"}},
            {"attribute": "revenue_growth_yoy", "value": "2.8x YoY",
             "confidence": 0.86, "source": {"type": "data_room", "external_id": "dr-100"}},
            {"attribute": "employees", "value": "16",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-100"}},
            {"attribute": "founded", "value": "2021",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-100"}},
            {"attribute": "partnerships", "value": "Verified carbon offset provider for 3 EU corporates",
             "confidence": 0.91, "source": {"type": "data_room", "external_id": "dr-101"}},
        ],
        "conflicts": [],
    },

    "HealthSync AI": {
        "entity": {"id": "ent-012", "type": "Company", "name": "HealthSync AI"},
        "facts": [
            {"attribute": "sector", "value": "Digital Health / Interoperability",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-110"}},
            {"attribute": "ARR", "value": "$4.5M",
             "confidence": 0.95, "source": {"type": "data_room", "external_id": "dr-110"}},
            {"attribute": "revenue_growth_yoy", "value": "3.5x YoY",
             "confidence": 0.93, "source": {"type": "data_room", "external_id": "dr-111"}},
            {"attribute": "employees", "value": "42",
             "confidence": 0.98, "source": {"type": "linkedin", "external_id": "li-110"}},
            {"attribute": "founded", "value": "2020",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-110"}},
            {"attribute": "regulatory_status", "value": "HIPAA compliant, HL7 FHIR certified",
             "confidence": 0.99, "source": {"type": "data_room", "external_id": "dr-112"}},
            {"attribute": "hospital_contracts", "value": "Signed contracts with 12 US hospital systems",
             "confidence": 0.96, "source": {"type": "crm", "external_id": "crm-111"}},
        ],
        "conflicts": [],
    },

    "PropTech Dynamics": {
        "entity": {"id": "ent-013", "type": "Company", "name": "PropTech Dynamics"},
        "facts": [
            {"attribute": "sector", "value": "PropTech / Real Estate AI",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-120"}},
            {"attribute": "ARR", "value": "$750K",
             "confidence": 0.84, "source": {"type": "crm", "external_id": "crm-121"}},
            {"attribute": "employees", "value": "11",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-120"}},
            {"attribute": "founded", "value": "2022",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-120"}},
            {"attribute": "market_sensitivity", "value": "Revenue fell 40% during 2023 rate hike cycle",
             "confidence": 0.88, "source": {"type": "data_room", "external_id": "dr-120"}},
        ],
        "conflicts": [
            {
                "attribute": "revenue_growth_yoy",
                "value_a": "1.5x YoY growth", "value_b": "Flat YoY",
                "status": "open",
            }
        ],
    },

    "AutoFleet Solutions": {
        "entity": {"id": "ent-014", "type": "Company", "name": "AutoFleet Solutions"},
        "facts": [
            {"attribute": "sector", "value": "Autonomous Vehicles / Logistics",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-130"}},
            {"attribute": "ARR", "value": "$200K",
             "confidence": 0.80, "source": {"type": "crm", "external_id": "crm-131"}},
            {"attribute": "employees", "value": "20",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-130"}},
            {"attribute": "founded", "value": "2020",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-130"}},
            {"attribute": "regulatory_status", "value": "No commercial deployment licence in any jurisdiction",
             "confidence": 0.95, "source": {"type": "data_room", "external_id": "dr-130"}},
            {"attribute": "burn_rate", "value": "$250K/month with 3 months runway",
             "confidence": 0.92, "source": {"type": "data_room", "external_id": "dr-131"}},
            {"attribute": "competitive_risk", "value": "Competing with Waymo and Aurora in same freight corridor",
             "confidence": 0.88, "source": {"type": "crm", "external_id": "crm-132"}},
        ],
        "conflicts": [],
    },

    "EdTech Pioneers": {
        "entity": {"id": "ent-015", "type": "Company", "name": "EdTech Pioneers"},
        "facts": [
            {"attribute": "sector", "value": "EdTech / AI Tutoring",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-140"}},
            {"attribute": "ARR", "value": "$600K",
             "confidence": 0.86, "source": {"type": "crm", "external_id": "crm-141"}},
            {"attribute": "revenue_growth_yoy", "value": "1.8x YoY",
             "confidence": 0.82, "source": {"type": "data_room", "external_id": "dr-140"}},
            {"attribute": "employees", "value": "13",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-140"}},
            {"attribute": "founded", "value": "2022",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-140"}},
            {"attribute": "unit_economics", "value": "CAC $120, LTV $180 — LTV:CAC ratio of 1.5x",
             "confidence": 0.85, "source": {"type": "data_room", "external_id": "dr-141"}},
            {"attribute": "competitive_risk", "value": "Khan Academy and Duolingo launched similar AI features",
             "confidence": 0.90, "source": {"type": "crm", "external_id": "crm-142"}},
        ],
        "conflicts": [],
    },

    "SupplyChain AI": {
        "entity": {"id": "ent-016", "type": "Company", "name": "SupplyChain AI"},
        "facts": [
            {"attribute": "sector", "value": "Supply Chain / Logistics AI",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-150"}},
            {"attribute": "ARR", "value": "$2.4M",
             "confidence": 0.93, "source": {"type": "data_room", "external_id": "dr-150"}},
            {"attribute": "revenue_growth_yoy", "value": "2.1x YoY",
             "confidence": 0.89, "source": {"type": "data_room", "external_id": "dr-151"}},
            {"attribute": "employees", "value": "24",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-150"}},
            {"attribute": "founded", "value": "2021",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-150"}},
            {"attribute": "customers", "value": "22 mid-market manufacturers as customers",
             "confidence": 0.92, "source": {"type": "crm", "external_id": "crm-151"}},
        ],
        "conflicts": [],
    },

    "LegalAI Pro": {
        "entity": {"id": "ent-017", "type": "Company", "name": "LegalAI Pro"},
        "facts": [
            {"attribute": "sector", "value": "Legal Tech / AI Contract Analysis",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-160"}},
            {"attribute": "ARR", "value": "$3.8M",
             "confidence": 0.95, "source": {"type": "data_room", "external_id": "dr-160"}},
            {"attribute": "revenue_growth_yoy", "value": "3.2x YoY",
             "confidence": 0.92, "source": {"type": "data_room", "external_id": "dr-161"}},
            {"attribute": "employees", "value": "31",
             "confidence": 0.98, "source": {"type": "linkedin", "external_id": "li-160"}},
            {"attribute": "founded", "value": "2021",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-160"}},
            {"attribute": "net_revenue_retention", "value": "135%",
             "confidence": 0.90, "source": {"type": "data_room", "external_id": "dr-162"}},
            {"attribute": "law_firm_clients", "value": "8 of the AmLaw 100 as paying clients",
             "confidence": 0.96, "source": {"type": "crm", "external_id": "crm-161"}},
        ],
        "conflicts": [],
    },

    "MarketMind Analytics": {
        "entity": {"id": "ent-018", "type": "Company", "name": "MarketMind Analytics"},
        "facts": [
            {"attribute": "sector", "value": "Marketing Analytics / Attribution",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-170"}},
            {"attribute": "ARR", "value": "$1.6M",
             "confidence": 0.90, "source": {"type": "crm", "external_id": "crm-171"}},
            {"attribute": "revenue_growth_yoy", "value": "2.3x YoY",
             "confidence": 0.87, "source": {"type": "data_room", "external_id": "dr-170"}},
            {"attribute": "employees", "value": "19",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-170"}},
            {"attribute": "founded", "value": "2021",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-170"}},
            {"attribute": "gross_margin", "value": "78%",
             "confidence": 0.87, "source": {"type": "data_room", "external_id": "dr-171"}},
        ],
        "conflicts": [],
    },

    "BioSignal Tech": {
        "entity": {"id": "ent-019", "type": "Company", "name": "BioSignal Tech"},
        "facts": [
            {"attribute": "sector", "value": "Biotech / Wearables",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-180"}},
            {"attribute": "ARR", "value": "$0 (pre-revenue)",
             "confidence": 0.95, "source": {"type": "crm", "external_id": "crm-181"}},
            {"attribute": "employees", "value": "7",
             "confidence": 0.97, "source": {"type": "linkedin", "external_id": "li-180"}},
            {"attribute": "founded", "value": "2023",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-180"}},
            {"attribute": "regulatory_path", "value": "Requires Class II FDA clearance — 18-24 month timeline",
             "confidence": 0.92, "source": {"type": "data_room", "external_id": "dr-180"}},
            {"attribute": "burn_rate", "value": "$90K/month with 6 months runway",
             "confidence": 0.89, "source": {"type": "data_room", "external_id": "dr-181"}},
            {"attribute": "IP_status", "value": "Core sensor patent contested by Medtronic",
             "confidence": 0.88, "source": {"type": "data_room", "external_id": "dr-182"}},
        ],
        "conflicts": [],
    },

    "DevOps Velocity": {
        "entity": {"id": "ent-020", "type": "Company", "name": "DevOps Velocity"},
        "facts": [
            {"attribute": "sector", "value": "Developer Tools / CI/CD",
             "confidence": 0.99, "source": {"type": "crm", "external_id": "crm-190"}},
            {"attribute": "ARR", "value": "$4.1M",
             "confidence": 0.95, "source": {"type": "data_room", "external_id": "dr-190"}},
            {"attribute": "revenue_growth_yoy", "value": "3.8x YoY",
             "confidence": 0.93, "source": {"type": "data_room", "external_id": "dr-191"}},
            {"attribute": "employees", "value": "33",
             "confidence": 0.98, "source": {"type": "linkedin", "external_id": "li-190"}},
            {"attribute": "founded", "value": "2021",
             "confidence": 0.99, "source": {"type": "crunchbase", "external_id": "cb-190"}},
            {"attribute": "net_revenue_retention", "value": "142%",
             "confidence": 0.91, "source": {"type": "data_room", "external_id": "dr-192"}},
            {"attribute": "developer_adoption", "value": "180K GitHub stars, 12K paying teams",
             "confidence": 0.94, "source": {"type": "crm", "external_id": "crm-191"}},
        ],
        "conflicts": [],
    },
}

# Normalise lookup: lowercase, stripped
_INDEX = {k.lower().strip(): v for k, v in ENTITIES.items()}


@app.get("/entity/{name}")
async def get_entity(name: str):
    key = name.lower().strip()
    entity = _INDEX.get(key)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity '{name}' not found")
    return entity



@app.get("/health")
async def health():
    return {"status": "ok", "entities": len(ENTITIES)}
