"""Build the alpha founder templates into content/alpha/.

Run from repo root:  python backend/scripts/build_alpha_content.py
Requires (dev only): openpyxl, python-docx, see backend/requirements-dev.txt

Every file is generic, India-aware and clearly labelled as an alpha template. Nothing here is
legal, tax, investment or valuation advice (a product rule).
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.alpha_catalog import CATALOG  # noqa: E402

OUT = ROOT / "content" / "alpha"
ACCENT = "CF3B25"
HEAD_FILL = PatternFill("solid", fgColor="2B2623")
NOTE_FILL = PatternFill("solid", fgColor="F7F1EC")
FOOTER = (
    "Demo Ventures Founder's Resource Portal · Alpha generic template. Adapt to your company. "
    "This is not legal, tax, investment or valuation advice, consult a qualified professional."
)
TITLES = {c["slug"]: c["title"] for c in CATALOG}


# ---------------------------------------------------------------- XLSX helpers
def _about(wb: Workbook, slug: str, how: list[str]) -> None:
    ws = wb.active
    ws.title = "About"
    ws["A1"] = TITLES[slug]
    ws["A1"].font = Font(size=16, bold=True, color=ACCENT)
    ws["A2"] = "Demo Ventures Founder's Resource Portal · alpha template"
    ws["A2"].font = Font(italic=True, color="6B625C")
    ws["A4"] = "How to use"
    ws["A4"].font = Font(bold=True)
    for i, line in enumerate(how, start=5):
        ws.cell(row=i, column=1, value=f"• {line}")
    r = 6 + len(how)
    ws.cell(row=r, column=1, value=FOOTER).font = Font(size=9, italic=True, color="6B625C")
    ws.cell(row=r, column=1).fill = NOTE_FILL
    ws.column_dimensions["A"].width = 110
    for row in ws.iter_rows(min_row=5, max_row=r):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")


def _sheet(wb: Workbook, name: str, headers: list[str], rows: list[list], widths: list[int] | None = None):
    ws = wb.create_sheet(name)
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = (widths[i - 1] if widths else max(14, len(h) + 4))
    return ws


def _list_validation(ws, col: str, options: list[str], last_row: int = 200) -> None:
    dv = DataValidation(type="list", formula1='"' + ",".join(options) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"{col}2:{col}{last_row}")


def _save_xlsx(wb: Workbook, slug: str) -> None:
    wb.calculation.fullCalcOnLoad = True  # openpyxl stores no cached values; force recalc on open
    wb.save(OUT / f"{slug}.xlsx")


MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]


def revenue_kpi_tracker() -> None:
    slug = "revenue-kpi-tracker"
    wb = Workbook()
    _about(wb, slug, [
        "Enter inputs in the yellow rows each month (Indian financial year, April–March).",
        "Calculated rows update automatically; do not overwrite formulas.",
        "Define each metric once (e.g. what counts as a 'customer') and keep it stable across months.",
        "Share the Summary rows in your monthly board / investor update.",
    ])
    ws = wb.create_sheet("KPIs")
    ws.append(["Metric", "Type", "Definition"] + MONTHS)
    inputs = [
        ("Opening customers", "Input", "Paying customers at start of month"),
        ("New customers", "Input", "Customers who started paying this month"),
        ("Churned customers", "Input", "Customers who stopped paying this month"),
        ("MRR (₹)", "Input", "Monthly recurring revenue at month end"),
        ("Expansion MRR (₹)", "Input", "Upsell / cross-sell from existing customers"),
        ("Churned MRR (₹)", "Input", "MRR lost from churn and downgrades"),
        ("Sales & marketing spend (₹)", "Input", "All acquisition cost for the month"),
        ("Cost of revenue (₹)", "Input", "Hosting, delivery, payment fees, support"),
    ]
    for name, typ, d in inputs:
        ws.append([name, typ, d] + [None] * 12)
    calcs = [
        ("Closing customers", "=({c}2+{c}3-{c}4)", "Opening + new − churned"),
        ("ARR (₹)", "={c}5*12", "MRR × 12"),
        ("MRR growth %", "=IFERROR({c}5/{p}5-1,\"\")", "vs previous month"),
        ("ARPU (₹)", "=IFERROR({c}5/{c}10,\"\")", "MRR ÷ closing customers"),
        ("Logo churn %", "=IFERROR({c}4/{c}2,\"\")", "Churned ÷ opening customers"),
        ("Net revenue retention %", "=IFERROR(({p}5+{c}6-{c}7)/{p}5,\"\")", "Monthly NRR on last month's base"),
        ("CAC (₹)", "=IFERROR({c}8/{c}3,\"\")", "S&M spend ÷ new customers"),
        ("Gross margin %", "=IFERROR(({c}5-{c}9)/{c}5,\"\")", "(MRR − cost of revenue) ÷ MRR"),
        ("LTV (₹)", "=IFERROR({c}13*{c}17/{c}14,\"\")", "ARPU × gross margin ÷ churn"),
        ("LTV : CAC", "=IFERROR({c}18/{c}16,\"\")", "Healthy SaaS benchmark is often ≥ 3"),
    ]
    for name, formula, d in calcs:
        row = [name, "Calculated", d]
        for i in range(12):
            col = get_column_letter(4 + i)
            prev = get_column_letter(3 + i) if i else None
            if prev is None and "{p}" in formula:
                row.append(None)
            else:
                row.append(formula.format(c=col, p=prev))
        ws.append(row)
    yellow = PatternFill("solid", fgColor="FFF4C2")
    for r in range(2, 10):
        for c in range(4, 16):
            ws.cell(row=r, column=c).fill = yellow
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
    for r in (12, 14, 15, 17):
        for c in range(4, 16):
            ws.cell(row=r, column=c).number_format = "0.0%"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 38
    ws.freeze_panes = "D2"
    _save_xlsx(wb, slug)


def non_revenue_kpi_tracker() -> None:
    slug = "non-revenue-kpi-tracker"
    wb = Workbook()
    _about(wb, slug, [
        "Use this alongside the Revenue KPI Tracker, or on its own before revenue starts.",
        "Pick 5–8 metrics that genuinely drive your business; delete the rest.",
        "Set a target for each and record actuals monthly. Status turns red when below target.",
    ])
    metrics = [
        ("Product", "Weekly active users", "count", 1000),
        ("Product", "Activation rate (signed up → first value)", "%", 0.4),
        ("Product", "Month-1 retention", "%", 0.35),
        ("Customer", "NPS", "score", 40),
        ("Customer", "Support tickets per 100 users", "count", 5),
        ("Finance", "Net burn (₹)", "₹", 2500000),
        ("Finance", "Cash in bank (₹)", "₹", 30000000),
        ("Finance", "Runway (months)", "months", 12),
        ("Sales", "Qualified pipeline (₹)", "₹", 10000000),
        ("Sales", "Pipeline coverage (pipeline ÷ quarterly target)", "x", 3),
        ("People", "Headcount", "count", 25),
        ("People", "Open roles", "count", 4),
    ]
    rows = []
    for i, (area, name, unit, target) in enumerate(metrics, start=2):
        rows.append([area, name, unit, "Higher is better" if "burn" not in name.lower() and "tickets" not in name.lower() else "Lower is better",
                     target, None, f'=IF(F{i}="","",IF(D{i}="Lower is better",IF(F{i}<=E{i},"On track","Below target"),IF(F{i}>=E{i},"On track","Below target")))', ""])
    ws = _sheet(wb, "Metrics", ["Area", "Metric", "Unit", "Direction", "Target", "Actual (this month)", "Status", "Comment"], rows,
                [12, 46, 10, 18, 16, 18, 16, 40])
    ws.conditional_formatting.add("G2:G100", FormulaRule(formula=['G2="Below target"'], font=Font(color="B42318", bold=True)))
    ws.conditional_formatting.add("G2:G100", FormulaRule(formula=['G2="On track"'], font=Font(color="067647", bold=True)))
    _save_xlsx(wb, slug)


def financial_projection_model() -> None:
    slug = "financial-projection-model"
    wb = Workbook()
    _about(wb, slug, [
        "Edit only the Assumptions sheet; the Projection sheet calculates 36 months.",
        "Keep assumptions defensible, note the evidence for each in the 'Basis' column.",
        "Use it for planning and fundraising conversations. Projections are indicative, not forecasts you guarantee.",
    ])
    a = _sheet(wb, "Assumptions", ["Assumption", "Value", "Basis / evidence"], [
        ["Starting MRR (₹)", 500000, "Current month MRR"],
        ["Monthly MRR growth %", 0.06, "Last 6 months average"],
        ["Gross margin %", 0.70, "Current unit economics"],
        ["Starting headcount", 15, "Current team"],
        ["New hires per month", 1, "Hiring plan"],
        ["Average monthly cost per employee (₹)", 120000, "CTC incl. benefits"],
        ["Other fixed costs per month (₹)", 400000, "Rent, tools, admin"],
        ["Marketing % of revenue", 0.15, "Planned budget"],
        ["Opening cash (₹)", 40000000, "Bank balance"],
        ["Fundraise amount (₹)", 0, "Enter planned round"],
        ["Fundraise month (1–36)", 0, "0 = none"],
    ], [42, 18, 40])
    a["B3"].number_format = a["B4"].number_format = a["B9"].number_format = "0.0%"
    p = wb.create_sheet("Projection")
    p.append(["Month", "Revenue (₹)", "Gross profit (₹)", "Headcount", "People cost (₹)", "Other fixed (₹)", "Marketing (₹)",
              "Net burn (₹)", "Fundraise (₹)", "Closing cash (₹)", "Runway (months)"])
    for m in range(1, 37):
        r = m + 1
        rev = "=Assumptions!$B$2" if m == 1 else f"=B{r-1}*(1+Assumptions!$B$3)"
        cash_prev = "Assumptions!$B$10" if m == 1 else f"J{r-1}"
        p.append([
            m, rev, f"=B{r}*Assumptions!$B$4",
            f"=Assumptions!$B$5+Assumptions!$B$6*({m}-1)", f"=D{r}*Assumptions!$B$7", "=Assumptions!$B$8",
            f"=B{r}*Assumptions!$B$9", f"=E{r}+F{r}+G{r}-C{r}", f"=IF(Assumptions!$B$12={m},Assumptions!$B$11,0)",
            f"={cash_prev}-H{r}+I{r}", f'=IF(H{r}<=0,"Profitable",IFERROR(J{r}/H{r},""))',
        ])
    for c in p[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
        c.alignment = Alignment(wrap_text=True)
    for col in "BCEFGHIJ":
        p.column_dimensions[col].width = 16
        for r in range(2, 38):
            p[f"{col}{r}"].number_format = "#,##0"
    p.column_dimensions["K"].width = 16
    p.freeze_panes = "B2"
    _save_xlsx(wb, slug)


def investor_data_room_checklist() -> None:
    slug = "investor-data-room-checklist"
    wb = Workbook()
    _about(wb, slug, [
        "Create one folder per section in your data-room tool, using the numbering below.",
        "Assign an owner to every line; mark N/A rather than deleting rows.",
        "Share access only after NDA / term-sheet stage, and log who has access.",
    ])
    sections = {
        "01 Corporate": ["Certificate of incorporation, MoA & AoA", "Shareholding pattern & cap table", "Board & shareholder resolutions (last 3 years)", "Shareholders' agreement / SHA & SSA from prior rounds", "ROC filings status"],
        "02 Financial": ["Audited financials (last 3 years)", "Monthly MIS (last 12 months)", "Financial projections & assumptions", "Bank statements (last 12 months)", "GST, TDS and income-tax filing status"],
        "03 Commercial": ["Customer list with revenue by customer", "Top customer contracts", "Sales pipeline", "Pricing & unit economics", "Market sizing & competition"],
        "04 Product & technology": ["Product roadmap", "Architecture overview", "IP ownership / assignment agreements", "Security & data-protection practices"],
        "05 People": ["Org chart", "Key employment agreements", "ESOP plan & grant register", "HR policies"],
        "06 Legal & compliance": ["Material contracts", "Litigation / notices (if any)", "Licences & registrations", "Related-party transactions"],
    }
    rows = [[sec, doc, "", "Not started", "", ""] for sec, docs in sections.items() for doc in docs]
    ws = _sheet(wb, "Checklist", ["Section", "Document", "Owner", "Status", "Link / location", "Notes"], rows, [26, 52, 16, 14, 34, 34])
    _list_validation(ws, "D", ["Not started", "In progress", "Ready", "N/A"])
    _save_xlsx(wb, slug)


def due_diligence_checklist() -> None:
    slug = "due-diligence-checklist"
    wb = Workbook()
    _about(wb, slug, [
        "Investors will ask variations of these questions. Draft answers before the round opens.",
        "Link each answer to evidence in your data room.",
        "Flag known gaps early with a remediation plan, surprises late in diligence cost trust.",
    ])
    qs = {
        "Commercial": ["Who are your top 10 customers and what share of revenue do they represent?", "What is your sales cycle length and win rate by segment?", "Why do customers churn, and what is the trend?", "How do you size the market and what is your share today?"],
        "Financial": ["Reconcile MIS revenue to audited revenue.", "What are CAC, payback and gross margin by channel?", "What is the monthly burn and runway on the current plan?", "Any outstanding statutory dues (GST, TDS, PF, ESI)?"],
        "Legal": ["Is the cap table reconciled to ROC filings?", "Are all IP assignments signed by founders, employees and contractors?", "Any pending litigation or regulatory notices?", "Are material contracts assignable on a change of control?"],
        "Technology": ["Who owns the code and infrastructure accounts?", "What security incidents have occurred and how were they handled?", "How is personal data collected, stored and deleted (DPDP readiness)?"],
        "People": ["Who are the key people and what are their retention arrangements?", "Is the ESOP pool sized for the next 18 months of hiring?", "Attrition in the last 12 months by function?"],
    }
    rows = [[area, q, "", "", "Open"] for area, items in qs.items() for q in items]
    ws = _sheet(wb, "Questions", ["Area", "Question", "Draft answer", "Evidence (data-room ref)", "Status"], rows, [14, 64, 46, 26, 12])
    _list_validation(ws, "E", ["Open", "Drafted", "Final", "Gap flagged"])
    _save_xlsx(wb, slug)


def investor_outreach_tracker() -> None:
    slug = "investor-outreach-tracker"
    wb = Workbook()
    _about(wb, slug, [
        "Pipeline: one row per investor. Keep 'Next step' and 'Date' always filled.",
        "Timeline: a typical 12-week round plan. Adjust week numbers to your round.",
        "Ask Demo Ventures for warm introductions instead of cold-emailing partners where possible.",
    ])
    stages = ["Target", "Intro requested", "First meeting", "Partner meeting", "Diligence", "Term sheet", "Closed", "Passed"]
    ws = _sheet(wb, "Pipeline", ["Investor", "Fund type", "Stage focus", "Partner / contact", "Intro via", "Stage", "Last contact", "Next step", "Next step date", "Notes"],
                [["Example Fund (replace)", "VC", "Series A", "", "Demo Ventures", "Target", None, "Request intro", None, ""]],
                [26, 12, 14, 22, 14, 16, 14, 28, 14, 36])
    _list_validation(ws, "F", stages)
    _list_validation(ws, "B", ["VC", "CVC", "Angel", "Family office", "Venture debt"])
    s = wb.create_sheet("Stage summary")
    s.append(["Stage", "Count"])
    for i, st in enumerate(stages, start=2):
        s.append([st, f'=COUNTIF(Pipeline!F:F,A{i})'])
    s.column_dimensions["A"].width = 20
    _sheet(wb, "Timeline", ["Week", "Workstream", "Milestone"], [
        [1, "Preparation", "Round size, use of funds and target investor list agreed"],
        [2, "Preparation", "Deck, narrative and financial model ready; data room 80% ready"],
        [3, "Outreach", "Warm intros requested for first batch of investors"],
        [4, "Outreach", "First meetings in batches so feedback can be incorporated"],
        [6, "Meetings", "Partner meetings with the most engaged funds"],
        [8, "Diligence", "Data room opened to shortlisted investors"],
        [10, "Term sheet", "Term sheets received and compared with advisers"],
        [12, "Closing", "Definitive documents, approvals and funds received"],
    ], [8, 16, 70])
    _save_xlsx(wb, slug)


def sales_pipeline_tracker() -> None:
    slug = "sales-pipeline-tracker"
    wb = Workbook()
    _about(wb, slug, [
        "One row per opportunity. Stage probability fills automatically; override only with a reason.",
        "Weighted value = deal value × probability. Review the Summary sheet in your weekly sales meeting.",
        "Every open deal needs a dated next step, deals without one are usually stalled.",
    ])
    stages = {"Lead": 0.05, "Qualified": 0.15, "Discovery": 0.25, "Proposal": 0.5, "Negotiation": 0.75, "Won": 1.0, "Lost": 0.0}
    rows = []
    examples = [("Sample Account A", "Mid-market", "Qualified", 800000), ("Sample Account B", "Enterprise", "Proposal", 2400000), ("Sample Account C", "SMB", "Lead", 150000)]
    for i, (acct, seg, st, val) in enumerate(examples, start=2):
        rows.append([acct, seg, "", st, val, f'=IFERROR(VLOOKUP(D{i},Stages!A:B,2,FALSE),"")', f"=IFERROR(E{i}*F{i},0)", None, "", None, ""])
    for i in range(5, 101):
        rows.append(["", "", "", "", None, f'=IF(D{i}="","",IFERROR(VLOOKUP(D{i},Stages!A:B,2,FALSE),""))', f'=IF(E{i}="","",IFERROR(E{i}*F{i},0))', None, "", None, ""])
    ws = _sheet(wb, "Pipeline", ["Account", "Segment", "Owner", "Stage", "Deal value (₹)", "Probability", "Weighted value (₹)", "Expected close", "Next step", "Next step date", "Notes"],
                rows, [24, 14, 14, 14, 16, 12, 18, 14, 30, 14, 30])
    _list_validation(ws, "D", list(stages), 101)
    _list_validation(ws, "B", ["SMB", "Mid-market", "Enterprise", "Government"], 101)
    for r in range(2, 102):
        ws[f"F{r}"].number_format = "0%"
        ws[f"E{r}"].number_format = ws[f"G{r}"].number_format = "#,##0"
    st = wb.create_sheet("Stages")
    st.append(["Stage", "Default probability"])
    for k, v in stages.items():
        st.append([k, v])
    sm = wb.create_sheet("Summary")
    sm.append(["Stage", "Deals", "Value (₹)", "Weighted (₹)"])
    for i, k in enumerate(stages, start=2):
        sm.append([k, f"=COUNTIF(Pipeline!D:D,A{i})", f"=SUMIF(Pipeline!D:D,A{i},Pipeline!E:E)", f"=SUMIF(Pipeline!D:D,A{i},Pipeline!G:G)"])
    n = len(stages) + 2
    sm.append(["Total open (excl. Won/Lost)", f"=SUM(B2:B{n-1})-B{n-2}-B{n-1}", f"=SUM(C2:C{n-1})-C{n-2}-C{n-1}", f"=SUM(D2:D{n-1})-D{n-2}-D{n-1}"])
    for c in sm[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
    for col in "ABCD":
        sm.column_dimensions[col].width = 26 if col == "A" else 16
    wb.move_sheet("Summary", offset=-2)
    _save_xlsx(wb, slug)


def client_data_template() -> None:
    slug = "client-data-template"
    wb = Workbook()
    _about(wb, slug, [
        "Single source of truth for customers and prospects. Keep personal data to what you need (DPDP Act).",
        "Health: Green = renewing, Amber = risk, Red = likely churn.",
    ])
    ws = _sheet(wb, "Accounts", ["Account", "Segment", "Industry", "City", "Primary contact role", "Contract start", "Renewal date", "ARR (₹)", "Health", "Account owner", "Notes"],
                [["Sample Account A", "Mid-market", "Logistics", "Bengaluru", "Head of Operations", None, None, 800000, "Green", "", ""]],
                [22, 14, 16, 14, 22, 14, 14, 14, 10, 16, 30])
    _list_validation(ws, "I", ["Green", "Amber", "Red"])
    _save_xlsx(wb, slug)


def okr_planning_template() -> None:
    slug = "okr-planning-template"
    wb = Workbook()
    _about(wb, slug, [
        "3 objectives per quarter at company level, at most 3–4 key results each.",
        "Key results are measurable outcomes, not tasks. Score progress weekly (0–100%).",
        "Confidence: High / Medium / Low, discuss Low items first in the weekly review.",
    ])
    rows = []
    for i, (obj, kr, start, target) in enumerate([
        ("Grow revenue efficiently", "Increase MRR", 500000, 750000),
        ("Grow revenue efficiently", "Reduce CAC payback (months)", 14, 10),
        ("Build a reliable product", "Reduce P1 incidents per month", 6, 1),
    ], start=2):
        rows.append(["Q1", obj, kr, "", start, target, None, f'=IF(G{i}="","",MAX(0,MIN(1,(G{i}-E{i})/(F{i}-E{i}))))', "Medium", ""])
    ws = _sheet(wb, "OKRs", ["Quarter", "Objective", "Key result", "Owner", "Start", "Target", "Current", "Progress", "Confidence", "Notes"], rows,
                [8, 30, 34, 14, 10, 10, 10, 10, 12, 30])
    for r in range(2, 60):
        ws[f"H{r}"].number_format = "0%"
    _list_validation(ws, "I", ["High", "Medium", "Low"])
    _save_xlsx(wb, slug)


def employee_onboarding_checklist() -> None:
    slug = "employee-onboarding-checklist"
    wb = Workbook()
    _about(wb, slug, ["Copy the Checklist sheet for each new joiner.", "The manager owns the outcome; People/Ops owns the logistics."])
    tasks = [
        ("Pre-joining", "Offer letter and appointment letter signed", "People"), ("Pre-joining", "Laptop, email and tool accounts ready", "Ops"),
        ("Pre-joining", "Buddy assigned", "Manager"), ("Day 1", "Welcome and company story from a founder", "Founder"),
        ("Day 1", "Policies acknowledged (code of conduct, POSH, IT, leave)", "People"), ("Day 1", "PF / ESI / payroll details collected", "People"),
        ("Week 1", "Role outcomes for first 90 days agreed in writing", "Manager"), ("Week 1", "Meet key cross-functional partners", "Manager"),
        ("Day 30", "Check-in: what is working, what is unclear", "Manager"), ("Day 60", "First feedback conversation", "Manager"),
        ("Day 90", "Probation / 90-day review against agreed outcomes", "Manager"),
    ]
    ws = _sheet(wb, "Checklist", ["Phase", "Task", "Owner", "Due date", "Done?", "Notes"], [[p, t, o, None, "No", ""] for p, t, o in tasks], [14, 56, 12, 12, 8, 30])
    _list_validation(ws, "E", ["Yes", "No", "N/A"])
    _save_xlsx(wb, slug)


def inventory_tracker() -> None:
    slug = "inventory-tracker"
    wb = Workbook()
    _about(wb, slug, ["Update stock-in and stock-out weekly. 'Reorder?' flags items at or below the reorder point."])
    rows = []
    for i in range(2, 52):
        sample = i == 2
        rows.append(["SKU-001" if sample else "", "Sample item" if sample else "", "pcs" if sample else "", 100 if sample else None, 20 if sample else None, 5 if sample else None,
                     30 if sample else None, 250 if sample else None,
                     f'=IF(A{i}="","",D{i}+E{i}-F{i})', f'=IF(A{i}="","",IF(I{i}<=G{i},"Reorder","OK"))', f'=IF(A{i}="","",I{i}*H{i})'])
    ws = _sheet(wb, "Stock", ["SKU", "Item", "Unit", "Opening stock", "Stock in", "Stock out", "Reorder point", "Unit cost (₹)", "Closing stock", "Reorder?", "Stock value (₹)"], rows,
                [12, 26, 8, 14, 10, 10, 14, 14, 14, 10, 16])
    ws.conditional_formatting.add("J2:J200", FormulaRule(formula=['J2="Reorder"'], font=Font(color="B42318", bold=True)))
    _save_xlsx(wb, slug)


def expense_tracker() -> None:
    slug = "expense-tracker"
    wb = Workbook()
    cats = ["Salaries", "Rent", "Software & tools", "Marketing", "Travel", "Professional fees", "Office & admin", "Other"]
    _about(wb, slug, ["Log every expense with a receipt reference. Summary totals by category and month.", "GST input credit eligibility depends on your situation, confirm with your CA."])
    ws = _sheet(wb, "Expenses", ["Date", "Month (YYYY-MM)", "Vendor", "Category", "Amount excl. GST (₹)", "GST (₹)", "Total (₹)", "Paid by", "Approved?", "Receipt ref"],
                [[None, f'=IF(A{i}="","",TEXT(A{i},"yyyy-mm"))', "", "", None, None, f'=IF(E{i}="","",E{i}+N(F{i}))', "", "Pending", ""] for i in range(2, 202)],
                [12, 14, 22, 18, 18, 12, 14, 14, 12, 14])
    _list_validation(ws, "D", cats, 202)
    _list_validation(ws, "I", ["Pending", "Approved", "Rejected"], 202)
    s = wb.create_sheet("Summary")
    s.append(["Category", "Total (₹)"])
    for i, c in enumerate(cats, start=2):
        s.append([c, f'=SUMIF(Expenses!D:D,A{i},Expenses!G:G)'])
    s.append(["Total", f"=SUM(B2:B{len(cats)+1})"])
    s.column_dimensions["A"].width = 22
    s.column_dimensions["B"].width = 16
    _save_xlsx(wb, slug)


def product_roadmap_90_day() -> None:
    slug = "product-roadmap-90-day"
    wb = Workbook()
    _about(wb, slug, ["Plan in themes (outcomes), then initiatives. Keep 20% capacity unplanned for learning and fixes.",
                      "Review fortnightly; move items rather than silently letting dates slip."])
    ws = _sheet(wb, "Roadmap", ["Theme / outcome", "Initiative", "Owner", "Start week", "End week", "Status", "Success metric", "Dependencies"]
                + [f"W{w}" for w in range(1, 14)],
                [["Improve activation", "Guided onboarding", "", 1, 4, "Planned", "Activation rate 30% → 40%", ""]] +
                [[""] * 8 for _ in range(20)], [22, 26, 12, 10, 10, 12, 26, 18] + [5] * 13)
    _list_validation(ws, "F", ["Planned", "In progress", "Done", "At risk", "Dropped"], 30)
    for r in range(2, 23):
        for w in range(1, 14):
            col = get_column_letter(8 + w)
            ws[f"{col}{r}"] = f'=IF(AND(ISNUMBER($D{r}),{w}>=$D{r},{w}<=$E{r}),"■","")'
            ws[f"{col}{r}"].font = Font(color=ACCENT)
            ws[f"{col}{r}"].alignment = Alignment(horizontal="center")
    _save_xlsx(wb, slug)


def quarterly_product_roadmap() -> None:
    slug = "quarterly-product-roadmap"
    wb = Workbook()
    _about(wb, slug, ["Now = committed this quarter; Next = likely next quarter; Later = direction, not commitment.",
                      "Share Now/Next with customers and investors; keep Later internal."])
    ws = _sheet(wb, "Roadmap", ["Horizon", "Quarter", "Outcome", "Key initiatives", "Confidence", "Dependencies / risks", "Owner"],
                [["Now", "Q1", "", "", "High", "", ""], ["Next", "Q2", "", "", "Medium", "", ""], ["Later", "Q3", "", "", "Low", "", ""], ["Later", "Q4", "", "", "Low", "", ""]],
                [10, 10, 30, 40, 12, 30, 14])
    _list_validation(ws, "A", ["Now", "Next", "Later"])
    _list_validation(ws, "E", ["High", "Medium", "Low"])
    _save_xlsx(wb, slug)


def research_reports_index() -> None:
    slug = "research-reports-index"
    wb = Workbook()
    _about(wb, slug, ["Index of curated reports. Every row needs a source URL and a confirmed redistribution/linking right before approval."])
    ws = _sheet(wb, "Index", ["Title", "Publisher", "Year", "Sector", "Source URL", "Rights checked?", "Summary (2 lines)", "Curated by"], [], [36, 20, 8, 16, 40, 14, 50, 14])
    _list_validation(ws, "F", ["Yes", "No"])
    _save_xlsx(wb, slug)


def ev_regulatory_watchlist() -> None:
    slug = "ev-regulatory-watchlist"
    wb = Workbook()
    _about(wb, slug, [
        "Track policy and regulatory changes that affect your business, from official sources only (ministry, regulator or gazette).",
        "For each change: what it means for us, who owns the response, and the deadline.",
        "Interpretation of any rule should be confirmed with your legal / compliance adviser.",
    ])
    ws = _sheet(wb, "Watchlist", ["Date noted", "Source (official)", "Source URL", "Area", "Summary of change", "Impact on us", "Impact level", "Owner", "Action & deadline", "Status"],
                [[None, "", "", "", "", "", "Medium", "", "", "Open"]],
                [12, 22, 32, 16, 40, 36, 12, 14, 30, 12])
    _list_validation(ws, "D", ["Battery & swapping", "Charging infrastructure", "Incentives & subsidies", "Safety & certification", "Data & connectivity", "Tax & GST", "Other"])
    _list_validation(ws, "G", ["High", "Medium", "Low"])
    _list_validation(ws, "J", ["Open", "In progress", "Closed"])
    _save_xlsx(wb, slug)


# ---------------------------------------------------------------- DOCX helpers
def _doc(slug: str, intro: str) -> Document:
    d = Document()
    st = d.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(11)
    h = d.add_heading(TITLES[slug], level=0)
    for run in h.runs:
        run.font.color.rgb = RGBColor.from_string(ACCENT)
    p = d.add_paragraph("Demo Ventures Founder's Resource Portal · alpha template")
    p.runs[0].italic = True
    d.add_paragraph(intro)
    return d


def _section(d: Document, heading: str, bullets: list[str] | None = None, text: str | None = None) -> None:
    d.add_heading(heading, level=1)
    if text:
        d.add_paragraph(text)
    for b in bullets or []:
        d.add_paragraph(b, style="List Bullet")


def _table(d: Document, headers: list[str], rows: list[list[str]]) -> None:
    t = d.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        t.rows[0].cells[i].text = h
    for r in rows:
        cells = t.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = v


def _save_doc(d: Document, slug: str) -> None:
    d.add_paragraph()
    p = d.add_paragraph(FOOTER)
    p.runs[0].italic = True
    p.runs[0].font.size = Pt(8)
    d.save(OUT / f"{slug}.docx")


def valuation_guide() -> None:
    slug = "valuation-revenue-multiples-guide"
    d = _doc(slug, "Investors price early-stage companies by judgement, comparables and the round's supply and demand. "
                   "This guide explains the vocabulary so you can follow the conversation, it does not tell you what your company is worth.")
    _section(d, "Key terms", [
        "Pre-money valuation: value of the company before new money comes in.",
        "Post-money valuation: pre-money + new investment.",
        "Dilution: the share of the company existing holders give up = new investment ÷ post-money.",
        "Revenue multiple: valuation ÷ annual revenue (usually ARR for recurring businesses).",
        "Option pool top-up: new ESOP shares created before the round, which dilute existing holders rather than new investors.",
    ])
    _section(d, "What moves a revenue multiple", [
        "Growth rate, usually the strongest driver.", "Revenue quality, recurring, contracted, diversified revenue earns higher multiples.",
        "Gross margin, software-like margins earn more than services-heavy margins.", "Retention, net revenue retention above 100% signals compounding.",
        "Market size and competitive position.", "Prevailing market conditions for your sector and stage.",
    ])
    _section(d, "Worked example (illustrative numbers only)")
    _table(d, ["Item", "Value"], [["ARR", "₹10 crore"], ["Multiple discussed", "8x ARR"], ["Implied pre-money", "₹80 crore"],
                                  ["Investment", "₹20 crore"], ["Post-money", "₹100 crore"], ["New investor stake", "20%"], ["Founder stake before (60%) → after", "48%"]])
    _section(d, "Before you negotiate", [
        "Collect 3–5 genuinely comparable recent rounds (stage, sector, growth) from reliable sources, and note the source of each.",
        "Model dilution across the next two rounds, not just this one.", "Understand terms beyond price: liquidation preference, anti-dilution, board seats and vetoes.",
        "Ask Demo Ventures to review the term sheet with you and involve your legal adviser before signing.",
    ])
    _save_doc(d, slug)


def fundraising_checklist() -> None:
    slug = "fundraising-checklist"
    d = _doc(slug, "Use this checklist to run a structured round. Tick items off in order, most rounds stall because preparation was skipped.")
    for stage, items in {
        "1. Decide the round": ["Why raise now, and what milestones will this money achieve?", "Round size = 18–24 months of runway to those milestones, plus buffer.", "Instrument (equity, CCPS, convertible note, iSAFE) discussed with advisers.", "Target investor profile and list (stage, sector, cheque size)."],
        "2. Prepare materials": ["Pitch deck and a 1-page teaser.", "Financial model with clear assumptions.", "Data room 80% ready before the first meeting.", "Answers drafted for the top 20 diligence questions."],
        "3. Run the process": ["Warm introductions via Demo Ventures and your network, in batches.", "Tight meeting window (4–6 weeks) to create momentum.", "Track every investor in the Investor Outreach Tracker.", "Update the deck after each batch of feedback."],
        "4. Term sheet to close": ["Compare term sheets on economics and control, not just price.", "Legal adviser engaged for definitive documents.", "Board and shareholder approvals; regulatory filings (e.g. FEMA reporting for foreign investment, ROC filings) handled with your CA/CS.", "Plan the announcement and first investor update."],
    }.items():
        _section(d, stage, ["☐ " + i for i in items])
    _save_doc(d, slug)


def pitch_deck_skeleton() -> None:
    slug = "pitch-deck-skeleton"
    d = _doc(slug, "A 12–15 slide structure. Each slide should prove one thing; the 'Must prove' column is what the investor is checking.")
    _table(d, ["#", "Slide", "Must prove"], [
        ["1", "Title & one-line positioning", "What you do, for whom, in one sentence"], ["2", "Problem", "The pain is real, frequent and expensive"],
        ["3", "Insight / why now", "You see something others have missed, and timing is right"], ["4", "Solution & product", "How you solve it, show, don't tell"],
        ["5", "Customers & traction", "People pay and keep paying; trend, not snapshot"], ["6", "Business model & unit economics", "Each customer is worth more than they cost to acquire"],
        ["7", "Market", "The opportunity is large enough, bottom-up sizing preferred"], ["8", "Go-to-market", "You know how to reach customers repeatably"],
        ["9", "Competition", "Honest landscape and why you win"], ["10", "Team", "This team is right for this problem"],
        ["11", "Financials", "Plan and key assumptions"], ["12", "The ask & use of funds", "How much, for what milestones, over what time"],
        ["13", "Appendix", "Detail you may need in Q&A"],
    ])
    _section(d, "Design rules", ["One message per slide; the headline states the conclusion.", "Real numbers with dates and definitions.", "Readable on a phone, investors often read decks on mobile."])
    _save_doc(d, slug)


def narrative_guide() -> None:
    slug = "fundraising-narrative-guide"
    d = _doc(slug, "Your narrative is the argument your deck makes. Write it as a page of prose first; the slides follow.")
    _section(d, "The five-part story", [
        "Problem, who suffers, how often, and what it costs them today.", "Insight, what you understand that incumbents do not.",
        "Proof, traction, retention, customer quotes, pilots.", "Why now, technology, regulation or behaviour shift that opens the window.",
        "Ambition & use of funds, what this round unlocks and what the company becomes.",
    ])
    _section(d, "Exercises", [
        "Write your story in 100 words, then in 30 words. If the 30-word version is weak, the deck will be too.",
        "List the three objections investors raise most often and answer each with evidence.",
        "Ask two founders outside your sector to repeat your story back to you after hearing it once.",
    ])
    _save_doc(d, slug)


def outreach_templates() -> None:
    slug = "outreach-templates"
    d = _doc(slug, "Short, specific and personal beats long and generic. Replace everything in [brackets]; never send a template unedited.")
    _section(d, "Sales, cold email")
    d.add_paragraph("Subject: [Specific outcome] for [their company]\n\nHi [Name],\n\nI noticed [specific trigger, new plant, hiring, regulation]. "
                    "Teams like [similar customer] use [product] to [quantified outcome].\n\nWould a 20-minute call next [day] be useful to see if this applies to [their company]?\n\n[Your name]")
    _section(d, "Sales, follow-up (after 4–5 working days)")
    d.add_paragraph("Hi [Name], following up with one thing that may help: [short case study / data point]. Happy to share more, or I'll leave it here if the timing isn't right.")
    _section(d, "LinkedIn, connection note (under 300 characters)")
    d.add_paragraph("Hi [Name], saw your post on [topic]. We're working on [problem] for [segment] and I'd value your view. Open to connecting?")
    _section(d, "Investor, warm introduction request (to Demo Ventures or a mutual contact)")
    d.add_paragraph("Hi [Connector], we're raising [amount] [round] to [milestone]. [Investor] backs [relevant portfolio company], so I think there's a fit. "
                    "Below is a forwardable 4-line blurb and our teaser. Would you be comfortable introducing us?")
    _section(d, "Investor, forwardable blurb")
    d.add_paragraph("[Company] helps [customer] [outcome]. [Traction in one line]. Raising [amount] to [milestone]. Team: [one-line credibility].")
    _section(d, "Rules", ["Personalise the first line to the person, not the company.", "One clear ask per message.", "Respect opt-outs and keep a record of consent where personal data is involved."])
    _save_doc(d, slug)


def b2b_sales_playbook() -> None:
    slug = "b2b-sales-playbook-sample"
    d = _doc(slug, "Sample B2B sales motion for early-stage teams selling to businesses. Submitted for review.")
    _table(d, ["Stage", "Exit criteria", "Typical activities"], [
        ["Lead", "Matches ICP", "Research, first outreach"], ["Qualified", "Pain, budget owner and timeline confirmed", "Discovery call"],
        ["Discovery", "Success criteria agreed in writing", "Demo, stakeholder mapping"], ["Proposal", "Pricing and scope shared", "Proposal, business case"],
        ["Negotiation", "Commercial and legal terms agreed", "Procurement, security review"], ["Won", "Signed contract", "Kick-off and onboarding"],
    ])
    _save_doc(d, slug)


def pm_framework() -> None:
    slug = "project-management-framework"
    d = _doc(slug, "A lightweight operating system for a 10–100 person startup: a planning cadence, a way to track work, and a small, deliberate tool stack.")
    _section(d, "Operating cadence", [
        "Quarterly: set OKRs (see the OKR Planning Template) and a 90-day product roadmap.", "Weekly: 30-minute leadership review, metrics, OKR confidence, blockers.",
        "Weekly per team: plan the week from the roadmap; demo what shipped.", "Monthly: founder update to the team and to investors.",
    ])
    _section(d, "How to track work", [
        "One system of record for tasks, avoid tasks living in chat.", "Every task has one owner and a due date.",
        "Use three statuses to start (To do, Doing, Done); add more only when needed.", "Projects link to the objective they serve.",
    ])
    _section(d, "Recommended tool stack (pick one per job)")
    _table(d, ["Tool", "Best for", "Why we recommend it", "Watch out for"], [
        ["Notion", "Docs, wiki, light project tracking", "Flexible; one place for policies, meeting notes and simple boards; generous free tier", "Gets messy without an owner and a page structure"],
        ["ClickUp", "Teams wanting docs + tasks + dashboards in one", "Highly configurable views and reporting; good value", "Many features, configure the minimum and stop"],
        ["Asana", "Cross-functional project management", "Clean, reliable, strong timelines and workload views", "Paid tiers needed for advanced features"],
        ["Motion", "Founders and small teams drowning in calendars", "Auto-schedules tasks into your calendar around meetings", "Works best for individuals and small teams; less suited to complex projects"],
    ])
    d.add_paragraph("Suggested default: Notion for documentation plus one of ClickUp or Asana for task tracking. Add Motion for individual calendar planning if useful. "
                    "Tool recommendations are for guidance only; Demo Ventures has no commercial relationship with these vendors.")
    _save_doc(d, slug)


def team_faq() -> None:
    slug = "team-faq-template"
    d = _doc(slug, "Replace the sample answers with your policies. Keep the FAQ in your wiki and update it whenever a question is asked twice.")
    for q, a in [("Who do I ask about…?", "[Table of topics → owner]"), ("How do I apply for leave?", "[Process, tool, notice period]"),
                 ("How do I claim expenses?", "[Policy, limits, receipts, approval]"), ("Which tools do we use for what?", "[Docs → Notion; tasks → …]"),
                 ("What are our working hours and meeting norms?", "[Core hours, no-meeting blocks]"), ("How are performance reviews run?", "[Cadence and process]"),
                 ("Where are company policies?", "[Link to POSH, code of conduct, IT and data policies]")]:
        _section(d, q, text=a)
    _save_doc(d, slug)


def icp_framework() -> None:
    slug = "icp-definition-framework"
    d = _doc(slug, "Your ideal customer profile (ICP) describes the customers who get the most value fastest and stay longest. "
                   "Base it on your best existing customers, not on who you wish would buy.")
    _section(d, "Step 1, list your best 10 customers", text="Best = fastest to close, highest retention, highest expansion, lowest support cost.")
    _section(d, "Step 2, find the pattern")
    _table(d, ["Dimension", "Questions", "Your answer"], [
        ["Firmographics", "Industry, size (revenue / employees), geography, growth stage", ""],
        ["Trigger events", "What happened just before they bought? (funding, regulation, new leader, expansion)", ""],
        ["Pain", "What problem were they solving and what did it cost them?", ""],
        ["Buyer & users", "Who signs, who uses, who can block?", ""], ["Current alternative", "What were they doing before you?", ""],
        ["Disqualifiers", "Which signals predict a poor fit or churn?", ""],
    ])
    _section(d, "Step 3, write it in one paragraph", text="'[Industry] companies with [size] in [geography] who have just [trigger] and struggle with [pain]. "
                                                             "The buyer is [role]; they currently use [alternative].'")
    _section(d, "AI prompts to draft and test your ICP", [
        "\"Here are anonymised notes on our 10 best and 5 worst customers: [paste]. Identify the patterns that separate them and draft an ICP.\"",
        "\"Act as a sceptical [buyer role] at a [industry] company. Which parts of this ICP description would not apply to you? [paste ICP]\"",
        "\"List 15 observable trigger events that would indicate a company matching this ICP is ready to buy now: [paste ICP]\"",
    ])
    d.add_paragraph("Do not paste personal data or confidential customer information into external AI tools.")
    _save_doc(d, slug)


def market_sizing_framework() -> None:
    slug = "market-sizing-framework"
    d = _doc(slug, "Market sizing needs industry-specific data, so this is a method plus prompts, not an automated calculator. "
                   "Investors trust a transparent bottom-up estimate more than a large top-down number.")
    _section(d, "Definitions", ["TAM, total annual spend on the problem you solve.", "SAM, the part of TAM your product and go-to-market can serve today.",
                                "SOM, the share of SAM you can realistically win in 3–5 years."])
    _section(d, "Bottom-up method (preferred)")
    _table(d, ["Step", "Example structure"], [["Count target customers", "Number of [ICP] companies in [geography] (source: …)"],
                                              ["Annual value per customer", "Your price × units per customer"], ["SAM", "Count × annual value"],
                                              ["SOM", "SAM × realistic share based on sales capacity"]])
    _section(d, "Source-quality rules", ["Prefer government statistics, regulators, industry bodies and company filings.", "Record the source, year and link for every number.",
                                         "Show your arithmetic; round sensibly.", "Cross-check bottom-up against one top-down estimate."])
    _section(d, "Research prompts", [
        "\"List official and industry sources that publish the number of [type of business] in India by state, with links.\"",
        "\"Build a bottom-up SAM model for [product] sold to [ICP] in [geography]. Show each assumption separately so I can verify it.\"",
        "\"What are the strongest objections an investor would raise about this market-size estimate? [paste]\"",
    ])
    d.add_paragraph("Verify every AI-generated figure against a primary source before using it.")
    _save_doc(d, slug)


def jd_template() -> None:
    slug = "job-description-template"
    d = _doc(slug, "A good JD describes outcomes, not just duties, and doubles as the interview scorecard.")
    for h, t in [("Role and team", "[Title] · reports to [role] · [location / hybrid]"), ("Why this role exists", "[The business problem this hire solves]"),
                 ("Outcomes in the first 12 months", "1. …  2. …  3. …"), ("Responsibilities", "[5–7 bullets]"),
                 ("Must-have experience", "[Only what is genuinely required]"), ("Nice to have", "[Kept short to avoid deterring good candidates]"),
                 ("What we offer", "[Compensation range, ESOP, benefits, growth]")]:
        _section(d, h, text=t)
    _section(d, "Interview scorecard")
    _table(d, ["Competency", "Evidence to look for", "Score 1–4"], [["Role outcome 1", "", ""], ["Role outcome 2", "", ""], ["Values / ways of working", "", ""]])
    _save_doc(d, slug)


BUILDERS = {
    "revenue-kpi-tracker": revenue_kpi_tracker, "non-revenue-kpi-tracker": non_revenue_kpi_tracker,
    "financial-projection-model": financial_projection_model, "valuation-revenue-multiples-guide": valuation_guide,
    "fundraising-checklist": fundraising_checklist, "investor-data-room-checklist": investor_data_room_checklist,
    "due-diligence-checklist": due_diligence_checklist, "pitch-deck-skeleton": pitch_deck_skeleton,
    "fundraising-narrative-guide": narrative_guide, "investor-outreach-tracker": investor_outreach_tracker,
    "sales-pipeline-tracker": sales_pipeline_tracker, "client-data-template": client_data_template,
    "outreach-templates": outreach_templates, "b2b-sales-playbook-sample": b2b_sales_playbook,
    "project-management-framework": pm_framework, "okr-planning-template": okr_planning_template,
    "employee-onboarding-checklist": employee_onboarding_checklist, "team-faq-template": team_faq,
    "inventory-tracker": inventory_tracker, "expense-tracker": expense_tracker,
    "product-roadmap-90-day": product_roadmap_90_day, "quarterly-product-roadmap": quarterly_product_roadmap,
    "icp-definition-framework": icp_framework, "market-sizing-framework": market_sizing_framework,
    "job-description-template": jd_template, "research-reports-index": research_reports_index,
    "ev-regulatory-watchlist": ev_regulatory_watchlist,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = [c["slug"] for c in CATALOG if c["slug"] not in BUILDERS]
    if missing:
        raise SystemExit(f"No builder for: {missing}")
    for c in CATALOG:
        BUILDERS[c["slug"]]()
    print(f"Built {len(CATALOG)} files in {OUT}")


if __name__ == "__main__":
    main()
