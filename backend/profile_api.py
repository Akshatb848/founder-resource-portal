"""Company profile (alpha v1.2.6, meeting with the MD on 29 Oct 2026).

The portal, not the spreadsheet, is the single source of truth for company data:
- brand name (companies.name) shown large, legal name smaller beneath it;
- governance: statutory auditor and appointment date, company secretary, legal counsel, bankers,
  board, advisory board and independent directors;
- compliance items answered Yes / No / Not applicable, with certificate details and expiry dates;
  SHA custody and AOP;
- DPDP consent (captured, duration, renewal frequency, SHA annexure);
- credit lines (bank, instrument, amount, interest rate), with corporate credit cards kept separate.

Firms (auditors, company secretaries, law firms, banks, lenders, investment banks) come from one shared
list. Callers send firm names; resolve_firm() finds the existing firm by its normalised name or adds it, so
the same firm is never entered twice.

Who may do what (no new permissions): staff read with companies.view and edit with companies.add, both
limited to their companies; founders read and edit their own company (portal.use). Staff previewing the
founder portal can read it but not change it there. Every change is written to admin_audit with the fields
that changed (old and new value); history starts now and is not backfilled.

Expiry badges: an expired certificate is red, one expiring within EXPIRY_WARN_DAYS is amber. Email reminders
and automatic alert rules are phase 2.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.admin_api import _audit, read_csv_upload
from backend.db import get_conn
from backend.pdf_simple import SimplePDF
from backend.security import auth_session, company_scope, founder_company, has_perm, is_founder, iso, need, require_company
from backend.xlsx_read import read_xlsx_rows

router = APIRouter(prefix="/api")

IST = timezone(timedelta(hours=5, minutes=30))
EXPIRY_WARN_DAYS = 60
CONFIRM_EVERY_DAYS = 365  # details not confirmed for a year show amber ("annual update")
YNA = ("yes", "no", "na")
YNA_LABEL = {"yes": "Yes", "no": "No", "na": "Not applicable", None: "Not answered"}
FIRM_KINDS = {
    "auditor": "Auditor", "company_secretary": "Company secretary", "law_firm": "Law firm",
    "bank": "Bank", "lender": "Lender", "investment_bank": "Investment bank", "tax_advisor": "Tax or structuring advisor",
}
PEOPLE_KINDS = {"board": "Board members", "advisory": "Advisory board", "independent": "Independent directors"}
CREDIT_KINDS = {"credit_line": "Credit lines", "credit_card": "Corporate credit cards"}
# The compliance items every company is asked about. Companies can add their own items as well.
STANDARD_COMPLIANCE = [
    ("msme", "MSME (Udyam) registration"),
    ("dpiit", "DPIIT Startup India recognition"),
    ("deeptech", "Deep-tech startup registration"),
    ("gst", "GST registration"),
    ("iso", "ISO certification"),
    ("trademark", "Trademark registration"),
    ("iec", "Import Export Code (IEC)"),
    ("posh", "POSH internal committee"),
    ("shops", "Shops and Establishment licence"),
]
STANDARD_ITEMS = [label for _, label in STANDARD_COMPLIANCE]
DPDP_RENEWAL_CHOICES = ["Every 6 months", "Every year", "Every 2 years", "Every 3 years", "Only when purpose changes", "Not set"]
SUFFIXES = ("private limited", "pvt ltd", "pvt", "limited", "ltd", "llp", "and co", "co", "inc", "india")


# ---------------------------------------------------------------- helpers
def firm_key(name: str) -> str:
    """Normalised firm name for finding duplicates: case, punctuation, '&' and common legal suffixes ignored.
    "Example Assurance & Sells LLP" and "example assurance and sells" give the same key."""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    changed = True
    while changed and s:
        changed = False
        for suf in SUFFIXES:
            if suf == "india" and s.endswith(" of india"):
                continue  # Bank of India, State Bank of India: part of the name
            if s.endswith(" " + suf) and len(s) > len(suf) + 1:
                s = s[: -len(suf) - 1].strip()
                changed = True
    return re.sub(r"\s+", " ", s)


def resolve_firm(cur, name: str | None, kind: str, actor: str) -> int | None:
    """The id of the firm with this name (adding it, or tagging it with this kind, when needed)."""
    name = re.sub(r"\s+", " ", (name or "")).strip()
    if not name:
        return None
    if len(name) > 160:
        raise HTTPException(status_code=422, detail="A firm name can be at most 160 characters")
    key = firm_key(name)
    if not key:
        raise HTTPException(status_code=422, detail=f"'{name}' is not a usable firm name")
    cur.execute("SELECT id, kinds FROM firms WHERE name_key = %s", (key,))
    row = cur.fetchone()
    if row:
        if kind not in (row[1] or []):
            cur.execute("UPDATE firms SET kinds = array_append(kinds, %s) WHERE id = %s", (kind, row[0]))
        return row[0]
    cur.execute("INSERT INTO firms (name, name_key, kinds, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
                (name, key, [kind], actor))
    return cur.fetchone()[0]


def parse_inr(val: Any) -> Decimal | None:
    """Rupee amounts as people write them: 5 crore, 5 cr, 50 lakh, 50L, 5,00,00,000, Rs 2.5 Cr."""
    if val is None:
        return None
    if isinstance(val, (int, float, Decimal)):
        return Decimal(str(val))
    s = re.sub(r"^(₹|inr|rs\.?)\s*", "", str(val).strip().lower()).replace(",", "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|l|k|thousand)?", s)
    if not m:
        raise HTTPException(status_code=422, detail=f"Amount '{val}' is not a number (for example 5 crore or 50 lakh)")
    num = Decimal(m.group(1))
    unit = m.group(2) or ""
    if unit.startswith("cr"):
        num *= Decimal(10_000_000)
    elif unit.startswith("la") or unit == "l":
        num *= Decimal(100_000)
    elif unit in ("k", "thousand"):
        num *= Decimal(1000)
    return num


def format_inr(amount: Decimal | float | None, rupee: str = "₹") -> str:
    if amount is None:
        return ""
    a = Decimal(str(amount))

    def short(x: Decimal) -> str:
        return f"{x.quantize(Decimal('0.01')).normalize():f}"

    if a >= 10_000_000:
        return f"{rupee}{short(a / 10_000_000)} crore"
    if a >= 100_000:
        return f"{rupee}{short(a / 100_000)} lakh"
    return f"{rupee}{short(a)}"


def parse_rate(val: Any) -> Decimal | None:
    if val in (None, ""):
        return None
    s = str(val).strip().rstrip("%").strip()
    if not s:
        return None
    try:
        r = Decimal(s)
    except InvalidOperation:
        raise HTTPException(status_code=422, detail=f"Interest rate '{val}' is not a number (for example 11.5)") from None
    if r < 0 or r > 100:
        raise HTTPException(status_code=422, detail="Interest rate must be between 0 and 100 per cent")
    return r


def parse_date(val: Any, label: str) -> date | None:
    """ISO dates (2026-10-29), Indian style (29/10/2026, 29-10-2026, 29 Oct 2026) and Excel serial numbers."""
    if val in (None, ""):
        return None
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{5}(\.0+)?", s):  # Excel stores dates as days since 30 Dec 1899
        return date(1899, 12, 30) + timedelta(days=int(float(s)))
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise HTTPException(status_code=422, detail=f"{label}: '{s}' is not a date (use 2026-10-29 or 29/10/2026)")


def yna(val: Any, label: str) -> str | None:
    if val in (None, ""):
        return None
    s = str(val).strip().lower()
    mapped = {"yes": "yes", "y": "yes", "true": "yes", "no": "no", "n": "no", "false": "no",
              "na": "na", "n/a": "na", "not applicable": "na", "not_applicable": "na"}.get(s)
    if not mapped:
        raise HTTPException(status_code=422, detail=f"{label} must be Yes, No or Not applicable")
    return mapped


def clean(val: Any, limit: int = 300) -> str | None:
    if val is None:
        return None
    s = re.sub(r"\s+", " ", str(val)).strip()
    return s[:limit] or None


def expiry_state(expires: date | None, today: date | None = None) -> str | None:
    """red (expired), amber (within EXPIRY_WARN_DAYS) or None."""
    if not expires:
        return None
    today = today or datetime.now(IST).date()
    if expires < today:
        return "red"
    if expires <= today + timedelta(days=EXPIRY_WARN_DAYS):
        return "amber"
    return None


def fmt_date(d: date | None) -> str:
    return d.strftime("%d %b %Y") if d else ""


# ---------------------------------------------------------------- reading a profile
def load_profile(cur, company_id: int) -> dict[str, Any]:
    cur.execute("SELECT id, name, legal_name, slug, sector, stage, city, fund, website, profile_confirmed_at, profile_confirmed_by "
                "FROM companies WHERE id = %s", (company_id,))
    c = cur.fetchone()
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")
    cur.execute(
        """
        SELECT a.name, p.auditor_appointed_on, s.name, l.name, p.sha_custody, p.aop_status, p.aop_note,
               p.dpdp_consent, p.dpdp_consent_duration, p.dpdp_renewal, p.dpdp_sha_annexure, p.updated_at, p.updated_by,
               p.secretary_engaged_on, p.accounts_signed_on, ib.name, tx.name, p.cloud_provider, p.board_nominee,
               p.infosec_policy, p.cos_name, p.cos_joined_on, p.patents_filed, p.patents_granted, p.share_cert_custody,
               p.demat_status
        FROM company_profile p
        LEFT JOIN firms a ON a.id = p.auditor_firm_id
        LEFT JOIN firms s ON s.id = p.secretary_firm_id
        LEFT JOIN firms l ON l.id = p.legal_counsel_firm_id
        LEFT JOIN firms ib ON ib.id = p.investment_bank_firm_id
        LEFT JOIN firms tx ON tx.id = p.tax_advisor_firm_id
        WHERE p.company_id = %s
        """, (company_id,))
    p = cur.fetchone() or (None,) * 26
    day = lambda v: v.isoformat() if v else None  # noqa: E731
    cur.execute("SELECT f.name FROM company_bankers b JOIN firms f ON f.id = b.firm_id WHERE b.company_id = %s "
                "ORDER BY b.sort_order, f.name", (company_id,))
    bankers = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT kind, full_name, role_note FROM company_people WHERE company_id = %s ORDER BY kind, sort_order, id", (company_id,))
    people = {k: [] for k in PEOPLE_KINDS}
    for kind, name, note in cur.fetchall():
        people[kind].append({"full_name": name, "role_note": note})
    cur.execute("SELECT item, status, certificate_no, issued_on, expires_on, note FROM company_compliance "
                "WHERE company_id = %s ORDER BY sort_order, id", (company_id,))
    answered = {r[0]: r for r in cur.fetchall()}
    compliance = []
    for item in STANDARD_ITEMS + [i for i in answered if i not in STANDARD_ITEMS]:
        r = answered.get(item)
        compliance.append({
            "item": item, "standard": item in STANDARD_ITEMS,
            "status": r[1] if r else None, "certificate_no": r[2] if r else None,
            "issued_on": r[3].isoformat() if r and r[3] else None, "expires_on": r[4].isoformat() if r and r[4] else None,
            "note": r[5] if r else None, "alert": expiry_state(r[4]) if r and r[1] == "yes" else None,
        })
    cur.execute("SELECT c.kind, f.name, c.instrument, c.amount_inr, c.interest_rate, c.note FROM company_credit c "
                "LEFT JOIN firms f ON f.id = c.firm_id WHERE c.company_id = %s ORDER BY c.kind, c.sort_order, c.id", (company_id,))
    credit = {k: [] for k in CREDIT_KINDS}
    for kind, lender, instrument, amount, rate, note in cur.fetchall():
        credit[kind].append({"lender": lender, "instrument": instrument,
                             "amount_inr": float(amount) if amount is not None else None, "amount_label": format_inr(amount),
                             "interest_rate": float(rate) if rate is not None else None, "note": note})
    confirmed = c[9]
    stale = confirmed is None or confirmed < datetime.now(timezone.utc) - timedelta(days=CONFIRM_EVERY_DAYS)
    alerts = [{"level": x["alert"], "item": x["item"], "expires_on": x["expires_on"]} for x in compliance if x["alert"]]
    alerts.sort(key=lambda a: (a["level"] != "red", a["expires_on"] or ""))
    prof = {
        "company": {"id": c[0], "brand_name": c[1], "legal_name": c[2], "slug": c[3], "sector": c[4], "stage": c[5],
                    "city": c[6], "fund": c[7], "website": c[8]},
        "governance": {
            "auditor": p[0], "auditor_appointed_on": p[1].isoformat() if p[1] else None,
            "company_secretary": p[2], "legal_counsel": p[3], "bankers": bankers,
            "board": people["board"], "advisory": people["advisory"], "independent": people["independent"],
            "secretary_engaged_on": day(p[13]), "board_nominee": p[18], "infosec_policy": p[19],
            "cos_name": p[20], "cos_joined_on": day(p[21]),
        },
        "services": {"accounts_signed_on": day(p[14]), "investment_bank": p[15], "tax_advisor": p[16], "cloud_provider": p[17]},
        "patents": {"filed": p[22], "granted": p[23]},
        "compliance": compliance,
        "agreements": {"sha_custody": p[4], "aop_status": p[5], "aop_note": p[6], "share_cert_custody": p[24], "demat_status": p[25]},
        "dpdp": {"consent": p[7], "consent_duration": p[8], "renewal": p[9], "sha_annexure": p[10]},
        "credit": credit,
        "updated_at": iso(p[11]), "updated_by": p[12],
        "confirmed_at": iso(confirmed), "confirmed_by": c[10], "confirm_due": stale,
        "alerts": alerts,
    }
    prof["completeness"] = completeness(prof)
    return prof


def completeness(prof: dict[str, Any], internal: bool = True) -> dict[str, Any]:
    """Which key fields are still empty: the gap list analysts fill in with founders.
    internal=False leaves out the agreements and DPDP fields, which founders do not see."""
    g, a, d = prof["governance"], prof["agreements"], prof["dpdp"]
    checks = [
        ("Legal name", prof["company"]["legal_name"]),
        ("Statutory auditor", g["auditor"]),
        ("Auditor appointment date", g["auditor_appointed_on"]),
        ("Company secretary", g["company_secretary"]),
        ("Legal counsel", g["legal_counsel"]),
        ("Bankers", g["bankers"]),
        ("Board members", g["board"]),
        ("Company secretary engaged since", g["secretary_engaged_on"]),
        ("Audited accounts signed on", prof["services"]["accounts_signed_on"]),
        ("Cloud service provider", prof["services"]["cloud_provider"]),
        ("Information security and privacy policy", g["infosec_policy"]),
        ("Patents filed", prof["patents"]["filed"] is not None),
    ]
    if internal:
        checks += [
            ("SHA custody", a["sha_custody"]),
            ("Share certificates custody", a["share_cert_custody"]),
            ("Demat status", a["demat_status"]),
            ("AOP", a["aop_status"]),
            ("DPDP consent", d["consent"]),
            ("DPDP consent annexure in the SHA", d["sha_annexure"]),
        ]
    checks += [(x["item"], x["status"]) for x in prof["compliance"] if x["standard"]]
    missing = [label for label, val in checks if not val]
    total = len(checks)
    return {"filled": total - len(missing), "total": total, "pct": round(100 * (total - len(missing)) / total), "missing": missing}


def flatten(prof: dict[str, Any]) -> dict[str, str]:
    """Every field as label -> text, for the change history (old and new values)."""
    g, a, d = prof["governance"], prof["agreements"], prof["dpdp"]
    people = lambda rows: "; ".join(r["full_name"] + (f" ({r['role_note']})" if r.get("role_note") else "") for r in rows)
    out = {
        "Legal name": prof["company"]["legal_name"] or "",
        "Statutory auditor": g["auditor"] or "", "Auditor appointment date": g["auditor_appointed_on"] or "",
        "Company secretary": g["company_secretary"] or "", "Legal counsel": g["legal_counsel"] or "",
        "Bankers": "; ".join(g["bankers"]),
        "Board members": people(g["board"]), "Advisory board": people(g["advisory"]),
        "Independent directors": people(g["independent"]),
        "Company secretary engaged since": g["secretary_engaged_on"] or "",
        "Demo Ventures nominee or observer on the board": g["board_nominee"] or "",
        "Information security and privacy policy": YNA_LABEL[g["infosec_policy"]] if g["infosec_policy"] else "",
        "Chief of Staff": " ".join(x for x in (g["cos_name"] or "", f"(joined {g['cos_joined_on']})" if g["cos_joined_on"] else "") if x),
        "Audited accounts signed on": prof["services"]["accounts_signed_on"] or "",
        "Investment banker": prof["services"]["investment_bank"] or "",
        "Tax or structuring advisor": prof["services"]["tax_advisor"] or "",
        "Cloud service provider": prof["services"]["cloud_provider"] or "",
        "Patents filed": "" if prof["patents"]["filed"] is None else str(prof["patents"]["filed"]),
        "Patents granted": "" if prof["patents"]["granted"] is None else str(prof["patents"]["granted"]),
        "SHA custody": a["sha_custody"] or "",
        "Share certificates custody": a["share_cert_custody"] or "",
        "Demat status": YNA_LABEL[a["demat_status"]] if a["demat_status"] else "",
        "AOP": " ".join(x for x in (YNA_LABEL[a["aop_status"]] if a["aop_status"] else "", a["aop_note"] or "") if x),
        "DPDP consent": YNA_LABEL[d["consent"]] if d["consent"] else "",
        "DPDP consent duration": d["consent_duration"] or "", "DPDP renewal": d["renewal"] or "",
        "DPDP consent annexure in the SHA": YNA_LABEL[d["sha_annexure"]] if d["sha_annexure"] else "",
    }
    for x in prof["compliance"]:
        if x["status"]:
            bits = [YNA_LABEL[x["status"]], x["certificate_no"] and f"no. {x['certificate_no']}",
                    x["issued_on"] and f"issued {x['issued_on']}", x["expires_on"] and f"expires {x['expires_on']}", x["note"]]
            out[f"Compliance: {x['item']}"] = ", ".join(b for b in bits if b)
    for kind, label in CREDIT_KINDS.items():
        out[label] = "; ".join(
            ", ".join(b for b in (r["lender"], r["instrument"], r["amount_label"], f"{r['interest_rate']:g}%" if r["interest_rate"] is not None else "") if b)
            for r in prof["credit"][kind])
    return out


# The order fields appear in on screen and in the PDF; the history lists changes in the same order
# (the database stores them as JSON, which does not keep key order).
FIELD_ORDER = ["Legal name", "Statutory auditor", "Auditor appointment date", "Company secretary", "Company secretary engaged since",
               "Legal counsel", "Bankers", "Audited accounts signed on", "Investment banker", "Tax or structuring advisor",
               "Cloud service provider", "Board members", "Demo Ventures nominee or observer on the board", "Advisory board",
               "Independent directors", "Information security and privacy policy", "Chief of Staff", "Patents filed",
               "Patents granted", *[f"Compliance: {i}" for i in STANDARD_ITEMS],
               "SHA custody", "Share certificates custody", "Demat status", "AOP", "DPDP consent", "DPDP consent duration", "DPDP renewal", "DPDP consent annexure in the SHA",
               "Credit lines", "Corporate credit cards"]


def diff(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    keys = list(dict.fromkeys([*before, *after]))
    return {k: [before.get(k, ""), after.get(k, "")] for k in keys if before.get(k, "") != after.get(k, "")}


# Agreements and DPDP are Demo Ventures' own records (SHA and share certificate custody, demat, AOP, DPDP consent).
# Founders never receive them: not on screen, in the PDF, in the gap list or in the change history.
INTERNAL_FIELDS = {"SHA custody", "Share certificates custody", "Demat status", "AOP", "DPDP consent",
                   "DPDP consent duration", "DPDP renewal", "DPDP consent annexure in the SHA"}


def founder_view(prof: dict[str, Any]) -> dict[str, Any]:
    """The profile as a founder sees it: without the agreements and DPDP fields."""
    prof["completeness"] = completeness(prof, internal=False)
    prof.pop("agreements", None)
    prof.pop("dpdp", None)
    if "history" in prof:
        kept = []
        for h in prof["history"]:
            changes = {k: v for k, v in (h.get("changes") or {}).items() if k not in INTERNAL_FIELDS}
            if h.get("changes") and not changes and h.get("action") != "profile.confirm":
                continue  # a change that touched only Demo Ventures' own fields
            kept.append({**h, "changes": changes})
        prof["history"] = kept
    if "choices" in prof:
        prof["choices"].pop("dpdp_renewal", None)
    return prof


def keep_internal(cur, company_id: int, body: "ProfileIn") -> "ProfileIn":
    """A founder's save leaves the agreements and DPDP fields as Demo Ventures last set them."""
    cur_prof = load_profile(cur, company_id)
    a, d = cur_prof["agreements"], cur_prof["dpdp"]
    return body.model_copy(update={
        "sha_custody": a["sha_custody"], "share_cert_custody": a["share_cert_custody"], "demat_status": a["demat_status"],
        "aop_status": a["aop_status"], "aop_note": a["aop_note"],
        "dpdp_consent": d["consent"], "dpdp_consent_duration": d["consent_duration"], "dpdp_renewal": d["renewal"],
        "dpdp_sha_annexure": d["sha_annexure"],
    })


