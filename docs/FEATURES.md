# Features, roles and permissions

A short, public specification of the Founder's Resource Portal. Everything shown in this repository uses
fictional demo data (fund: **Demo Ventures (fictional)**).

## Founder portal (`index.html`)

| Area | What a founder can do |
|---|---|
| Dashboard | Company-specific greeting, news flashes for their sector, a featured candidate, Connect / requests / playbook stats, upcoming events |
| Resource Library | Browse and download approved templates (fundraising, finance, hiring, sales, product); every download is logged |
| Sector Updates | Short, approved briefs for their company's sector: what happened, why it matters to them, link to the source |
| Company profile | Keep governance, compliance and service-provider details up to date; change history; PDF export |
| Connect | Directory of investors, operational partners, peer founders and the fund team; ask for an introduction |
| Hiring | Open roles, candidate profiles featured by the fund team, a public "express interest" page per opening |
| Messages / support | One trackable request thread with the fund team: status, owner, priority |
| Playbook | 100-day checklist across four phases (progress computed from tasks) plus chapter-by-chapter lessons |
| Events | Upcoming events with RSVP and calendar (.ics) download |

## Team workspace (`analyst.html`)

Overview, **Approvals**, Companies & founders (invite founders with single-use links), request queue,
questionnaire answers, activity tracking, content (resources, sector updates, events, Connect, hiring,
playbook lessons), messages/outbox and Team & access with a full audit trail.

## Roles

| Tier | Who | Scope |
|---|---|---|
| 1 · Super Admin | Exactly one person (enforced by a unique index) | Whole portfolio; the only approver; adds Admins; full audit trail; can hand the role over |
| 2 · Admin | Portfolio managers | Their own companies (and their analysts' companies) |
| 3 · Analyst | Portfolio team members | Day-to-day support for their assigned companies; everything they add waits for approval |
| Founder | Invited founders and their team | Their own company's portal only |

Anything an Admin or Analyst adds (resources, events, Connect profiles, sector updates, candidate profiles)
waits in the Super Admin's **Approvals** queue; founders never see it before approval.

## Permission matrix

Generated from `backend/permissions.py`, the single source of truth (synced to the database at start-up;
every API route checks a permission, never a role name). ✓ = all companies · ✓ (own) = only assigned
companies · — = not allowed.

| Permission | Code | What it allows | Super Admin | Admin | Analyst | Founder |
|---|---|---|---|---|---|---|
| View overview | `overview.view` | See the workspace overview | ✓ | ✓ | ✓ | — |
| View companies | `companies.view` | See portfolio companies, their founders and Demo Ventures team | ✓ | ✓ (own) | ✓ (own) | — |
| Set up companies | `companies.add` | Add a portfolio company and edit the details of your companies | ✓ | ✓ (own) | ✓ (own) | — |
| Manage founder accounts | `founders.manage` | Invite founders and reset or deactivate their accounts | ✓ | ✓ (own) | ✓ (own) | — |
| Assign the Demo Ventures team | `team.assign` | Choose the company's relationship manager and analyst | ✓ | ✓ (own) | — | — |
| Manage analysts | `staff.manage` | Add analysts and reset or deactivate their accounts | ✓ | ✓ | — | — |
| Manage admins | `admins.manage` | Add admins and move people between the Admin and Analyst tiers | ✓ | — | — | — |
| Hand over Super Admin | `super_admin.handover` | Give the Super Admin role to another person | ✓ | — | — | — |
| View audit trail | `audit.view` | See every admin change and every download | ✓ | ✓ (own) | — | — |
| Track founder activity | `activity.founders` | See what founders have done: sign-ins, downloads, requests | ✓ | ✓ (own) | ✓ (own) | — |
| Track analyst activity | `activity.analysts` | See what analysts have done | ✓ | ✓ (own) | — | — |
| Track admin activity | `activity.admins` | See what admins have done | ✓ | — | — | — |
| Add and edit content | `content.submit` | Add or edit resources, events, Connect profiles and sector updates | ✓ | ✓ | ✓ | — |
| Approve content | `content.approve` | Approve, return or withdraw anything waiting for approval | ✓ | — | — | — |
| Manage playbooks | `playbooks.manage` | Set the playbook owner and manage playbook tasks | ✓ | ✓ (own) | ✓ (own) | — |
| Write sector updates | `news.publish` | Write sector updates for a company | ✓ | ✓ | ✓ | — |
| Manage news feeds | `news.sources` | Add, pause and tag news feeds (used by beta news suggestions) | ✓ | ✓ | ✓ | — |
| Approve news feeds | `news.sources.approve` | Approve a news feed as a trusted source | ✓ | — | — | — |
| Manage events | `events.manage` | Add, cancel and restore events; add join and recording links | ✓ | ✓ | ✓ | — |
| Manage Connect profiles | `connect.manage` | Add, edit and hide Connect profiles | ✓ | ✓ | ✓ | — |
| Handle founder requests | `requests.handle` | Work queue: status, owner and priority | ✓ | ✓ (own) | ✓ (own) | — |
| Feature candidate profiles | `talent.feature` | Add a company's open roles and feature candidate profiles on its founders' dashboard | ✓ | ✓ (own) | ✓ (own) | — |
| Manage the playbook lessons | `lms.manage` | Write, order and publish the chapters and lessons founders see in the Playbook | ✓ | ✓ | — | — |
| Approve candidate profiles | `talent.approve` | Decide whether a candidate profile is good enough to show to founders | ✓ | ✓ | — | — |
| Read questionnaire answers | `intakes.view` | Read founders' questionnaire answers | ✓ | ✓ (own) | ✓ (own) | — |
| Preview founder portal | `founder.preview` | View the founder portal as one of your companies | ✓ | ✓ (own) | ✓ (own) | — |
| Use founder portal | `portal.use` | Use the founder portal for your own company | — | — | — | ✓ |

## Request lifecycle

Founder raises a request (support or introduction) → it lands in the team's queue for that company →
an owner, status and priority are set → the founder follows the same thread until it is resolved. Every
step is recorded in the audit trail.

## Product boundaries (by design)

- MIS appears only as a downloadable template; there is no live MIS collection or investment-performance dashboard.
- Nothing is presented as legal, tax, investment or valuation advice.
- Third-party material is published only with redistribution rights and attribution.
- Automatic sector-news suggestions (RSS feed matching) are built but switched off; updates are written and approved by people.
