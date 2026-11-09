"""Starter content for the 100-Day Playbook course (LMS), chapter by chapter.

One chapter per playbook task, in the four playbook phases, each with two short lessons: why it matters and
what good looks like, then doing it with the linked Resource Library template. It is Demo Ventures starter
content: the content team edits, extends or replaces it in the workspace (Playbook course). It is loaded only
into an empty course (ensure_starter), so it never overwrites edits. General guidance only: legal, tax and
compliance points must be checked with the company's own advisors.
"""
from __future__ import annotations

ADVISOR_NOTE = "This is general guidance, not legal, tax or compliance advice. Check the specifics with your own advisors."

# (phase, chapter title, summary, [(lesson title, minutes, body, resource slug or None)])
CHAPTERS = [
    (1, "Onboarding essentials", "Get every new person productive in their first two weeks.", [
        ("Why onboarding decides retention", 5,
         "The first two weeks shape whether a new hire stays. A clear start cuts the time to their first useful work and the "
         "number of questions they have to chase.\n\nGood onboarding has three parts:\n- Before day one: laptop, accounts and a named buddy ready.\n"
         "- Week one: the company story, how decisions are made, and one small task they can finish.\n"
         "- Week two: their 30-60-90 day goals agreed with their manager.", None),
        ("Do it: set up your onboarding checklist", 10,
         "Open the Employee Onboarding Checklist, copy it for your company and fill in the owner for each line.\n\n"
         "- Assign a buddy for every new joiner.\n- Book a 15-minute check-in at the end of week one and week four.\n"
         "- Ask each new joiner what was missing, and add it to the checklist.", "employee-onboarding-checklist"),
    ]),
    (1, "Founder alignment", "Agree how the founders divide work and make decisions.", [
        ("Why founders write things down", 5,
         "Most early co-founder friction comes from unspoken assumptions about roles, decisions and time. Writing them down "
         "while things are calm makes the hard conversations easier later.\n\nCover:\n- Who owns which areas, and who has the final say.\n"
         "- How you resolve a disagreement.\n- Time commitment and what happens if it changes.\n- How you review this note (every six months).", None),
        ("Do it: a one-page alignment note", 15,
         "Each founder writes their answers separately, then you compare and agree one version.\n\n"
         "- Keep it to one page.\n- Share the agreed version with your Demo Ventures relationship manager.\n- Anything about equity or vesting "
         "goes to your lawyer to put into the right documents.\n\n" + ADVISOR_NOTE, None),
    ]),
    (1, "Operating cadence", "Set the weekly and monthly rhythm the team runs on.", [
        ("A simple rhythm beats more meetings", 5,
         "A fixed rhythm means problems surface early and fewer ad-hoc meetings.\n\nA starting point:\n- Weekly: 30-minute leadership check-in on numbers, blockers and decisions.\n"
         "- Monthly: review of goals, cash and hiring.\n- Quarterly: plan the next quarter's priorities.", None),
        ("Do it: put your cadence in place", 10,
         "Use the Project Management Framework to agree owners, meeting formats and where decisions are written down.\n\n"
         "- Put the meetings in everyone's calendar for the next quarter.\n- Keep a single decision log the whole team can read.", "project-management-framework"),
    ]),
    (2, "Board reporting and KPIs", "Report the few numbers that show how the company is doing.", [
        ("Pick the numbers that matter", 6,
         "Investors and the board want the same handful of numbers every month, in the same format.\n\n"
         "- Revenue (or the closest leading indicator), growth and gross margin.\n- Burn and runway in months.\n- Two or three operating numbers specific to your business.\n"
         "Keep definitions fixed so month-to-month comparisons are honest.", None),
        ("Do it: set up your KPI tracker", 15,
         "Fill the Revenue KPI Tracker with the last six months, then update it on the same day each month. This is a template "
         "for your own reporting: Demo Ventures does not collect MIS through the portal.", "revenue-kpi-tracker"),
    ]),
    (2, "Core HR policies", "Write down the few people policies every team needs.", [
        ("What to cover first", 6,
         "Early policies prevent avoidable disputes. Start with:\n- Working hours, leave and holidays.\n- Expenses and reimbursements.\n"
         "- Code of conduct, including the POSH policy and committee where the law requires it.\n- Exit process and notice periods.\n\n" + ADVISOR_NOTE, None),
        ("Do it: publish a team FAQ", 15,
         "Use the Team FAQ template to answer the questions people ask most. Publish it where everyone can find it and name an owner "
         "who keeps it current.", "team-faq-template"),
    ]),
    (2, "ESOP policy", "Decide how employee stock options will work before you promise them.", [
        ("The decisions behind an ESOP", 7,
         "Before offering options, agree:\n- The size of the pool as a share of the company.\n- Vesting schedule and cliff.\n"
         "- What happens when someone leaves.\n- How you explain the value to employees.\n\n" + ADVISOR_NOTE, None),
        ("Do it: get the plan documented", 10,
         "Write your answers to the decisions above, then ask your lawyer and CA to draft the scheme and board approvals. Your Demo Ventures "
         "team can introduce advisors through Connect.", None),
    ]),
    (2, "Quarterly OKRs", "Agree three to five outcomes for the quarter and how you will measure them.", [
        ("Outcomes, not task lists", 5,
         "Objectives say what you want to achieve; key results are the numbers that prove it.\n\n"
         "- Three to five objectives for the company, each with two to four measurable key results.\n- Every key result has one owner.\n"
         "- Review progress in the monthly meeting.", None),
        ("Do it: plan this quarter", 15,
         "Use the OKR Planning Template. Draft at leadership level first, then let teams add their own key results that support the company's.",
         "okr-planning-template"),
    ]),
    (3, "Sales pipeline review", "Know where every deal stands and what moves it forward.", [
        ("A pipeline you can trust", 6,
         "A useful pipeline has clear stages with exit criteria, a next step and date for every deal, and an honest view of what is stuck.\n\n"
         "- Review it weekly with the people who own deals.\n- Close out deals that have not moved in 60 days.", None),
        ("Do it: set up the tracker", 15, "Load your open deals into the Sales Pipeline Tracker and agree stage definitions with the team.",
         "sales-pipeline-tracker"),
    ]),
    (3, "Customer insight", "Turn customer conversations into decisions.", [
        ("Who your best customers are", 6,
         "Your ideal customer profile (ICP) describes the customers who buy fastest, stay longest and get the most value.\n\n"
         "- Look at your best ten customers: what do they have in common?\n- Write down the problems they hire you to solve, in their words.", None),
        ("Do it: define your ICP", 15, "Work through the ICP Definition Framework with sales and product, and share the result with the whole team.",
         "icp-definition-framework"),
    ]),
    (3, "Leadership hiring plan", "Plan the senior hires the next stage needs.", [
        ("Hire for the next stage", 6,
         "List the leadership gaps that block the next 12 months, in order. For each role, write what success looks like after a year "
         "before you write the job description.\n\nYour Demo Ventures team can feature candidate profiles for your openings in Hiring.", None),
        ("Do it: write the job descriptions", 15,
         "Use the Job Description Template for each role, add the openings on your Hiring page and share each opening's interest link.",
         "job-description-template"),
    ]),
    (4, "Evidence room", "Have the documents investors will ask for ready before you raise.", [
        ("What investors check", 6,
         "Due diligence goes faster when documents are organised before you start.\n\n- Company and legal documents.\n- Financials and KPIs.\n"
         "- Customer contracts and pipeline.\n- Team, ESOP and policies.", None),
        ("Do it: fill your data room checklist", 20,
         "Work through the Investor Data Room Checklist and mark each item ready, in progress or missing.", "investor-data-room-checklist"),
    ]),
    (4, "Fundraising narrative", "Tell a clear story about why the company wins.", [
        ("The story in five parts", 7,
         "A fundraising narrative answers: the problem, why now, why you, the evidence so far, and what the money will achieve.\n\n"
         "Test it on people who do not know the business: if they cannot repeat it, simplify it.", None),
        ("Do it: draft your narrative", 20, "Use the Fundraising Narrative Guide to draft and test your story before you build the deck.",
         "fundraising-narrative-guide"),
    ]),
    (4, "Investor process", "Run the raise as a process with a timeline.", [
        ("Plan the raise like a project", 6,
         "A planned process keeps momentum and gives you options.\n\n- Build a target list matched to your stage and sector.\n"
         "- Plan warm introductions; your Demo Ventures team can help.\n- Set a timeline and track every conversation.", None),
        ("Do it: set up your outreach tracker", 15, "Load your target investors into the Investor Outreach Tracker and agree who owns each relationship.",
         "investor-outreach-tracker"),
    ]),
]


def ensure_starter(cur) -> int:
    """Load the starter course into an empty course. Returns the number of chapters added (0 if any exist)."""
    cur.execute("SELECT 1 FROM lms_chapters LIMIT 1")
    if cur.fetchone():
        return 0
    order = 0
    for phase, title, summary, lessons in CHAPTERS:
        order += 1
        cur.execute(
            "INSERT INTO lms_chapters (phase_no, sort_order, title, summary, status, created_by) VALUES (%s, %s, %s, %s, 'published', %s) RETURNING id",
            (phase, order, title, summary, "Demo Ventures starter content"),
        )
        chapter_id = cur.fetchone()[0]
        for i, (lt, minutes, body, slug) in enumerate(lessons, start=1):
            cur.execute(
                """
                INSERT INTO lms_lessons (chapter_id, sort_order, title, body, resource_slug, minutes, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, 'published', %s)
                """,
                (chapter_id, i, lt, body, slug, minutes, "Demo Ventures starter content"),
            )
    return len(CHAPTERS)