def history(cur, company_id: int, limit: int = 30) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT a.created_at, a.action, a.details, COALESCE(u.full_name, a.actor)
        FROM admin_audit a LEFT JOIN users u ON lower(u.email) = lower(a.actor)
        WHERE a.company_id = %s AND a.action LIKE 'profile.%%' ORDER BY a.created_at DESC LIMIT %s
        """, (company_id, limit))
    out = []
    for at, action, details, who in cur.fetchall():
        det = details if isinstance(details, dict) else json.loads(details or "{}")
        changes = det.get("changes", {})
        changes = dict(sorted(changes.items(), key=lambda kv: (FIELD_ORDER.index(kv[0]) if kv[0] in FIELD_ORDER else len(FIELD_ORDER), kv[0])))
        out.append({"at": iso(at), "by": who, "action": action,
                    "what": {"profile.update": "Updated the profile", "profile.confirm": "Confirmed the details are current",
                             "profile.import": "Imported from a spreadsheet"}.get(action, action),
                    "changes": changes})
    return out


# ---------------------------------------------------------------- saving a profile
class Person(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    role_note: str | None = Field(default=None, max_length=120)


class ComplianceIn(BaseModel):
    item: str = Field(min_length=2, max_length=120)
    status: str | None = None
    certificate_no: str | None = Field(default=None, max_length=120)
    issued_on: str | None = None
    expires_on: str | None = None
    note: str | None = Field(default=None, max_length=300)


class CreditIn(BaseModel):
    lender: str | None = Field(default=None, max_length=160)
    instrument: str | None = Field(default=None, max_length=120)
    amount: str | float | None = None
    interest_rate: str | float | None = None
    note: str | None = Field(default=None, max_length=300)


class ProfileIn(BaseModel):
    """The whole profile, as the edit form sends it. Lists replace what was there."""
    legal_name: str | None = Field(default=None, max_length=200)
    auditor: str | None = Field(default=None, max_length=160)
    auditor_appointed_on: str | None = None
    company_secretary: str | None = Field(default=None, max_length=160)
    legal_counsel: str | None = Field(default=None, max_length=160)
    bankers: list[str] = Field(default_factory=list, max_length=20)
    board: list[Person] = Field(default_factory=list, max_length=30)
    advisory: list[Person] = Field(default_factory=list, max_length=30)
    independent: list[Person] = Field(default_factory=list, max_length=30)
    compliance: list[ComplianceIn] = Field(default_factory=list, max_length=40)
    sha_custody: str | None = Field(default=None, max_length=300)
    aop_status: str | None = None
    aop_note: str | None = Field(default=None, max_length=300)
    dpdp_consent: str | None = None
    dpdp_consent_duration: str | None = Field(default=None, max_length=120)
    dpdp_renewal: str | None = Field(default=None, max_length=120)
    dpdp_sha_annexure: str | None = None
    credit_lines: list[CreditIn] = Field(default_factory=list, max_length=30)
    credit_cards: list[CreditIn] = Field(default_factory=list, max_length=30)
    # From the portfolio tracker (3 Nov 2026)
    secretary_engaged_on: str | None = None
    accounts_signed_on: str | None = None
    investment_bank: str | None = Field(default=None, max_length=160)
    tax_advisor: str | None = Field(default=None, max_length=160)
    cloud_provider: str | None = Field(default=None, max_length=160)
    board_nominee: str | None = Field(default=None, max_length=200)
    infosec_policy: str | None = None
    cos_name: str | None = Field(default=None, max_length=120)
    cos_joined_on: str | None = None
    patents_filed: str | int | None = None
    patents_granted: str | int | None = None
    share_cert_custody: str | None = Field(default=None, max_length=300)
    demat_status: str | None = None


def count(val: Any, label: str) -> int | None:
    """A whole number of 0 or more (patents filed or granted); empty means not answered."""
    if val is None or str(val).strip() == "":
        return None
    s = str(val).strip()
    if not re.fullmatch(r"\d{1,5}", s):
        raise HTTPException(status_code=422, detail=f"{label} must be a whole number such as 0, 3 or 12")
    return int(s)


def save_profile(cur, company_id: int, body: ProfileIn, actor: dict[str, Any]) -> dict[str, list[str]]:
    """Replace the company's profile with body. Returns the fields that changed (old, new)."""
    who = actor["full_name"]
    before = flatten(load_profile(cur, company_id))
    cur.execute("UPDATE companies SET legal_name = %s WHERE id = %s", (clean(body.legal_name, 200), company_id))
    vals = {
        "auditor_firm_id": resolve_firm(cur, body.auditor, "auditor", who),
        "auditor_appointed_on": parse_date(body.auditor_appointed_on, "Auditor appointment date"),
        "secretary_firm_id": resolve_firm(cur, body.company_secretary, "company_secretary", who),
        "legal_counsel_firm_id": resolve_firm(cur, body.legal_counsel, "law_firm", who),
        "sha_custody": clean(body.sha_custody), "aop_status": yna(body.aop_status, "AOP"), "aop_note": clean(body.aop_note),
        "dpdp_consent": yna(body.dpdp_consent, "DPDP consent"), "dpdp_consent_duration": clean(body.dpdp_consent_duration, 120),
        "dpdp_renewal": clean(body.dpdp_renewal, 120), "dpdp_sha_annexure": yna(body.dpdp_sha_annexure, "DPDP consent annexure"),
        "secretary_engaged_on": parse_date(body.secretary_engaged_on, "Company secretary engaged since"),
        "accounts_signed_on": parse_date(body.accounts_signed_on, "Audited accounts signed on"),
        "investment_bank_firm_id": resolve_firm(cur, body.investment_bank, "investment_bank", who),
        "tax_advisor_firm_id": resolve_firm(cur, body.tax_advisor, "tax_advisor", who),
        "cloud_provider": clean(body.cloud_provider, 160), "board_nominee": clean(body.board_nominee, 200),
        "infosec_policy": yna(body.infosec_policy, "Information security and privacy policy"),
        "cos_name": clean(body.cos_name, 120), "cos_joined_on": parse_date(body.cos_joined_on, "Chief of Staff joined on"),
        "patents_filed": count(body.patents_filed, "Patents filed"), "patents_granted": count(body.patents_granted, "Patents granted"),
        "share_cert_custody": clean(body.share_cert_custody), "demat_status": yna(body.demat_status, "Demat status"),
    }
    if vals["patents_filed"] is not None and vals["patents_granted"] is not None and vals["patents_granted"] > vals["patents_filed"]:
        raise HTTPException(status_code=422, detail="Patents granted cannot be more than patents filed")
    cols = list(vals)  # fixed column names, never user input
    cur.execute(
        f"""
        INSERT INTO company_profile (company_id, {", ".join(cols)}, updated_at, updated_by)
        VALUES (%s, {", ".join(["%s"] * len(cols))}, NOW(), %s)
        ON CONFLICT (company_id) DO UPDATE SET {", ".join(f"{c} = EXCLUDED.{c}" for c in cols)},
            updated_at = NOW(), updated_by = EXCLUDED.updated_by
        """, (company_id, *vals.values(), who))
    cur.execute("DELETE FROM company_bankers WHERE company_id = %s", (company_id,))
    seen: set[int] = set()
    for i, name in enumerate(body.bankers):
        fid = resolve_firm(cur, name, "bank", who)
        if fid and fid not in seen:
            seen.add(fid)
            cur.execute("INSERT INTO company_bankers (company_id, firm_id, sort_order) VALUES (%s, %s, %s)", (company_id, fid, i))
    cur.execute("DELETE FROM company_people WHERE company_id = %s", (company_id,))
    for kind in PEOPLE_KINDS:
        for i, person in enumerate(getattr(body, kind)):
            name = clean(person.full_name, 120)
            if name:
                cur.execute("INSERT INTO company_people (company_id, kind, full_name, role_note, sort_order) VALUES (%s, %s, %s, %s, %s)",
                            (company_id, kind, name, clean(person.role_note, 120), i))
    cur.execute("DELETE FROM company_compliance WHERE company_id = %s", (company_id,))
    done: set[str] = set()
    for i, x in enumerate(body.compliance):
        item = clean(x.item, 120)
        status = yna(x.status, item or "Compliance item")
        if not item or not status or item.lower() in done:
            continue
        done.add(item.lower())
        detailed = status == "yes"  # certificate details only make sense when the answer is Yes
        issued = parse_date(x.issued_on, f"{item}: issued on") if detailed else None
        expires = parse_date(x.expires_on, f"{item}: expires on") if detailed else None
        if issued and expires and expires < issued:
            raise HTTPException(status_code=422, detail=f"{item}: the expiry date is before the issue date")
        cur.execute(
            "INSERT INTO company_compliance (company_id, item, status, certificate_no, issued_on, expires_on, note, sort_order) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (company_id, item, status, clean(x.certificate_no, 120) if detailed else None, issued, expires, clean(x.note), i))
    cur.execute("DELETE FROM company_credit WHERE company_id = %s", (company_id,))
    for kind, rows, firm_kind in (("credit_line", body.credit_lines, "lender"), ("credit_card", body.credit_cards, "bank")):
        for i, r in enumerate(rows):
            if not any((clean(r.lender), clean(r.instrument), r.amount not in (None, ""), r.interest_rate not in (None, ""))):
                continue  # an empty row in the form
            cur.execute(
                "INSERT INTO company_credit (company_id, kind, firm_id, instrument, amount_inr, interest_rate, note, sort_order) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (company_id, kind, resolve_firm(cur, r.lender, firm_kind, who), clean(r.instrument, 120), parse_inr(r.amount),
                 parse_rate(r.interest_rate), clean(r.note), i))
    return diff(before, flatten(load_profile(cur, company_id)))


