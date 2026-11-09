"""Alpha resource catalog, the curated, generic founder templates approved for the alpha (Resource
Repository meeting, 19 Oct 2026). Single source of truth for both the content builder
(`backend/scripts/build_alpha_content.py`) and the database seed (`backend/seed.py`).

Status meaning:
  approved, visible to founders. Content owner confirms at the weekly Monday review.
  in_review, submitted, waiting for the weekly manual check; never visible to founders.

Owners come from the meeting's deliverables list. Files live in content/alpha/.
"""
from __future__ import annotations

ALPHA_REVIEW_NOTE = "Generic alpha template · owner sign-off at Monday content review"

# (slug, category, subcategory, title, description, type, owner, status, tags, company_specific)
CATALOG: list[dict] = [
    # Finance
    dict(slug="revenue-kpi-tracker", category="Finance and Compliance", sub="KPIs", title="Revenue KPI Tracker",
         desc="Monthly MRR, ARR, growth, ARPU, churn, net revenue retention, CAC, LTV and gross margin with formulas.",
         type="XLSX", owner="Sara", tags=["finance", "kpi", "reporting"]),
    dict(slug="non-revenue-kpi-tracker", category="Finance and Compliance", sub="KPIs", title="Non-Revenue KPI Tracker",
         desc="Activation, retention, NPS, burn, runway, headcount and pipeline-coverage metrics for months without revenue signal.",
         type="XLSX", owner="Sara", tags=["finance", "kpi", "operations"]),
    dict(slug="financial-projection-model", category="Finance and Compliance", sub="Planning", title="Financial Projection Template",
         desc="Assumptions sheet driving a 36-month revenue, cost, burn and runway projection. Indicative planning only.",
         type="XLSX", owner="Rishabh", tags=["finance", "fundraising", "planning"]),
    dict(slug="valuation-revenue-multiples-guide", category="Finance and Compliance", sub="Valuation", title="Revenue Multiples & Valuation Guide",
         desc="How revenue multiples, comparables and dilution work, with a worked example. Educational, not valuation advice.",
         type="DOCX", owner="Rishabh", tags=["finance", "fundraising", "valuation"]),
    # Fundraising
    dict(slug="fundraising-checklist", category="Fundraising and Investor Relations", sub="Readiness", title="Fundraising Checklist",
         desc="Stage-by-stage checklist from round planning to closing, with owners and evidence to prepare.",
         type="DOCX", owner="Sara", tags=["fundraising"]),
    dict(slug="investor-data-room-checklist", category="Fundraising and Investor Relations", sub="Data room", title="Investor Data Room Checklist",
         desc="Folder structure and document list for an investor data room, with owner and status columns.",
         type="XLSX", owner="Rishabh", tags=["fundraising", "diligence"]),
    dict(slug="due-diligence-checklist", category="Fundraising and Investor Relations", sub="Data room", title="Due Diligence Checklist",
         desc="Commercial, financial, legal, technology and people diligence questions investors typically ask.",
         type="XLSX", owner="Rishabh", tags=["fundraising", "diligence"]),
    dict(slug="pitch-deck-skeleton", category="Fundraising and Investor Relations", sub="Narrative", title="Pitch Deck Skeleton",
         desc="Slide-by-slide structure for a 12–15 slide deck, with what each slide must prove.",
         type="DOCX", owner="Roneet", tags=["fundraising", "narrative"]),
    dict(slug="fundraising-narrative-guide", category="Fundraising and Investor Relations", sub="Narrative", title="Fundraising Narrative & Story Guide",
         desc="Build the story behind the deck: problem, insight, proof, why now, and the use of funds.",
         type="DOCX", owner="Roneet", tags=["fundraising", "narrative"]),
    dict(slug="investor-outreach-tracker", category="Fundraising and Investor Relations", sub="Outreach", title="Investor Outreach Tracker & Timeline",
         desc="Track investors through intro, first meeting, partner meeting, term sheet and close, with a 12-week round timeline.",
         type="XLSX", owner="Rishabh", tags=["fundraising", "outreach"]),
    # Growth & Sales
    dict(slug="sales-pipeline-tracker", category="Growth & Sales", sub="Pipeline", title="Sales Pipeline Tracker",
         desc="Deal-level tracker with stage, value, probability and weighted pipeline, plus an automatic stage summary.",
         type="XLSX", owner="Roneet", tags=["sales", "gtm", "pipeline"]),
    dict(slug="client-data-template", category="Growth & Sales", sub="Pipeline", title="Client Data Template",
         desc="Account master for customers and prospects: segment, contacts, contract, renewal and health.",
         type="XLSX", owner="Roneet", tags=["sales", "gtm"]),
    dict(slug="outreach-templates", category="Growth & Sales", sub="Outreach", title="Email & LinkedIn Outreach Templates",
         desc="Cold, warm and follow-up templates for sales prospects and investors, with personalisation notes.",
         type="DOCX", owner="Rishabh", tags=["sales", "fundraising", "outreach"]),
    dict(slug="b2b-sales-playbook-sample", category="Growth & Sales", sub="Playbooks", title="B2B Sales Process Sample",
         desc="Sample B2B sales motion from qualification to close. Submitted for the Monday content review.",
         type="DOCX", owner="Roneet", status="in_review", tags=["sales", "gtm"]),
    # Operations
    dict(slug="project-management-framework", category="Business Operations", sub="Project management", title="Project Management Framework & Tool Stack",
         desc="A lightweight operating cadence plus a recommended tool stack (Notion, ClickUp, Asana, Motion) with reasons for each.",
         type="DOCX", owner="Roneet", tags=["operations", "tools"]),
    dict(slug="okr-planning-template", category="Business Operations", sub="People", title="OKR Planning Template",
         desc="Quarterly company and team objectives with key results, owners, confidence and weekly check-ins.",
         type="XLSX", owner="Sara", tags=["operations", "people"]),
    dict(slug="employee-onboarding-checklist", category="Business Operations", sub="People", title="Employee Onboarding Checklist",
         desc="Pre-joining, day one, week one and first-90-days onboarding tasks with owners.",
         type="XLSX", owner="Sara", tags=["operations", "people", "hiring"]),
    dict(slug="team-faq-template", category="Business Operations", sub="People", title="Internal Team FAQ Template",
         desc="A starter FAQ for policies, tools, leave, expenses and who-to-ask, to reduce repeated questions.",
         type="DOCX", owner="Roneet", tags=["operations", "people"]),
    dict(slug="inventory-tracker", category="Business Operations", sub="Trackers", title="Inventory Tracker",
         desc="SKU-level stock, reorder point and reorder flag, with stock value calculated automatically.",
         type="XLSX", owner="Sara", tags=["operations"]),
    dict(slug="expense-tracker", category="Business Operations", sub="Trackers", title="Expense Tracker",
         desc="Expense log with category, GST and approval status, plus a monthly summary by category.",
         type="XLSX", owner="Sara", tags=["operations", "finance"]),
    # Product
    dict(slug="product-roadmap-90-day", category="Product & Tech Strategy", sub="Roadmaps", title="90-Day Product Roadmap",
         desc="Thirteen-week roadmap with themes, initiatives, owners, status and success metrics.",
         type="XLSX", owner="Sara", tags=["product"]),
    dict(slug="quarterly-product-roadmap", category="Product & Tech Strategy", sub="Roadmaps", title="Quarterly Product Roadmap",
         desc="Four-quarter Now / Next / Later roadmap with outcomes, confidence and dependencies.",
         type="XLSX", owner="Sara", tags=["product"]),
    # Market
    dict(slug="icp-definition-framework", category="Market Intelligence", sub="ICP", title="ICP Definition Framework & Prompts",
         desc="Define your ideal customer profile with firmographics, pains, triggers and disqualifiers, plus AI prompts to draft it.",
         type="DOCX", owner="Roneet", tags=["market", "sales", "gtm"]),
    dict(slug="market-sizing-framework", category="Market Intelligence", sub="Market sizing", title="Market Sizing Framework & Prompts",
         desc="Top-down and bottom-up TAM / SAM / SOM method with source-quality rules and research prompts. Not a calculator.",
         type="DOCX", owner="Roneet", tags=["market", "fundraising"]),
    # Hiring / content & research
    dict(slug="job-description-template", category="People & Hiring", sub="Templates", title="Job Description Template",
         desc="A structured JD with outcomes, responsibilities, must-haves and an interview scorecard.",
         type="DOCX", owner="Sara", tags=["hiring", "people"]),
    dict(slug="research-reports-index", category="Research and Reports", sub="Reports", title="Research Reports Index",
         desc="Index of curated research reports and articles. Awaiting Sara's collation and rights check.",
         type="XLSX", owner="Sara", status="in_review", tags=["research"]),
    # Company-specific (pilot company)
    dict(slug="ev-regulatory-watchlist", category="Market Intelligence", sub="Regulatory & Policy", title="EV Regulatory Watchlist Tracker",
         desc="Published for Nimbus Mobility: track policy changes, what they mean for the business, owners and deadlines.",
         type="XLSX", owner="Sara", tags=["industry", "compliance"], company_specific=True),
]

for _item in CATALOG:
    _item.setdefault("status", "approved")
    _item.setdefault("company_specific", False)
    _item["file_name"] = f"{_item['slug']}.{_item['type'].lower()}"

# Intake → resource recommendation rules (founder intake form in the Resource Library).
PRIORITY_TO_TAGS = {
    "Fundraising": ["fundraising"],
    "Sales & GTM": ["sales", "gtm", "pipeline"],
    "Product": ["product"],
    "Finance & reporting": ["finance", "kpi", "reporting"],
    "Operations & people": ["operations", "people", "tools"],
    "Hiring": ["hiring"],
    "Market & ICP": ["market"],
}

PRIORITY_TO_CATEGORY = {
    "Fundraising": "Fundraising and Investor Relations",
    "Sales & GTM": "Growth & Sales",
    "Product": "Product & Tech Strategy",
    "Finance & reporting": "Finance and Compliance",
    "Operations & people": "Business Operations",
    "Hiring": "People & Hiring",
    "Market & ICP": "Market Intelligence",
}
