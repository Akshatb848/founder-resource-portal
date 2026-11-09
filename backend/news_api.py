"""Admin API for live sector news: feed sources, suggestions, publish / dismiss, fetch now.

Governance (Resource Repository meeting, 19 Oct 2026): sector updates stay curated. Feeds are read
automatically, but a person publishes every update, and only from a source Demo Ventures has approved.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.admin_api import UPDATE_LABELS, _audit
from backend.config import NEWS_FETCH_ENABLED, NEWS_FETCH_MINUTES, NEWS_SUGGESTIONS_ENABLED
from backend.db import get_conn
from backend.news_feed import (
    FeedError,
    company_keywords,
    fetch_feed,
    match_recent,
    run_cycle,
    scheduler_running,
    suggest_label,
    validate_feed_url,
)
from backend.security import has_perm, iso, need, require_perm

def _beta_only() -> None:
    """News suggestions are a beta feature; in alpha these routes do not exist (config.NEWS_SUGGESTIONS_ENABLED)."""
    if not NEWS_SUGGESTIONS_ENABLED:
        raise HTTPException(status_code=404, detail="News suggestions arrive in the beta version")


router = APIRouter(prefix="/api/admin/news", dependencies=[Depends(_beta_only)])


# ---------------------------------------------------------------- status + sources
@router.get("/sources")
def list_sources(user: dict = Depends(need("news.publish", "news.sources"))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.id, s.name, s.feed_url, s.site_url, s.kind, s.sectors, s.active, s.approved, s.approved_by,
                    s.approved_at, s.last_fetched_at, s.last_status, s.last_error,
                    (SELECT COUNT(*) FROM news_items i WHERE i.source_id = s.id AND i.published_at > NOW() - INTERVAL '10 days')
                FROM news_sources s ORDER BY s.approved DESC, s.kind, s.name
                """
            )
            rows = cur.fetchall()
            cur.execute(
                """
                SELECT started_at, finished_at, trigger, sources_ok, sources_failed, new_items, new_suggestions
                FROM news_fetch_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1
                """
            )
            last = cur.fetchone()
    return {
        "schedule": {"enabled": NEWS_FETCH_ENABLED, "running": scheduler_running(), "every_minutes": NEWS_FETCH_MINUTES},
        "can": {"manage_sources": has_perm(user, "news.sources"), "approve_sources": has_perm(user, "news.sources.approve"),
                "publish": has_perm(user, "news.publish")},
        "last_run": None if not last else {
            "started_at": iso(last[0]), "finished_at": iso(last[1]), "trigger": last[2], "sources_ok": last[3],
            "sources_failed": last[4], "new_items": last[5], "new_suggestions": last[6],
        },
        "sources": [
            {"id": r[0], "name": r[1], "feed_url": r[2], "site_url": r[3], "kind": r[4], "sectors": r[5], "active": r[6],
             "approved": r[7], "approved_by": r[8], "approved_at": iso(r[9]), "last_fetched_at": iso(r[10]),
             "last_status": r[11], "last_error": r[12], "recent_items": r[13]}
            for r in rows
        ],
    }


class SourceIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    feed_url: str = Field(min_length=10, max_length=500)
    kind: str = "news"
    sectors: str = Field(default="*", max_length=120)