def _put(company_id: int, body: ProfileIn, user: dict[str, Any], founder: bool = False) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if founder:
                body = keep_internal(cur, company_id, body)
            changes = save_profile(cur, company_id, body, user)
            if changes:
                cur.execute("SELECT name FROM companies WHERE id = %s", (company_id,))
                _audit(cur, user, "profile.update", cur.fetchone()[0], {"changes": changes}, company_id)
            prof = load_profile(cur, company_id)
        conn.commit()
    prof["changed"] = list(changes)
    if founder:
        prof["changed"] = [k for k in prof["changed"] if k not in INTERNAL_FIELDS]
        return founder_view(prof)
    return prof


def _confirm(company_id: int, user: dict[str, Any]) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE companies SET profile_confirmed_at = NOW(), profile_confirmed_by = %s WHERE id = %s RETURNING name",
                        (user["full_name"], company_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Company not found")
            _audit(cur, user, "profile.confirm", row[0], {}, company_id)
            prof = load_profile(cur, company_id)
        conn.commit()
    return prof


def _get(company_id: int, can_edit: bool) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            prof = load_profile(cur, company_id)
            prof["history"] = history(cur, company_id)
    prof["can_edit"] = can_edit
    prof["choices"] = {"standard_items": STANDARD_ITEMS, "dpdp_renewal": DPDP_RENEWAL_CHOICES,
                       "expiry_warn_days": EXPIRY_WARN_DAYS}
    return prof


def list_firms() -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f.id, f.name, f.kinds,
                       (SELECT COUNT(DISTINCT company_id) FROM (
                            SELECT company_id FROM company_profile WHERE f.id IN (auditor_firm_id, secretary_firm_id, legal_counsel_firm_id, investment_bank_firm_id, tax_advisor_firm_id)
                            UNION ALL SELECT company_id FROM company_bankers WHERE firm_id = f.id
                            UNION ALL SELECT company_id FROM company_credit WHERE firm_id = f.id) used)
                FROM firms f ORDER BY lower(f.name)""")
            return [{"id": r[0], "name": r[1], "kinds": r[2], "companies": r[3]} for r in cur.fetchall()]


# ---------------------------------------------------------------- PDF
def profile_pdf(prof: dict[str, Any], generated_by: str) -> bytes:
    """The full company profile as a PDF; the legal name is printed in the footer of every page."""
    c, g, a, d = prof["company"], prof["governance"], prof.get("agreements"), prof.get("dpdp")
    today = datetime.now(IST)
    footer = c["legal_name"] or c["brand_name"]
    pdf = SimplePDF(footer_left=footer)
    pdf.title(c["brand_name"])
    if c["legal_name"]:
        pdf.subtitle(c["legal_name"])
    pdf.note(" · ".join(x for x in (c["sector"], c["stage"], c["city"], c["fund"]) if x))
    confirmed = (f"Details last confirmed {fmt_date(datetime.fromisoformat(prof['confirmed_at']).astimezone(IST).date())}"
                 f" by {prof['confirmed_by']}") if prof["confirmed_at"] else "Details not yet confirmed"
    pdf.note(f"Company profile generated {today.strftime('%d %b %Y, %H:%M')} IST by {generated_by}. {confirmed}.")
    if prof["alerts"]:
        pdf.heading("Needs attention")
        for al in prof["alerts"]:
            when = fmt_date(date.fromisoformat(al["expires_on"]))
            pdf.row("Expired" if al["level"] == "red" else "Expires soon", f"{al['item']} ({when})")
    pdf.heading("Governance")
    pdf.row("Statutory auditor", g["auditor"] or "-")
    pdf.row("Auditor appointed on", fmt_date(date.fromisoformat(g["auditor_appointed_on"])) if g["auditor_appointed_on"] else "-")
    when = lambda v: fmt_date(date.fromisoformat(v)) if v else "-"  # noqa: E731
    sv, pt = prof["services"], prof["patents"]
    pdf.row("Company secretary", g["company_secretary"] or "-")
    pdf.row("Company secretary engaged since", when(g["secretary_engaged_on"]))
    pdf.row("Legal counsel", g["legal_counsel"] or "-")
    pdf.row("Bankers", ", ".join(g["bankers"]) or "-")
    for kind, label in PEOPLE_KINDS.items():
        rows = g[kind]
        pdf.row(label, "; ".join(r["full_name"] + (f" ({r['role_note']})" if r.get("role_note") else "") for r in rows) or "-")
    pdf.row("Demo Ventures nominee or observer", g["board_nominee"] or "-")
    pdf.row("Information security and privacy policy", YNA_LABEL[g["infosec_policy"]])
    pdf.row("Chief of Staff", " ".join(x for x in (g["cos_name"] or "-", f"(joined {when(g['cos_joined_on'])})" if g["cos_joined_on"] else "") if x))
    pdf.heading("Service providers")
    pdf.row("Audited accounts signed on", when(sv["accounts_signed_on"]))
    pdf.row("Investment banker", sv["investment_bank"] or "-")
    pdf.row("Tax or structuring advisor", sv["tax_advisor"] or "-")
    pdf.row("Cloud service provider", sv["cloud_provider"] or "-")
    pdf.row("Patents", f"{'-' if pt['filed'] is None else pt['filed']} filed, {'-' if pt['granted'] is None else pt['granted']} granted")
    pdf.heading("Compliance")
    for x in prof["compliance"]:
        if not x["status"] and not x["standard"]:
            continue
        bits = [YNA_LABEL[x["status"]]]
        if x["status"] == "yes":
            bits += [x["certificate_no"] and f"Certificate {x['certificate_no']}",
                     x["issued_on"] and f"issued {fmt_date(date.fromisoformat(x['issued_on']))}",
                     x["expires_on"] and f"expires {fmt_date(date.fromisoformat(x['expires_on']))}"]
        if x["alert"]:
            bits.append("EXPIRED" if x["alert"] == "red" else "EXPIRES SOON")
        bits.append(x["note"])
        pdf.row(x["item"], ", ".join(b for b in bits if b))
    if a is not None and d is not None:  # staff only; the founder view has neither
        pdf.heading("Agreements")
        pdf.row("SHA custody", a["sha_custody"] or "-")
        pdf.row("Share certificates custody", a["share_cert_custody"] or "-")
        pdf.row("Demat status", YNA_LABEL[a["demat_status"]])
        pdf.row("AOP", ", ".join(b for b in (YNA_LABEL[a["aop_status"]], a["aop_note"]) if b))
        pdf.heading("DPDP consent")
        pdf.row("Consent captured", YNA_LABEL[d["consent"]])
        pdf.row("Consent duration", d["consent_duration"] or "-")
        pdf.row("Renewal frequency", d["renewal"] or "-")
        pdf.row("Consent annexure in the SHA", YNA_LABEL[d["sha_annexure"]])
    for kind, label in CREDIT_KINDS.items():
        pdf.heading(label)
        rows = prof["credit"][kind]
        if not rows:
            pdf.row("", "None recorded")
        for r in rows:
            amount = format_inr(r["amount_inr"], rupee="Rs ") if r["amount_inr"] is not None else ""
            rate = f"{r['interest_rate']:g}% interest" if r["interest_rate"] is not None else ""
            pdf.row(r["lender"] or "-", ", ".join(b for b in (r["instrument"], amount, rate, r["note"]) if b) or "-")
    pdf.heading("Profile completeness")
    comp = prof["completeness"]
    pdf.row("Filled in", f"{comp['filled']} of {comp['total']} key fields ({comp['pct']}%)")
    if comp["missing"]:
        pdf.row("Still missing", ", ".join(comp["missing"]))
    return pdf.output()


def _pdf_response(prof: dict[str, Any], user: dict[str, Any]) -> Response:
    data = profile_pdf(prof, user["full_name"])
    slug = prof["company"]["slug"] or "company"
    name = f"{slug}-company-profile-{datetime.now(IST).strftime('%Y-%m-%d')}.pdf"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- staff routes
def _staff_can_edit(user: dict[str, Any], company_id: int) -> bool:
    if not has_perm(user, "companies.add"):
        return False
    allowed = company_scope(user, "companies.add")
    return allowed is None or company_id in allowed


@router.get("/admin/companies/{company_id}/profile")
def admin_get_profile(company_id: int, user: dict = Depends(need("companies.view"))) -> dict[str, Any]:
    require_company(user, "companies.view", company_id)
    return _get(company_id, _staff_can_edit(user, company_id))


@router.put("/admin/companies/{company_id}/profile")
def admin_put_profile(company_id: int, body: ProfileIn, user: dict = Depends(need("companies.add"))) -> dict[str, Any]:
    require_company(user, "companies.add", company_id)
    return _put(company_id, body, user)


@router.post("/admin/companies/{company_id}/profile/confirm")
def admin_confirm_profile(company_id: int, user: dict = Depends(need("companies.add"))) -> dict[str, Any]:
    require_company(user, "companies.add", company_id)
    return _confirm(company_id, user)


@router.get("/admin/companies/{company_id}/profile.pdf")
def admin_profile_pdf(company_id: int, user: dict = Depends(need("companies.view"))) -> Response:
    require_company(user, "companies.view", company_id)
    return _pdf_response(_get(company_id, False), user)


@router.get("/admin/firms")
def admin_firms(user: dict = Depends(need("companies.view"))) -> dict[str, Any]:
    return {"firms": list_firms(), "kinds": FIRM_KINDS}


class FirmRename(BaseModel):
    name: str = Field(min_length=2, max_length=160)


@router.patch("/admin/firms/{firm_id}")
def rename_firm(firm_id: int, body: FirmRename, user: dict = Depends(need("content.approve"))) -> dict[str, Any]:
    """The Super Admin corrects a firm's spelling; every company using it shows the new name."""
    name = re.sub(r"\s+", " ", body.name).strip()
    key = firm_key(name)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM firms WHERE id = %s", (firm_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Firm not found")
            cur.execute("SELECT name FROM firms WHERE name_key = %s AND id <> %s", (key, firm_id))
            other = cur.fetchone()
            if other:
                raise HTTPException(status_code=409, detail=f"'{other[0]}' is already in the list")
            cur.execute("UPDATE firms SET name = %s, name_key = %s WHERE id = %s", (name, key, firm_id))
            _audit(cur, user, "firm.rename", name, {"from": row[0], "to": name})
        conn.commit()
    return {"status": "renamed", "name": name}


