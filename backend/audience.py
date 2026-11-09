"""Who a resource, event or sector update is for (meetings of 23 Oct 2026: map content by sector and stage).

An item is for one company (company_id), or portfolio-wide (company_id NULL) and optionally narrowed to chosen
companies, sectors and/or stages. Founder screens filter with the SQL function fp_visible() (schema.sql).
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

STAGES = ["Pre-seed", "Seed", "Pre-Series A", "Series A", "Series B", "Series C+", "Growth"]


def visible(alias: str = "") -> str:
    """SQL condition (one %s parameter: the company id) that an item is meant for that company."""
    a = f"{alias}." if alias else ""
    return f"fp_visible({a}company_id, {a}target_company_ids, {a}target_sectors, {a}target_stages, %s)"


class Audience(BaseModel):
    """Targeting chosen in the workspace dropdowns. company_id = one company only; otherwise the lists
    narrow a portfolio-wide item (all empty = every portfolio company)."""
    company_id: int | None = None
    target_company_ids: list[int] = Field(default_factory=list, max_length=200)
    target_sectors: list[str] = Field(default_factory=list, max_length=40)
    target_stages: list[str] = Field(default_factory=list, max_length=10)


def sectors(cur) -> list[str]:
    """Every sector tag used by a company (a company's sector is a comma-separated list of tags)."""
    cur.execute(
        """
        SELECT DISTINCT t FROM (
            SELECT trim(unnest(string_to_array(sector, ','))) AS t FROM companies WHERE sector IS NOT NULL
        ) x WHERE t <> '' ORDER BY t
        """
    )
    return [r[0] for r in cur.fetchall()]


def sector_tags(text: str | None) -> list[str]:
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def clean_audience(cur, aud: Audience, scope: set[int] | None) -> dict[str, Any]:
    """Validate targeting against real companies, sectors and stages, and the user's company scope.
    scope None = all companies; otherwise a non-Super-Admin may only target their own companies."""
    ids = sorted({int(i) for i in aud.target_company_ids})
    secs = sorted({s.strip() for s in aud.target_sectors if s and s.strip()})
    stages = sorted({s.strip() for s in aud.target_stages if s and s.strip()})
    if aud.company_id is not None:
        ids = []
        secs, stages = [], []
        wanted = [aud.company_id]
    else:
        wanted = ids
    if wanted:
        cur.execute("SELECT id FROM companies WHERE id = ANY(%s)", (wanted,))
        found = {r[0] for r in cur.fetchall()}
        if found != set(wanted):
            raise HTTPException(status_code=422, detail="One of the chosen companies does not exist")
        if scope is not None and not set(wanted) <= scope:
            raise HTTPException(status_code=403, detail="You can target only the companies you are assigned to")
    bad = set(stages) - set(STAGES)
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown stage: {', '.join(sorted(bad))}")
    known = set(sectors(cur))
    bad = set(secs) - known
    if bad:
        raise HTTPException(status_code=422, detail=f"No company has the sector: {', '.join(sorted(bad))}")
    return {"company_id": aud.company_id, "target_company_ids": ids, "target_sectors": secs, "target_stages": stages}


def describe(company_name: str | None, ids: list[int] | None, secs: list[str] | None, stages: list[str] | None,
             names: dict[int, str] | None = None) -> str:
    """Plain-language audience shown in the workspace."""
    if company_name:
        return f"{company_name} only"
    parts = []
    if ids:
        listed = [names.get(i, f"#{i}") for i in ids] if names else [str(len(ids))]
        parts.append(", ".join(listed) if names else f"{len(ids)} companies")
    if secs:
        parts.append("sector: " + ", ".join(secs))
    if stages:
        parts.append("stage: " + ", ".join(stages))
    return "All portfolio founders" if not parts else "Portfolio companies · " + " · ".join(parts)


def company_names(cur) -> dict[int, str]:
    cur.execute("SELECT id, name FROM companies")
    return {r[0]: r[1] for r in cur.fetchall()}