@router.post("/sources")
def add_source(body: SourceIn, user: dict = Depends(need("news.sources"))) -> dict[str, Any]:
    if body.kind not in ("official", "news"):
        raise HTTPException(status_code=422, detail="kind must be 'official' or 'news'")
    try:
        url = validate_feed_url(body.feed_url)
        items = fetch_feed(url)  # prove it is a working feed before saving it
    except FeedError as e:
        raise HTTPException(status_code=422, detail=f"Feed check failed: {e}") from e
    if not items:
        raise HTTPException(status_code=422, detail="Feed check failed: the feed has no items")
    sectors = ",".join(t.strip().lower() for t in body.sectors.split(",") if t.strip()) or "*"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_sources (name, feed_url, site_url, kind, sectors, created_by)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (feed_url) DO NOTHING RETURNING id
                """,
                (body.name.strip(), url, None, body.kind, sectors, user["email"]),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=409, detail="This feed is already in the list")
            _audit(cur, user, "news_source.add", body.name.strip(), {"feed_url": url, "kind": body.kind})
        conn.commit()
    return {"id": row[0], "items_in_feed": len(items), "approved": False}


class SourcePatch(BaseModel):
    active: bool | None = None
    approved: bool | None = None
    sectors: str | None = Field(default=None, max_length=120)


@router.patch("/sources/{source_id}")
def change_source(source_id: int, body: SourcePatch, user: dict = Depends(need("news.sources", "news.sources.approve"))) -> dict[str, str]:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to update")
    if "approved" in changes:
        require_perm(user, "news.sources.approve")
    if changes.keys() - {"approved"}:
        require_perm(user, "news.sources")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM news_sources WHERE id = %s", (source_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Source not found")
            if "active" in changes:
                cur.execute("UPDATE news_sources SET active = %s WHERE id = %s", (changes["active"], source_id))
            if "approved" in changes:
                cur.execute(
                    "UPDATE news_sources SET approved = %s, approved_by = %s, approved_at = CASE WHEN %s THEN NOW() END WHERE id = %s",
                    (changes["approved"], user["email"] if changes["approved"] else None, changes["approved"], source_id),
                )
            if "sectors" in changes:
                tags = ",".join(t.strip().lower() for t in changes["sectors"].split(",") if t.strip()) or "*"
                cur.execute("UPDATE news_sources SET sectors = %s WHERE id = %s", (tags, source_id))
            _audit(cur, user, "news_source.update", row[0], changes)
        conn.commit()
    return {"status": "updated"}


@router.post("/fetch")
def fetch_now(user: dict = Depends(need("news.publish", "news.sources"))) -> dict[str, Any]:
    result = run_cycle(f"admin:{user['email']}")
    if result.get("status") == "busy":
        raise HTTPException(status_code=409, detail="A fetch is already running. Try again in a minute.")
    return result


# ---------------------------------------------------------------- company keywords
@router.get("/companies")
def company_news_settings(user: dict = Depends(need("news.publish"))) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.name, c.sector, c.news_keywords,
                    (SELECT COUNT(*) FROM news_matches m JOIN news_items i ON i.id = m.item_id
                     WHERE m.company_id = c.id AND m.status = 'suggested' AND i.published_at > NOW() - INTERVAL '10 days')
                FROM companies c ORDER BY c.name
                """
            )
            rows = cur.fetchall()
    return [
        {"id": r[0], "name": r[1], "sector": r[2], "news_keywords": r[3] or "", "waiting": r[4],
         "effective_keywords": company_keywords(r[1], r[2], r[3])}
        for r in rows
    ]


class KeywordsIn(BaseModel):
    news_keywords: str = Field(default="", max_length=600)


@router.put("/companies/{company_id}/keywords")
def set_keywords(company_id: int, body: KeywordsIn, user: dict = Depends(need("news.publish"))) -> dict[str, Any]:
    kws = ", ".join(k.strip() for k in body.news_keywords.split(",") if k.strip())
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE companies SET news_keywords = %s WHERE id = %s RETURNING slug", (kws or None, company_id))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Company not found")
            added = match_recent(cur, company_id)  # re-check recent news straight away
            _audit(cur, user, "news.keywords", row[0], {"news_keywords": kws})
        conn.commit()
    return {"status": "saved", "new_suggestions": added}