@router.get("/admin/profile-gaps")
def profile_gaps(user: dict = Depends(need("companies.view"))) -> list[dict[str, Any]]:
    """Each company's completeness, alerts and confirmation state (the gap list for analysts)."""
    allowed = company_scope(user, "companies.view")
    out = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM companies WHERE status = 'active' ORDER BY name")
            for (cid,) in cur.fetchall():
                if allowed is not None and cid not in allowed:
                    continue
                prof = load_profile(cur, cid)
                out.append({"company_id": cid, "brand_name": prof["company"]["brand_name"], "legal_name": prof["company"]["legal_name"],
                            "completeness": prof["completeness"], "alerts": prof["alerts"],
                            "confirmed_at": prof["confirmed_at"], "confirm_due": prof["confirm_due"]})
    return out


# ---------------------------------------------------------------- Demo Ventures tracker (staff only)
# Columns of the "Portfolio Tracker" sheet that are Demo Ventures' own follow-up. They are never sent to founders
# (no founder route reads company_tracker) and never printed in the profile PDF.
TRACKER_FIELDS = [
    # (key, label, kind, max length)
    ("exit_discussion", "Last exit discussion", "text", 600),
    ("exit_discussion_on", "Exit discussion date", "date", 0),
    ("exit_led_by", "Exit discussion led by", "text", 120),
    ("sha_review_status", "SHA rights review status", "text", 300),
    ("sha_review_period", "SHA rights review month or quarter", "text", 40),
    ("fundraise_status", "Fundraise status", "text", 600),
    ("action_points", "Specific action points", "text", 2000),
    ("kyc_received", "Founders' KYC received", "yna", 0),
    ("kyc_received_on", "KYC received on", "date", 0),
]
TRACKER_KEYS = [k for k, *_ in TRACKER_FIELDS]
# KYC is tracked as received or not: identity numbers must never be typed into the portal (DPDP).
ID_NUMBER = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b|\b\d{4}\s?\d{4}\s?\d{4}\b|\b[A-Z]\d{7}\b")


