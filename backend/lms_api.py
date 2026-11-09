"""100-Day Playbook course (LMS), chapter by chapter (meeting 1, 26 Oct 2026).

    GET   /api/founder/course                               published chapters and lessons, with this founder's progress
    POST  /api/founder/course/lessons/{id}/complete         mark a lesson done (or not done)
    GET   /api/admin/course                                 every chapter and lesson (drafts too) and completion per company
    POST  /api/admin/course/chapters                        add a chapter
    PATCH /api/admin/course/chapters/{id}                   edit, publish/unpublish or move a chapter
    DELETE /api/admin/course/chapters/{id}                  remove a chapter and its lessons
    POST  /api/admin/course/chapters/{id}/lessons           add a lesson
    PATCH /api/admin/course/lessons/{id}                    edit, publish/unpublish or move a lesson
    DELETE /api/admin/course/lessons/{id}                   remove a lesson
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.admin_api import _audit
from backend.audience import visible
from backend.db import get_conn
from backend.playbook import PHASES
from backend.security import auth_session, company_scope, founder_company, iso, need, require_founder, require_founder_or_preview

router = APIRouter(prefix="/api")
PHASE_NAMES = {n: f"{name} · {days}" for n, name, days in PHASES}


class ChapterIn(BaseModel):
    phase_no: int = Field(ge=1, le=4)
    title: str = Field(min_length=3, max_length=160)
    summary: str | None = Field(default=None, max_length=600)
    status: Literal["draft", "published"] = "draft"


class ChapterPatch(BaseModel):
    phase_no: int | None = Field(default=None, ge=1, le=4)
    title: str | None = Field(default=None, min_length=3, max_length=160)
    summary: str | None = Field(default=None, max_length=600)
    status: Literal["draft", "published"] | None = None
    move: Literal["up", "down"] | None = None


class LessonIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=20, max_length=8000)
    resource_slug: str | None = Field(default=None, max_length=80)
    video_url: str | None = Field(default=None, max_length=500)
    minutes: int = Field(default=5, ge=1, le=240)
    status: Literal["draft", "published"] = "draft"


class LessonPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=160)
    body: str | None = Field(default=None, min_length=20, max_length=8000)
    resource_slug: str | None = Field(default=None, max_length=80)
    video_url: str | None = Field(default=None, max_length=500)
    minutes: int | None = Field(default=None, ge=1, le=240)
    status: Literal["draft", "published"] | None = None
    move: Literal["up", "down"] | None = None


class DoneIn(BaseModel):
    done: bool = True


def _check_links(cur, slug: str | None, video: str | None) -> tuple[str | None, str | None]:
    slug = (slug or "").strip() or None
    video = (video or "").strip() or None
    if video and not video.lower().startswith("https://"):
        raise HTTPException(status_code=422, detail="The video link must start with https://")
    if slug:
        cur.execute("SELECT 1 FROM resources WHERE slug = %s AND status = 'approved'", (slug,))
        if not cur.fetchone():
            raise HTTPException(status_code=422, detail="Choose an approved resource from the library")
    return slug, video


# ---------------------------------------------------------------- founder side
@router.get("/founder/course")
def founder_course(user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_founder_or_preview(user)
    cid = founder_company(user)[0]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, phase_no, title, summary FROM lms_chapters WHERE status = 'published' ORDER BY phase_no, sort_order, id")
            chapters = [{"id": r[0], "phase_no": r[1], "phase": PHASE_NAMES.get(r[1], ""), "title": r[2], "summary": r[3], "lessons": []}
                        for r in cur.fetchall()]
            by_id = {c["id"]: c for c in chapters}
            cur.execute(
                f"""
                SELECT l.id, l.chapter_id, l.title, l.body, l.minutes, l.video_url, r.id, r.title, r.placement,
                    EXISTS (SELECT 1 FROM lms_progress p WHERE p.lesson_id = l.id AND p.user_id = %s),
                    EXISTS (SELECT 1 FROM lms_progress p WHERE p.lesson_id = l.id AND p.company_id = %s)
                FROM lms_lessons l
                LEFT JOIN resources r ON r.slug = l.resource_slug AND r.status = 'approved'
                    AND {visible('r')} AND (r.company_id IS NOT NULL OR r.is_portfolio_wide)
                WHERE l.status = 'published' ORDER BY l.chapter_id, l.sort_order, l.id
                """,
                (user["id"], cid, cid),
            )
            for r in cur.fetchall():
                if r[1] in by_id:
                    by_id[r[1]]["lessons"].append({"id": r[0], "title": r[2], "body": r[3], "minutes": r[4], "video_url": r[5],
                                                   "resource_id": r[6], "resource_title": r[7], "resource_is_guide": r[8] == "playbook",
                                                   "done": r[9], "done_by_team": r[10]})
            # Playbook guides: the full manuals behind the lessons, downloaded from the Playbook page.
            cur.execute(
                f"""
                SELECT r.id, r.title, r.description, r.resource_type FROM resources r
                WHERE r.placement = 'playbook' AND r.status = 'approved' AND {visible('r')}
                    AND (r.company_id IS NOT NULL OR r.is_portfolio_wide)
                ORDER BY r.title
                """,
                (cid,),
            )
            guides = [{"id": r[0], "title": r[1], "description": r[2], "type": r[3]} for r in cur.fetchall()]
    chapters = [c for c in chapters if c["lessons"]]
    total = sum(len(c["lessons"]) for c in chapters)
    mine = sum(1 for c in chapters for lesson in c["lessons"] if lesson["done"])
    team = sum(1 for c in chapters for lesson in c["lessons"] if lesson["done_by_team"])
    for n, c in enumerate(chapters, start=1):
        c["number"] = n
        c["done"] = sum(1 for lesson in c["lessons"] if lesson["done"])
    return {"chapters": chapters, "guides": guides, "total": total, "done": mine, "team_done": team,
            "pct": round(100 * mine / total) if total else 0}


@router.post("/founder/course/lessons/{lesson_id}/complete")
def complete_lesson(lesson_id: int, body: DoneIn, user: dict = Depends(auth_session)) -> dict[str, Any]:
    require_founder(user)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT l.title FROM lms_lessons l JOIN lms_chapters c ON c.id = l.chapter_id "
                        "WHERE l.id = %s AND l.status = 'published' AND c.status = 'published'", (lesson_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Lesson not found")
            if body.done:
                cur.execute("INSERT INTO lms_progress (user_id, lesson_id, company_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            (user["id"], lesson_id, user["company_id"]))
            else:
                cur.execute("DELETE FROM lms_progress WHERE user_id = %s AND lesson_id = %s", (user["id"], lesson_id))
            cur.execute("SELECT COUNT(*) FROM lms_lessons l JOIN lms_chapters c ON c.id = l.chapter_id WHERE l.status = 'published' AND c.status = 'published'")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM lms_progress p JOIN lms_lessons l ON l.id = p.lesson_id JOIN lms_chapters c ON c.id = l.chapter_id "
                        "WHERE p.user_id = %s AND l.status = 'published' AND c.status = 'published'", (user["id"],))
            done = cur.fetchone()[0]
        conn.commit()
    return {"done": body.done, "pct": round(100 * done / total) if total else 0, "completed": done, "total": total}


# ---------------------------------------------------------------- Demo Ventures side
@router.get("/admin/course")
def admin_course(user: dict = Depends(need("lms.manage", "companies.view"))) -> dict[str, Any]:
    allowed = company_scope(user, "companies.view")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, phase_no, sort_order, title, summary, status, created_by, updated_at FROM lms_chapters ORDER BY phase_no, sort_order, id")
            chapters = [{"id": r[0], "phase_no": r[1], "phase": PHASE_NAMES.get(r[1], ""), "sort_order": r[2], "title": r[3], "summary": r[4],
                         "status": r[5], "created_by": r[6], "updated_at": iso(r[7]), "lessons": []} for r in cur.fetchall()]
            by_id = {c["id"]: c for c in chapters}
            cur.execute(
                """
                SELECT l.id, l.chapter_id, l.sort_order, l.title, l.body, l.resource_slug, l.video_url, l.minutes, l.status,
                    (SELECT COUNT(DISTINCT p.company_id) FROM lms_progress p WHERE p.lesson_id = l.id)
                FROM lms_lessons l ORDER BY l.chapter_id, l.sort_order, l.id
                """
            )
            for r in cur.fetchall():
                by_id[r[1]]["lessons"].append({"id": r[0], "sort_order": r[2], "title": r[3], "body": r[4], "resource_slug": r[5],
                                               "video_url": r[6], "minutes": r[7], "status": r[8], "companies_done": r[9]})
            cur.execute("SELECT COUNT(*) FROM lms_lessons l JOIN lms_chapters c ON c.id = l.chapter_id WHERE l.status = 'published' AND c.status = 'published'")
            total = cur.fetchone()[0]
            cur.execute(
                """
                SELECT c.id, c.name, COUNT(DISTINCT p.lesson_id) FILTER (WHERE l.status = 'published' AND ch.status = 'published'),
                    MAX(p.completed_at)
                FROM companies c LEFT JOIN lms_progress p ON p.company_id = c.id
                LEFT JOIN lms_lessons l ON l.id = p.lesson_id LEFT JOIN lms_chapters ch ON ch.id = l.chapter_id
                WHERE c.status = 'active' GROUP BY c.id, c.name ORDER BY c.name
                """
            )
            progress = [{"company_id": r[0], "company": r[1], "done": r[2], "total": total, "pct": round(100 * r[2] / total) if total else 0,
                         "last": iso(r[3])} for r in cur.fetchall() if allowed is None or r[0] in allowed]
            cur.execute("SELECT slug, title, id FROM resources WHERE status = 'approved' AND slug IS NOT NULL ORDER BY title")
            resources = [{"slug": r[0], "title": r[1], "id": r[2]} for r in cur.fetchall()]
    return {"chapters": chapters, "progress": progress, "resources": resources, "phases": PHASE_NAMES,
            "can_edit": "lms.manage" in (user.get("permissions") or [])}


def _move(cur, table: str, parent_col: str, item_id: int, direction: str) -> None:
    """Swap an item with its neighbour inside the same phase (chapters) or chapter (lessons)."""
    cur.execute(f"SELECT {parent_col}, sort_order FROM {table} WHERE id = %s", (item_id,))
    parent, order = cur.fetchone()
    cmp, sort = ("<", "DESC") if direction == "up" else (">", "ASC")
    cur.execute(f"SELECT id, sort_order FROM {table} WHERE {parent_col} = %s AND (sort_order, id) {cmp} (%s, %s) "
                f"ORDER BY sort_order {sort}, id {sort} LIMIT 1", (parent, order, item_id))
    other = cur.fetchone()
    if other:
        new_mine = other[1] if other[1] != order else order + (-1 if direction == "up" else 1)
        cur.execute(f"UPDATE {table} SET sort_order = %s WHERE id = %s", (order, other[0]))
        cur.execute(f"UPDATE {table} SET sort_order = %s WHERE id = %s", (new_mine, item_id))


@router.post("/admin/course/chapters")
def add_chapter(body: ChapterIn, user: dict = Depends(need("lms.manage"))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM lms_chapters WHERE phase_no = %s", (body.phase_no,))
            order = cur.fetchone()[0]
            cur.execute("INSERT INTO lms_chapters (phase_no, sort_order, title, summary, status, created_by) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                        (body.phase_no, order, body.title.strip(), (body.summary or "").strip() or None, body.status, user["full_name"]))
            cid = cur.fetchone()[0]
            _audit(cur, user, "course.chapter.add", body.title.strip(), {"status": body.status})
        conn.commit()
    return {"id": cid}


@router.patch("/admin/course/chapters/{chapter_id}")
def change_chapter(chapter_id: int, body: ChapterPatch, user: dict = Depends(need("lms.manage"))) -> dict[str, str]:
    changes = body.model_dump(exclude_none=True, exclude={"move"})
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title FROM lms_chapters WHERE id = %s", (chapter_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Chapter not found")
            for col, val in changes.items():  # columns come from the pydantic model
                cur.execute(f"UPDATE lms_chapters SET {col} = %s, updated_at = NOW() WHERE id = %s",
                            (val.strip() if isinstance(val, str) and col != "status" else val, chapter_id))
            if body.move:
                _move(cur, "lms_chapters", "phase_no", chapter_id, body.move)
            if not changes and not body.move:
                raise HTTPException(status_code=422, detail="Nothing to change")
            _audit(cur, user, "course.chapter.edit", changes.get("title") or row[0], {k: v for k, v in changes.items() if k != "summary"})
        conn.commit()
    return {"status": "updated"}


@router.delete("/admin/course/chapters/{chapter_id}")
def delete_chapter(chapter_id: int, user: dict = Depends(need("lms.manage"))) -> dict[str, str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM lms_chapters WHERE id = %s RETURNING title", (chapter_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Chapter not found")
            _audit(cur, user, "course.chapter.delete", row[0])
        conn.commit()
    return {"status": "deleted"}


@router.post("/admin/course/chapters/{chapter_id}/lessons")
def add_lesson(chapter_id: int, body: LessonIn, user: dict = Depends(need("lms.manage"))) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title FROM lms_chapters WHERE id = %s", (chapter_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Chapter not found")
            slug, video = _check_links(cur, body.resource_slug, body.video_url)
            cur.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM lms_lessons WHERE chapter_id = %s", (chapter_id,))
            order = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO lms_lessons (chapter_id, sort_order, title, body, resource_slug, video_url, minutes, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (chapter_id, order, body.title.strip(), body.body.strip(), slug, video, body.minutes, body.status, user["full_name"]),
            )
            lid = cur.fetchone()[0]
            _audit(cur, user, "course.lesson.add", body.title.strip(), {"status": body.status})
        conn.commit()
    return {"id": lid}


@router.patch("/admin/course/lessons/{lesson_id}")
def change_lesson(lesson_id: int, body: LessonPatch, user: dict = Depends(need("lms.manage"))) -> dict[str, str]:
    changes = body.model_dump(exclude_unset=True, exclude={"move"})
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, resource_slug, video_url FROM lms_lessons WHERE id = %s", (lesson_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Lesson not found")
            if "resource_slug" in changes or "video_url" in changes:
                slug, video = _check_links(cur, changes.get("resource_slug", row[1]), changes.get("video_url", row[2]))
                changes["resource_slug"], changes["video_url"] = slug, video
            for col, val in changes.items():  # columns come from the pydantic model
                if val is None and col not in ("resource_slug", "video_url"):
                    continue
                cur.execute(f"UPDATE lms_lessons SET {col} = %s, updated_at = NOW() WHERE id = %s",
                            (val.strip() if isinstance(val, str) and col not in ("status",) else val, lesson_id))
            if body.move:
                _move(cur, "lms_lessons", "chapter_id", lesson_id, body.move)
            if not changes and not body.move:
                raise HTTPException(status_code=422, detail="Nothing to change")
            _audit(cur, user, "course.lesson.edit", changes.get("title") or row[0], {k: v for k, v in changes.items() if k != "body"})
        conn.commit()
    return {"status": "updated"}


@router.delete("/admin/course/lessons/{lesson_id}")
def delete_lesson(lesson_id: int, user: dict = Depends(need("lms.manage"))) -> dict[str, str]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM lms_lessons WHERE id = %s RETURNING title", (lesson_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Lesson not found")
            _audit(cur, user, "course.lesson.delete", row[0])
        conn.commit()
    return {"status": "deleted"}