# ---------------------------------------------------------------- suggestions
@router.get("/suggestions")
def suggestions(company_id: int | None = None, user: dict = Depends(need("news.publish"))) -> list[dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id, c.id, c.name, c.sector, m.score, m.matched_terms, i.title, i.excerpt, i.url, i.published_at,
                    s.name, s.kind, s.approved
                FROM news_matches m
                JOIN news_items i ON i.id = m.item_id
                JOIN news_sources s ON s.id = i.source_id
                JOIN companies c ON c.id = m.company_id
                WHERE m.status = 'suggested' AND s.active AND i.published_at > NOW() - INTERVAL '10 days'
                  AND (%s::int IS NULL OR c.id = %s::int)
                ORDER BY i.published_at DESC, m.score DESC LIMIT 60
                """,
                (company_id, company_id),
            )
            rows = cur.fetchall()
    return [
        {"id": r[0], "company_id": r[1], "company": r[2], "sector": r[3], "score": r[4], "matched_terms": r[5],
         "title": r[6], "excerpt": r[7] or "", "url": r[8], "published_at": iso(r[9]), "source": r[10],
         "source_kind": r[11], "source_approved": r[12], "suggested_label": suggest_label(r[11], r[6], r[7] or "")}
        for r in rows
    ]


class PublishIn(BaseModel):
    label: str
    title: str = Field(min_length=5, max_length=160)
    summary: str = Field(min_length=10, max_length=800)
    expires_in_days: int = Field(default=14, ge=1, le=180)


@router.post("/suggestions/{match_id}/publish")
def publish_suggestion(match_id: int, body: PublishIn, user: dict = Depends(need("news.publish"))) -> dict[str, Any]:
    label = body.label.upper()
    if label not in UPDATE_LABELS:
        raise HTTPException(status_code=422, detail=f"label must be one of {UPDATE_LABELS}")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.status, m.company_id, c.slug, c.sector, m.matched_terms, i.id, i.url, s.name, s.approved
                FROM news_matches m JOIN news_items i ON i.id = m.item_id JOIN news_sources s ON s.id = i.source_id
                JOIN companies c ON c.id = m.company_id WHERE m.id = %s FOR UPDATE OF m
                """,
                (match_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Suggestion not found")
            status, cid, slug, sector, terms, item_id, url, source, approved = row
            if status != "suggested":
                raise HTTPException(status_code=409, detail=f"Already {status}")
            if not approved:
                raise HTTPException(status_code=403, detail=f"{source} is not an approved source yet. Approve it under Feed sources first.")
            why = f"Mentions {terms}." if terms else None
            cur.execute(
                """
                INSERT INTO sector_updates (company_id, label, title, summary, sector, source, source_url, published_by,
                    news_item_id, why, published_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW() + make_interval(days => %s)) RETURNING id
                """,
                (cid, label, body.title.strip(), body.summary.strip(), sector, source, url, user["full_name"], item_id, why,
                 body.expires_in_days),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "UPDATE news_matches SET status = 'published', sector_update_id = %s, reviewed_by = %s, reviewed_at = NOW() WHERE id = %s",
                (uid, user["email"], match_id),
            )
            # Real news replaces the labelled sample briefs for this company.
            cur.execute(
                """
                UPDATE sector_updates SET expires_at = NOW() WHERE company_id = %s AND published_by IS NULL
                AND source LIKE '%%(sample brief)' AND (expires_at IS NULL OR expires_at > NOW())
                """,
                (cid,),
            )
            _audit(cur, user, "sector_update.publish", slug, {"title": body.title, "source": source, "from_feed": True})
        conn.commit()
    return {"id": uid}


@router.post("/suggestions/{match_id}/dismiss")
def dismiss_suggestion(match_id: int, user: dict = Depends(need("news.publish"))) -> dict[str, str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE news_matches SET status = 'dismissed', reviewed_by = %s, reviewed_at = NOW()
                WHERE id = %s AND status = 'suggested' RETURNING id
                """,
                (user["email"], match_id),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Suggestion not found or already handled")
        conn.commit()
    return {"status": "dismissed"}