class TrackerIn(BaseModel):
    exit_discussion: str | None = Field(default=None, max_length=600)
    exit_discussion_on: str | None = None
    exit_led_by: str | None = Field(default=None, max_length=120)
    sha_review_status: str | None = Field(default=None, max_length=300)
    sha_review_period: str | None = Field(default=None, max_length=40)
    fundraise_status: str | None = Field(default=None, max_length=600)
    action_points: str | None = Field(default=None, max_length=2000)
    kyc_received: str | None = None
    kyc_received_on: str | None = None


def load_tracker(cur, company_id: int) -> dict[str, Any]:
    cur.execute(f"SELECT {', '.join(TRACKER_KEYS)}, updated_at, updated_by FROM company_tracker WHERE company_id = %s", (company_id,))
    row = cur.fetchone() or (None,) * (len(TRACKER_KEYS) + 2)
    vals = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in zip(TRACKER_KEYS, row)}
    return {"values": vals, "updated_at": iso(row[-2]), "updated_by": row[-1],
            "fields": [{"key": k, "label": label, "kind": kind, "max": n} for k, label, kind, n in TRACKER_FIELDS]}


def _tracker_text(vals: dict[str, Any]) -> dict[str, str]:
    out = {}
    for k, label, kind, _ in TRACKER_FIELDS:
        v = vals.get(k)
        out[label] = (YNA_LABEL[v] if kind == "yna" and v else str(v or ""))[:200]
    return out


