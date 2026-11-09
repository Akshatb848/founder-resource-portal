"""100-Day Playbook: phase definitions, the starter task template and progress calculation."""
from __future__ import annotations

PHASES = [
    (1, "Foundation", "Days 1–30"),
    (2, "Operations", "Days 31–60"),
    (3, "Growth", "Days 61–80"),
    (4, "Fundraise readiness", "Days 81–100"),
]

# (phase, title, linked alpha resource slug or None), from the approved playbook wireframe.
TEMPLATE_TASKS = [
    (1, "Onboarding essentials", "employee-onboarding-checklist"),
    (1, "Founder alignment note", None),
    (1, "Initial operating cadence", "project-management-framework"),
    (2, "Board reporting template set up (template only)", "revenue-kpi-tracker"),
    (2, "Publish core HR policy", "team-faq-template"),
    (2, "Finalise ESOP policy", None),
    (2, "Set quarterly OKRs", "okr-planning-template"),
    (3, "Sales pipeline review", "sales-pipeline-tracker"),
    (3, "Customer insight synthesis", "icp-definition-framework"),
    (3, "Leadership hiring plan", "job-description-template"),
    (4, "Evidence room checklist", "investor-data-room-checklist"),
    (4, "Narrative readiness", "fundraising-narrative-guide"),
    (4, "Investor process plan", "investor-outreach-tracker"),
]


def phase_label(no: int) -> str:
    for n, name, days in PHASES:
        if n == no:
            return f"{name} · {days}"
    return "Completed"


def seed_template_tasks(cur, company_id: int, created_by: str = "Playbook template") -> int:
    """Add the starter tasks to a company that has none. Returns the number added."""
    cur.execute("SELECT 1 FROM playbook_tasks WHERE company_id = %s LIMIT 1", (company_id,))
    if cur.fetchone():
        return 0
    for i, (phase, title, slug) in enumerate(TEMPLATE_TASKS):
        cur.execute(
            """
            INSERT INTO playbook_tasks (company_id, phase_no, title, sort_order, resource_slug, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (company_id, phase, title, i, slug, created_by),
        )
    return len(TEMPLATE_TASKS)


def sync_progress(cur, company_id: int) -> tuple[int, str]:
    """Recalculate progress % and current phase from the task list and store them."""
    cur.execute(
        "SELECT phase_no, done FROM playbook_tasks WHERE company_id = %s ORDER BY phase_no, sort_order, id",
        (company_id,),
    )
    rows = cur.fetchall()
    total = len(rows)
    done = sum(1 for _, d in rows if d)
    pct = round(done * 100 / total) if total else 0
    open_phases = [p for p, d in rows if not d]
    current = phase_label(min(open_phases)) if open_phases else ("Completed" if total else phase_label(1))
    cur.execute("SELECT 1 FROM playbook_progress WHERE company_id = %s", (company_id,))
    if cur.fetchone():
        cur.execute(
            "UPDATE playbook_progress SET progress_pct = %s, current_phase = %s, updated_at = NOW() WHERE company_id = %s",
            (pct, current, company_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO playbook_progress (company_id, playbook_name, progress_pct, current_phase)
            VALUES (%s, '100-Day Founder Playbook', %s, %s)
            """,
            (company_id, pct, current),
        )
    return pct, current