def save_tracker(cur, company_id: int, body: TrackerIn, actor: dict[str, Any]) -> dict[str, list[str]]:
    """Replace the company's tracker values. Returns the fields that changed (old, new)."""
    before = _tracker_text(load_tracker(cur, company_id)["values"])
    vals: dict[str, Any] = {}
    for k, label, kind, n in TRACKER_FIELDS:
        raw = getattr(body, k)
        if kind == "date":
            vals[k] = parse_date(raw, label)
        elif kind == "yna":
            vals[k] = yna(raw, label)
        else:
            text = (str(raw).strip()[:n] or None) if raw is not None else None
            if text and ID_NUMBER.search(text.upper()):
                raise HTTPException(status_code=422, detail=f"{label}: PAN, Aadhaar or passport numbers must not be stored in the portal. "
                                                            "Record only whether KYC is received.")
            vals[k] = text
    if vals["kyc_received"] != "yes":
        vals["kyc_received_on"] = None  # a received date only makes sense when KYC is received
    cur.execute(
        f"""
        INSERT INTO company_tracker (company_id, {", ".join(TRACKER_KEYS)}, updated_at, updated_by)
        VALUES (%s, {", ".join(["%s"] * len(TRACKER_KEYS))}, NOW(), %s)
        ON CONFLICT (company_id) DO UPDATE SET {", ".join(f"{c} = EXCLUDED.{c}" for c in TRACKER_KEYS)},
            updated_at = NOW(), updated_by = EXCLUDED.updated_by
        """, (company_id, *[vals[k] for k in TRACKER_KEYS], actor["full_name"]))
    return diff(before, _tracker_text(load_tracker(cur, company_id)["values"]))


@router.get("/admin/companies/{company_id}/tracker")
def admin_get_tracker(company_id: int, user: dict = Depends(need("companies.view"))) -> dict[str, Any]:
    require_company(user, "companies.view", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM companies WHERE id = %s", (company_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Company not found")
            out = load_tracker(cur, company_id)
    out["can_edit"] = _staff_can_edit(user, company_id)
    return out


@router.put("/admin/companies/{company_id}/tracker")
def admin_put_tracker(company_id: int, body: TrackerIn, user: dict = Depends(need("companies.add"))) -> dict[str, Any]:
    require_company(user, "companies.add", company_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM companies WHERE id = %s", (company_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Company not found")
            changes = save_tracker(cur, company_id, body, user)
            if changes:
                _audit(cur, user, "tracker.update", row[0], {"changes": changes}, company_id)
            out = load_tracker(cur, company_id)
        conn.commit()
    out["can_edit"] = True
    out["changed"] = list(changes)
    return out


# ---------------------------------------------------------------- founder routes
@router.get("/founder/profile")
def founder_get_profile(user: dict = Depends(auth_session)) -> dict[str, Any]:
    cid = founder_company(user)[0]
    return founder_view(_get(cid, is_founder(user)))  # staff previewing see it read-only, as the founder does


def _founder_only(user: dict[str, Any]) -> int:
    cid = founder_company(user)[0]
    if not is_founder(user):
        raise HTTPException(status_code=403, detail="Preview is read-only. Edit the profile from the workspace.")
    return cid


@router.put("/founder/profile")
def founder_put_profile(body: ProfileIn, user: dict = Depends(auth_session)) -> dict[str, Any]:
    return _put(_founder_only(user), body, user, founder=True)


@router.post("/founder/profile/confirm")
def founder_confirm_profile(user: dict = Depends(auth_session)) -> dict[str, Any]:
    return founder_view(_confirm(_founder_only(user), user))


@router.get("/founder/profile.pdf")
def founder_profile_pdf(user: dict = Depends(auth_session)) -> Response:
    cid = founder_company(user)[0]
    return _pdf_response(founder_view(_get(cid, False)), user)


@router.get("/founder/firms")
def founder_firms(user: dict = Depends(auth_session)) -> dict[str, Any]:
    founder_company(user)  # founders and staff previewing only
    return {"firms": [{"id": f["id"], "name": f["name"], "kinds": f["kinds"]} for f in list_firms()], "kinds": FIRM_KINDS}


# ---------------------------------------------------------------- spreadsheet import
PROFILE_COLUMNS = ["company", "legal_name", "auditor", "auditor_appointed_on", "company_secretary", "legal_counsel",
                   "bankers", "board_members", "advisory_board", "independent_directors", "sha_custody", "aop", "aop_note",
                   "dpdp_consent", "dpdp_consent_duration", "dpdp_renewal", "dpdp_sha_annexure",
                   "secretary_engaged_on", "accounts_signed_on", "investment_bank", "tax_advisor", "cloud_provider",
                   "board_nominee", "infosec_policy", "cos_name", "cos_joined_on", "patents_filed", "patents_granted",
                   "share_cert_custody", "demat_status"]
# Staff-only columns, kept in company_tracker.
TRACKER_IMPORT_COLUMNS = list(TRACKER_KEYS)
# The column names of Demo Ventures' "Portfolio Tracker" sheet, so it can be uploaded as it is.
TRACKER_HEADERS = {
    "company name": "company", "company": "company", "particulars": "legal_name", "updated as on": "",
    "name of statutory auditor": "auditor", "auditor engaged since": "auditor_appointed_on",
    "audited accounts signature date": "accounts_signed_on", "name of cs": "company_secretary",
    "cs engaged since": "secretary_engaged_on", "legal counsel": "legal_counsel",
    "investment banker (appointed/ used in past)": "investment_bank", "tax/ structuring advisor": "tax_advisor",
    "banking partner": "bankers", "credit history (cc limit/ corporate credit card)": "credit_history",
    "cloud service provider": "cloud_provider", "formal board nominee/ observer": "board_nominee",
    "external advisory board constituted (y/n) + independent directors": "advisory_board",
    "information security & privacy policy (dpdp)": "infosec_policy", "name of cos appointed (joined since)": "cos_name",
    "filed": "patents_filed", "granted": "patents_granted", "control of share certificates": "share_cert_custody",
    "control of sha": "sha_custody", "demat status": "demat_status",
    "last exit discussion (lead by whom)": "exit_discussion", "sha rights review (status & month/qtr)": "sha_review_status",
    "founders' kyc (pan aadhar & passport)": "kyc_received", "fundraise status": "fundraise_status",
    "specific action points": "action_points", "deeptech registration with validity": "deeptech_tracker",
    "startup registration": "dpiit_tracker", "msme registration": "msme_tracker",
}


def _header_key(cell: Any) -> str:
    s = str(cell or "").replace("\u2019", "'").lower()
    return re.sub(r"\s+", " ", s).strip()


def _tracker_header(cell: Any) -> str:
    """A sheet column name in the portal's own terms; FY25 AOP received and the like map to aop."""
    key = _header_key(cell)
    if re.fullmatch(r"fy ?\d{2,4} aop received", key):
        return "aop"
    return TRACKER_HEADERS.get(key, key)
COMPLIANCE_COLUMNS = [f"{key}_{part}" for key, _ in STANDARD_COMPLIANCE for part in ("status", "certificate", "expires_on")]
CREDIT_COLUMNS = ["company", "type", "lender", "instrument", "amount", "interest_rate", "note"]


def _template(columns: list[str], example: list[str], filename: str) -> Response:
    buf = io.StringIO()
    csv.writer(buf).writerows([columns, example])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/admin/profile-import/template")
def import_template(kind: str = "profile", user: dict = Depends(need("companies.add"))) -> Response:
    if kind == "credit":
        return _template(CREDIT_COLUMNS, ["example-company", "credit line", "Example Bank", "Working capital loan", "5 crore", "11.5", ""],
                         "company-credit-template.csv")
    example = ["example-company", "Example Technologies Private Limited", "Example & Co LLP", "2024-09-30", "Example CS Associates",
               "Example Legal LLP", "Example Bank; Second Bank", "Leela Das (Chair); Omar Siddiqui", "Dr. Tara Menon", "",
               "Demo Ventures legal team", "Yes", "FY27 approved", "Yes", "Until purpose ends", "Every year", "No",
               "2023-04-01", "2025-09-15", "", "Example Tax Advisors LLP", "AWS", "Farhan Ali (Demo Ventures observer)", "Yes", "",
               "", "3", "1", "Demo Ventures legal team", "Yes"]
    example += ["yes", "UDYAM-XX-00-0000000", "2027-03-31"] + [""] * (len(COMPLIANCE_COLUMNS) - 3)
    example += [""] * len(TRACKER_IMPORT_COLUMNS)
    assert len(example) == len(PROFILE_COLUMNS) + len(COMPLIANCE_COLUMNS) + len(TRACKER_IMPORT_COLUMNS)
    return _template(PROFILE_COLUMNS + COMPLIANCE_COLUMNS + TRACKER_IMPORT_COLUMNS, example, "company-profile-template.csv")


def _rows_from_upload(data: bytes, filename: str, columns: list[str]) -> list[dict[str, str]]:
    if len(data) > 1_000_000:
        raise HTTPException(status_code=413, detail="The file is larger than 1 MB")
    if filename.lower().endswith(".xlsx"):
        raw = read_xlsx_rows(data)
        if not raw:
            raise HTTPException(status_code=422, detail="The spreadsheet is empty")
    else:
        try:
            raw = list(csv.reader(io.StringIO(data[:1_000_001].decode("utf-8-sig"))))
        except UnicodeDecodeError:
            raw = None  # read_csv_upload explains how to save the file as UTF-8
    if raw:
        # The portfolio tracker has a group row (Professional Services, Governance ...) above its column names:
        # start at the row that names the company column, and use the portal's names for the tracker's columns.
        head = next((i for i, r in enumerate(raw[:10]) if any(_header_key(c) in ("company", "company name") for c in r)), 0)
        raw = [[c if c in columns else _tracker_header(c) for c in raw[head]]] + raw[head + 1:]
        buf = io.StringIO()
        csv.writer(buf).writerows(raw)
        data = buf.getvalue().encode("utf-8")
    return read_csv_upload(data, [columns[0]], tuple(columns[1:]))


def _company_lookup(cur) -> dict[str, int]:
    cur.execute("SELECT id, slug, name, legal_name FROM companies")
    out: dict[str, int] = {}
    for cid, slug, name, legal in cur.fetchall():
        for key in (slug, name, legal):
            if key:
                out.setdefault(key.strip().lower(), cid)
    return out


def _find_company(lookup: dict[str, int], ref: str) -> int | None:
    """A company by short ID, brand name or legal name; failing that, the one company whose name starts with or
    contains the reference (the tracker writes "Nimbus" for Nimbus Mobility and "Ledger" for Ledgerly Fintech)."""
    ref = ref.strip().lower()
    if ref in lookup:
        return lookup[ref]
    k = re.sub(r"[^a-z0-9]", "", ref)
    if len(k) < 3:
        return None
    hits = {cid for name, cid in lookup.items() if (n := re.sub(r"[^a-z0-9]", "", name)).startswith(k) or k in n}
    return hits.pop() if len(hits) == 1 else None


def _register_cell(text: str, label: str) -> tuple[str | None, str | None, str | None]:
    """A tracker registration cell ('Yes, valid till 31/03/2027', 'Applied', 'NA') as (answer, expiry, note)."""
    s = (text or "").strip()
    if not s:
        return None, None, None
    low = s.lower()
    status = "yes" if re.match(r"(yes|y\b|done|registered|granted|valid|received)", low) else \
        "no" if re.match(r"(no|n\b|not\b|pending|applied)", low) else "na" if re.match(r"(na\b|n/a|not applicable)", low) else None
    expiry = None
    m = re.search(r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]{3,9} \d{4})", s)
    if m:
        expiry = parse_date(m.group(1).replace(".", "/"), label).isoformat()
    if status is None:
        status = "yes" if expiry else None
    return status, expiry, s[:300]


def _people(cell: str) -> list[Person]:
    """'Leela Das (Chair); Omar Siddiqui' -> two people."""
    out = []
    for part in re.split(r"[;\n]", cell):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(.+?)\s*\((.+)\)", part)
        out.append(Person(full_name=m.group(1), role_note=m.group(2)) if m else Person(full_name=part))
    return out


def _merge_profile_row(prof: dict[str, Any], r: dict[str, str]) -> ProfileIn:
    """The current profile with the row's non-empty cells applied: an empty cell never clears a value."""
    g, a, d = prof["governance"], prof["agreements"], prof["dpdp"]
    cell = lambda k: (r.get(k) or "").strip()
    body = ProfileIn(
        legal_name=cell("legal_name") or prof["company"]["legal_name"],
        auditor=cell("auditor") or g["auditor"], auditor_appointed_on=cell("auditor_appointed_on") or g["auditor_appointed_on"],
        company_secretary=cell("company_secretary") or g["company_secretary"], legal_counsel=cell("legal_counsel") or g["legal_counsel"],
        bankers=[b.strip() for b in cell("bankers").split(";") if b.strip()] if cell("bankers") else g["bankers"],
        board=_people(cell("board_members")) if cell("board_members") else [Person(**p) for p in g["board"]],
        advisory=_people(cell("advisory_board")) if cell("advisory_board") else [Person(**p) for p in g["advisory"]],
        independent=_people(cell("independent_directors")) if cell("independent_directors") else [Person(**p) for p in g["independent"]],
        sha_custody=cell("sha_custody") or a["sha_custody"], aop_status=cell("aop") or a["aop_status"], aop_note=cell("aop_note") or a["aop_note"],
        dpdp_consent=cell("dpdp_consent") or d["consent"], dpdp_consent_duration=cell("dpdp_consent_duration") or d["consent_duration"],
        dpdp_renewal=cell("dpdp_renewal") or d["renewal"], dpdp_sha_annexure=cell("dpdp_sha_annexure") or d["sha_annexure"],
        credit_lines=[CreditIn(lender=x["lender"], instrument=x["instrument"], amount=x["amount_inr"], interest_rate=x["interest_rate"], note=x["note"])
                      for x in prof["credit"]["credit_line"]],
        credit_cards=[CreditIn(lender=x["lender"], instrument=x["instrument"], amount=x["amount_inr"], interest_rate=x["interest_rate"], note=x["note"])
                      for x in prof["credit"]["credit_card"]],
    )
    sv, pt = prof["services"], prof["patents"]
    keep = lambda k, cur: cell(k) or cur  # noqa: E731
    body.secretary_engaged_on = keep("secretary_engaged_on", g["secretary_engaged_on"])
    body.accounts_signed_on = keep("accounts_signed_on", sv["accounts_signed_on"])
    body.investment_bank = keep("investment_bank", sv["investment_bank"])
    body.tax_advisor = keep("tax_advisor", sv["tax_advisor"])
    body.cloud_provider = keep("cloud_provider", sv["cloud_provider"])
    body.board_nominee = keep("board_nominee", g["board_nominee"])
    body.infosec_policy = keep("infosec_policy", g["infosec_policy"])
    body.cos_name = keep("cos_name", g["cos_name"])
    body.cos_joined_on = keep("cos_joined_on", g["cos_joined_on"])
    body.patents_filed = keep("patents_filed", pt["filed"])
    body.patents_granted = keep("patents_granted", pt["granted"])
    body.share_cert_custody = keep("share_cert_custody", a["share_cert_custody"])
    body.demat_status = keep("demat_status", a["demat_status"])
    compliance = []
    for key, label in STANDARD_COMPLIANCE:
        cur_item = next((x for x in prof["compliance"] if x["item"] == label), None) or {}
        status = cell(f"{key}_status") or cur_item.get("status")
        expires, note = cell(f"{key}_expires_on") or cur_item.get("expires_on"), cur_item.get("note")
        if cell(f"{key}_tracker"):  # the tracker's one-cell form, e.g. "Yes, valid till 31/03/2027"
            t_status, t_expires, t_note = _register_cell(cell(f"{key}_tracker"), label)
            status, expires, note = t_status or status, t_expires or expires, t_note or note
        compliance.append(ComplianceIn(item=label, status=status,
                                       certificate_no=cell(f"{key}_certificate") or cur_item.get("certificate_no"),
                                       issued_on=cur_item.get("issued_on"), expires_on=expires, note=note))
    compliance += [ComplianceIn(item=x["item"], status=x["status"], certificate_no=x["certificate_no"], issued_on=x["issued_on"],
                                expires_on=x["expires_on"], note=x["note"]) for x in prof["compliance"] if not x["standard"] and x["status"]]
    body.compliance = compliance
    return body


def _credit_type(val: str) -> str:
    s = (val or "").strip().lower()
    if "card" in s:
        return "credit_card"
    if s in ("", "credit line", "credit_line", "line", "loan", "credit"):
        return "credit_line"
    raise HTTPException(status_code=422, detail="type must be 'credit line' or 'credit card'")


@router.post("/admin/profile-import")
async def import_profiles(file: UploadFile = File(...), kind: str = Form("profile"), dry_run: bool = Form(True),
                          company_id: int | None = Form(None),
                          user: dict = Depends(need("companies.add"))) -> dict[str, Any]:
    """Bring the existing company sheet into the portal (CSV or .xlsx). dry_run=true checks every row and saves
    nothing; a real import saves only when every row is valid. Empty cells leave the current value alone. Credit rows (kind=credit) are added to the company's
    list, or update the row with the same lender and instrument."""
    if kind not in ("profile", "credit"):
        raise HTTPException(status_code=422, detail="kind must be profile or credit")
    columns = CREDIT_COLUMNS if kind == "credit" else PROFILE_COLUMNS + COMPLIANCE_COLUMNS + TRACKER_IMPORT_COLUMNS + \
        [f"{k}_tracker" for k, _ in STANDARD_COMPLIANCE] + ["credit_history"]
    rows = _rows_from_upload(await file.read(1_000_001), file.filename or "", columns)
    allowed = company_scope(user, "companies.add")
    if company_id is not None:
        # A sheet added while creating one company: its single company row fills that company's profile.
        rows = [r for r in rows if not re.fullmatch(r"fund\s+[ivx\d]+", (r.get("company") or "").strip().lower())]
        if len(rows) != 1:
            raise HTTPException(status_code=422, detail="For one company, the sheet should have one row of details")
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT slug FROM companies WHERE id = %s", (company_id,))
                hit = cur.fetchone()
        if not hit:
            raise HTTPException(status_code=404, detail="Company not found")
        rows[0]["company"] = hit[0]
    results, ok = [], 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            lookup = _company_lookup(cur)
            for n, r in enumerate(rows, start=2):  # row 1 is the header
                ref = (r.get("company") or "").strip()
                res: dict[str, Any] = {"row": n, "company": ref}
                if re.fullmatch(r"fund\s+[ivx\d]+", ref.lower()) or not ref:
                    res["skipped"] = "Fund heading or empty row"  # the tracker groups companies under Fund I, II, III
                    ok += 1
                    results.append(res)
                    continue
                cid = _find_company(lookup, ref)
                if not cid:
                    res["error"] = "No company with this short ID, brand name or legal name"
                elif allowed is not None and cid not in allowed:
                    res["error"] = "This company is not one of yours"
                else:
                    cur.execute("SAVEPOINT import_row")
                    try:
                        prof = load_profile(cur, cid)
                        if kind == "credit":
                            body = _merge_profile_row(prof, {})
                            target = body.credit_cards if _credit_type(r.get("type", "")) == "credit_card" else body.credit_lines
                            new = CreditIn(lender=r.get("lender"), instrument=r.get("instrument"), amount=r.get("amount") or None,
                                           interest_rate=r.get("interest_rate") or None, note=r.get("note"))
                            parse_inr(new.amount), parse_rate(new.interest_rate)  # report bad values on this row
                            same = next((x for x in target if firm_key(x.lender or "") == firm_key(new.lender or "")
                                         and (x.instrument or "").lower() == (new.instrument or "").lower()), None)
                            if same:
                                target[target.index(same)] = new
                            else:
                                target.append(new)
                        else:
                            body = _merge_profile_row(prof, r)
                            if (r.get("credit_history") or "").strip():
                                res["warning"] = "Credit history is not imported: add credit lines and cards in the profile"
                        changes = save_profile(cur, cid, body, user)
                        if kind == "profile" and any((r.get(k) or "").strip() for k in TRACKER_KEYS):
                            current = load_tracker(cur, cid)["values"]
                            merged = {k: (r.get(k) or "").strip() or current.get(k) for k in TRACKER_KEYS}
                            kyc = (r.get("kyc_received") or "").strip()
                            if kyc and not re.fullmatch(r"(?i)y|yes|n|no|na|n/a|not applicable|true|false", kyc):
                                merged["kyc_received"] = "yes" if re.match(r"(?i)(received|done|complete)", kyc) else None
                            t_changes = save_tracker(cur, cid, TrackerIn(**merged), user)
                            if t_changes and not dry_run:
                                _audit(cur, user, "tracker.import", prof["company"]["brand_name"], {"changes": t_changes, "file": file.filename}, cid)
                            changes = {**changes, **{f"Tracker: {k}": v for k, v in t_changes.items()}}
                        res.update(brand_name=prof["company"]["brand_name"], changes=list(changes))
                        if changes and not dry_run:
                            _audit(cur, user, "profile.import", prof["company"]["brand_name"],
                                   {"changes": changes, "file": file.filename}, cid)
                        cur.execute("RELEASE SAVEPOINT import_row")
                        ok += 1
                    except HTTPException as e:
                        cur.execute("ROLLBACK TO SAVEPOINT import_row")
                        res["error"] = e.detail
                results.append(res)
        # All or nothing: a real import with any bad row saves nothing, so the sheet can be fixed and sent again.
        saved = not dry_run and ok == len(rows)
        if saved:
            conn.commit()
        else:
            conn.rollback()
    return {"dry_run": dry_run, "saved": saved, "rows": len(rows), "ok": ok, "errors": len(rows) - ok, "results": results}
