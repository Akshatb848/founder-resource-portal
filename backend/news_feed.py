"""Live sector news: read approved RSS/Atom feeds, match items to companies, queue them for review.

How it works (near real time, not push):
1. Every NEWS_FETCH_MINUTES the API reads each active feed in news_sources (or run
   `python -m backend.scripts.fetch_news` from cron / a systemd timer on the VM).
2. Only the headline, a short excerpt, the link and the date are stored (news_items); no full
   articles are copied, so the portal links back to the publisher instead of republishing it.
3. Recent items are matched to each company by sector and keywords (news_matches, status 'suggested').
4. An admin publishes a suggestion as a sector update, or dismisses it. Publishing is only allowed
   from sources Demo Ventures has approved. Nothing reaches a founder automatically.
"""
from __future__ import annotations

import hashlib
import html
import ipaddress
import logging
import re
import socket
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from defusedxml import ElementTree as SafeET

from backend.config import NEWS_FETCH_ENABLED, NEWS_FETCH_MINUTES, NEWS_SUGGESTIONS_ENABLED
from backend.db import get_conn

log = logging.getLogger("founder_portal.news")

USER_AGENT = "FounderPortal/0.2 (sector news reader)"
MAX_FEED_BYTES = 3_000_000
FETCH_TIMEOUT = 20
MATCH_WINDOW_DAYS = 10  # only recent news is suggested
LOCK_KEY = 42017  # Postgres advisory lock: one fetch cycle at a time across workers / cron
ATOM = "{http://www.w3.org/2005/Atom}"

# Starter list (verified to respond on 21 Oct 2026). All start "pending approval": Demo Ventures signs off
# each source in the admin portal before anything from it can be published.
STARTER_SOURCES = [
    # name, feed_url, site_url, kind, sectors
    ("RBI press releases", "https://www.rbi.org.in/pressreleases_rss.xml", "https://www.rbi.org.in", "official", "*"),
    ("RBI notifications", "https://www.rbi.org.in/notifications_rss.xml", "https://www.rbi.org.in", "official", "*"),
    ("SEBI updates", "https://www.sebi.gov.in/sebirss.xml", "https://www.sebi.gov.in", "official", "*"),
    ("ET EnergyWorld", "https://energy.economictimes.indiatimes.com/rss/topstories", "https://energy.economictimes.indiatimes.com", "news", "energy,ev,cleantech"),
    ("Mercom India", "https://www.mercomindia.com/feed", "https://www.mercomindia.com", "news", "energy,ev,cleantech"),
    ("EVreporter", "https://evreporter.com/feed/", "https://evreporter.com", "news", "ev,mobility"),
    ("EMobility+", "https://emobilityplus.com/feed/", "https://emobilityplus.com", "news", "ev,mobility"),
    ("Inc42", "https://inc42.com/feed/", "https://inc42.com", "news", "*"),
    ("YourStory", "https://yourstory.com/feed", "https://yourstory.com", "news", "*"),
    ("BusinessLine: Companies", "https://www.thehindubusinessline.com/companies/feeder/default.rss", "https://www.thehindubusinessline.com", "news", "*"),
    ("BusinessLine: Economy", "https://www.thehindubusinessline.com/economy/feeder/default.rss", "https://www.thehindubusinessline.com", "news", "*"),
    ("Mint: Companies", "https://www.livemint.com/rss/companies", "https://www.livemint.com", "news", "*"),
]

# Default keywords per sector tag; each company adds its own in companies.news_keywords.
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "ev": ["electric vehicle", "EV", "e-mobility", "electric two-wheeler", "electric three-wheeler", "electric bus",
           "charging infrastructure", "EV charging", "battery swapping", "PM E-DRIVE", "FAME"],
    "energy": ["battery storage", "energy storage", "BESS", "lithium-ion", "cell manufacturing", "ACC PLI",
               "renewable energy", "green hydrogen", "power tariff"],
    "mobility": ["electric vehicle", "fleet electrification", "last-mile", "logistics fleet"],
    "fintech": ["RBI", "NBFC", "UPI", "digital lending", "payment aggregator", "KYC", "account aggregator"],
    "saas": ["SaaS", "enterprise software", "data protection", "DPDP"],
    "health": ["healthtech", "CDSCO", "medical device", "ABDM"],
    "agri": ["agritech", "FPO", "agriculture"],
    "d2c": ["D2C", "consumer brand", "quick commerce", "e-commerce"],
}
FUNDING_WORDS = ("raises", "funding", "series a", "series b", "series c", "seed round", "pre-series", "investment round", "fundraise")
POLICY_WORDS = ("policy", "scheme", "ministry", "government", "subsidy", "incentive", "budget", "cabinet")
REG_WORDS = ("circular", "notification", "regulation", "guidelines", "compliance", "framework", "directions", "amendment")


class FeedError(Exception):
    pass


# ---------------------------------------------------------------- safe fetching
def _check_host(url: str) -> None:
    """Block internal addresses so an admin-entered feed URL can't reach the VM's private network."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise FeedError("Feed URL must use https://")
    if parts.port not in (None, 443):
        raise FeedError("Feed URL must use the standard https port")
    host = parts.hostname or ""
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise FeedError(f"Cannot resolve {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise FeedError("Feed URL points to a private or local address")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        _check_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect())


def validate_feed_url(url: str) -> str:
    url = (url or "").strip()
    if len(url) > 500:
        raise FeedError("Feed URL is too long")
    _check_host(url)
    return url


_BOILERPLATE = re.compile(
    r"The post .{0,300}? appeared first (?:at|on) .{0,120}?\.(?=\s|$)|\[(?:…|\.\.\.)\]|Continue reading.*$|Read more.*$|Listen to this article|From: Mercom Capital Group",
    re.IGNORECASE,
)


def _clean(text: str | None, limit: int, excerpt: bool = True) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text, cut_footer = _BOILERPLATE.subn(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([a-z])\.([A-Z])", r"\1. \2", text)  # "Maharashtra.The" → "Maharashtra. The"
    tail = re.search(r"\s+The post .*$", text)  # a feed's own cut-off "The post <title>…" footer
    if tail or (cut_footer and not text.endswith((".", "?", "!"))):
        text = text[: tail.start()].rstrip() if tail else text
        ends = [m.end() for m in re.finditer(r"[.?!](?=\s|$)", text)]  # sentence ends, not "1.26"
        text = text[: ends[-1]] if ends and ends[-1] >= 60 else text.rstrip(" ,;:-") + "…"
    if len(text) <= limit:
        # A feed that cuts its own excerpt mid-sentence gets an ellipsis so it never reads as complete.
        return text if not excerpt or not text or text.endswith((".", "?", "!", "…", '"', "”", ")")) else text.rstrip(" ,;:-") + "…"
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:.-") + "…"


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        d = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%d %b, %Y %z", "%d %b %Y %H:%M:%S %z", "%Y-%m-%d"):
            try:
                d = datetime.strptime(raw.replace("Z", "+00:00"), fmt)
                break
            except ValueError:
                continue
    if d is None:
        return None
    if d.tzinfo is None:  # Indian feeds without a zone are IST
        d = d.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    return d.astimezone(timezone.utc)


def fetch_feed(url: str) -> list[dict[str, Any]]:
    """Return [{title, url, excerpt, published_at}] for one RSS 2.0 or Atom feed."""
    validate_feed_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.5"})
    try:
        with _opener.open(req, timeout=FETCH_TIMEOUT) as r:
            data = r.read(MAX_FEED_BYTES + 1)
    except FeedError:
        raise
    except Exception as e:  # network, HTTP status, TLS
        raise FeedError(f"{type(e).__name__}: {str(e)[:150]}") from e
    if len(data) > MAX_FEED_BYTES:
        raise FeedError("Feed is larger than 3 MB")
    try:
        root = SafeET.fromstring(data)
    except Exception as e:
        raise FeedError(f"Not a valid RSS/Atom feed ({type(e).__name__})") from e

    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for it in root.iter("item"):
        link = (it.findtext("link") or it.findtext("guid") or "").strip()
        out.append({
            "title": it.findtext("title"),
            "url": link,
            "excerpt": it.findtext("description"),
            "published_at": _parse_date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")),
        })
    for it in root.iter(f"{ATOM}entry"):
        link_el = next((l for l in it.findall(f"{ATOM}link") if l.get("rel") in (None, "alternate")), None)
        out.append({
            "title": it.findtext(f"{ATOM}title"),
            "url": (link_el.get("href") if link_el is not None else "") or "",
            "excerpt": it.findtext(f"{ATOM}summary") or it.findtext(f"{ATOM}content"),
            "published_at": _parse_date(it.findtext(f"{ATOM}published") or it.findtext(f"{ATOM}updated")),
        })
    items = []
    for x in out:
        title = _clean(x["title"], 300, excerpt=False)
        link = x["url"].strip()
        if not title or not link.startswith(("https://", "http://")):
            continue
        published = x["published_at"] or now
        items.append({"title": title, "url": link[:1000], "excerpt": _clean(x["excerpt"], 320),
                      "published_at": min(published, now)})
    return items


# ---------------------------------------------------------------- matching
def _sector_tags(sector: str | None) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", (sector or "").lower()))
    tags = {t for t in SECTOR_KEYWORDS if t in words}
    if "electric" in words or "mobility" in words:
        tags.add("ev")
    if "clean" in words or "climate" in words or "cleantech" in words:
        tags.add("energy")
    return tags


def company_keywords(name: str, sector: str | None, extra: str | None) -> list[str]:
    kws: list[str] = []
    for tag in sorted(_sector_tags(sector)):
        kws += SECTOR_KEYWORDS[tag]
    kws += [k.strip() for k in (extra or "").split(",") if len(k.strip()) >= 2]
    seen, unique = set(), []
    for k in kws:
        if k.lower() not in seen:
            seen.add(k.lower())
            unique.append(k)
    return unique


def _kw_regex(kw: str) -> re.Pattern:
    # Whole-word, case-insensitive; short acronyms (EV, RBI) must match case exactly to avoid noise.
    flags = 0 if (kw.isupper() and len(kw) <= 4) else re.IGNORECASE
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(kw) + r"s?(?![A-Za-z0-9])", flags)


def score_item(title: str, excerpt: str, name: str, keywords: list[str]) -> tuple[int, list[str]]:
    score, hits = 0, []
    if name and _kw_regex(name).search(f"{title} {excerpt}"):
        score += 6
        hits.append(name)
    for kw in keywords:
        rx = _kw_regex(kw)
        if rx.search(title):
            score += 3
            hits.append(kw)
        elif rx.search(excerpt):
            score += 1
            hits.append(kw)
    return score, hits


def suggest_label(kind: str, title: str, excerpt: str) -> str:
    text = f"{title} {excerpt}".lower()
    if any(w in text for w in FUNDING_WORDS):
        return "FUNDING"
    if kind == "official" or any(w in text for w in REG_WORDS):
        return "REGULATORY" if any(w in text for w in REG_WORDS) else "POLICY"
    if any(w in text for w in POLICY_WORDS):
        return "POLICY"
    return "MARKET"


def _source_fits(source_sectors: str, company_sector: str | None) -> bool:
    tags = {t.strip().lower() for t in (source_sectors or "*").split(",") if t.strip()}
    if not tags or "*" in tags:
        return True
    return bool(tags & (_sector_tags(company_sector) | set(re.findall(r"[a-z0-9]+", (company_sector or "").lower()))))


def match_recent(cur, company_id: int | None = None) -> int:
    """Suggest recent items to companies. Existing matches (any status) are never duplicated."""
    cur.execute(
        "SELECT id, name, sector, news_keywords FROM companies" + (" WHERE id = %s" if company_id else ""),
        (company_id,) if company_id else (),
    )
    companies = cur.fetchall()
    cur.execute(
        """
        SELECT i.id, i.title, COALESCE(i.excerpt, ''), s.sectors FROM news_items i
        JOIN news_sources s ON s.id = i.source_id
        WHERE s.active AND i.published_at > NOW() - make_interval(days => %s)
        """,
        (MATCH_WINDOW_DAYS,),
    )
    items = cur.fetchall()
    created = 0
    for cid, name, sector, extra in companies:
        kws = company_keywords(name, sector, extra)
        if not kws:
            continue
        for item_id, title, excerpt, sectors in items:
            if not _source_fits(sectors, sector):
                continue
            score, hits = score_item(title, excerpt, name, kws)
            if score < 3:  # at least one keyword in the headline (or the company name)
                continue
            cur.execute(
                """
                INSERT INTO news_matches (item_id, company_id, score, matched_terms) VALUES (%s, %s, %s, %s)
                ON CONFLICT (item_id, company_id) DO NOTHING
                """,
                (item_id, cid, score, ", ".join(hits[:6])),
            )
            created += cur.rowcount
    return created


# ---------------------------------------------------------------- one cycle
def _url_hash(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    query = "&".join(sorted(p for p in parts.query.split("&") if p and not p.lower().startswith("utm_")))
    norm = urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))
    return hashlib.sha256(norm.encode()).hexdigest()


def run_cycle(trigger: str = "schedule", source_id: int | None = None) -> dict[str, Any]:
    """Fetch active feeds, store new items, create suggestions. Safe to run from several processes."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            if not cur.fetchone()[0]:
                return {"status": "busy", "detail": "Another fetch is running"}
            try:
                return _cycle(conn, cur, trigger, source_id)
            finally:
                cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
                conn.commit()


def _cycle(conn, cur, trigger: str, source_id: int | None) -> dict[str, Any]:
    cur.execute(
        "SELECT id, feed_url FROM news_sources WHERE active" + (" AND id = %s" if source_id else "") + " ORDER BY id",
        (source_id,) if source_id else (),
    )
    sources = cur.fetchall()
    cur.execute("INSERT INTO news_fetch_runs (trigger) VALUES (%s) RETURNING id", (trigger,))
    run_id = cur.fetchone()[0]
    conn.commit()

    def work(src):
        try:
            return src, fetch_feed(src[1]), None
        except FeedError as e:
            return src, [], str(e)
        except Exception as e:  # never let one feed stop the cycle
            return src, [], f"{type(e).__name__}: {str(e)[:150]}"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(work, sources))

    ok = failed = new_items = 0
    for (sid, _), items, err in results:
        if err:
            failed += 1
            cur.execute(
                "UPDATE news_sources SET last_fetched_at = NOW(), last_status = 'error', last_error = %s WHERE id = %s",
                (err, sid),
            )
            continue
        ok += 1
        for it in items:
            cur.execute(
                """
                INSERT INTO news_items (source_id, url_hash, title, excerpt, url, published_at)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (url_hash) DO NOTHING
                """,
                (sid, _url_hash(it["url"]), it["title"], it["excerpt"], it["url"], it["published_at"]),
            )
            new_items += cur.rowcount
        cur.execute(
            "UPDATE news_sources SET last_fetched_at = NOW(), last_status = %s, last_error = NULL WHERE id = %s",
            (f"ok · {len(items)} items in feed", sid),
        )
    suggestions = match_recent(cur)
    # Keep the store small: items older than 60 days that were never published are removed.
    cur.execute(
        """
        DELETE FROM news_items i WHERE i.published_at < NOW() - INTERVAL '60 days'
        AND NOT EXISTS (SELECT 1 FROM sector_updates s WHERE s.news_item_id = i.id)
        """
    )
    cur.execute(
        """
        UPDATE news_fetch_runs SET finished_at = NOW(), sources_ok = %s, sources_failed = %s, new_items = %s,
            new_suggestions = %s WHERE id = %s
        """,
        (ok, failed, new_items, suggestions, run_id),
    )
    conn.commit()
    summary = {"status": "ok", "sources_ok": ok, "sources_failed": failed, "new_items": new_items, "new_suggestions": suggestions}
    log.info("news cycle (%s): %s", trigger, summary)
    return summary


# ---------------------------------------------------------------- background schedule inside the API
_stop = threading.Event()
_thread: threading.Thread | None = None


def _loop() -> None:
    if _stop.wait(15):  # let the API finish starting first
        return
    while not _stop.is_set():
        try:
            run_cycle("schedule")
        except Exception:  # database down etc.; try again next interval
            log.exception("news cycle failed")
        if _stop.wait(max(5, NEWS_FETCH_MINUTES) * 60):
            return


def start_scheduler() -> None:
    global _thread
    if not (NEWS_FETCH_ENABLED and NEWS_SUGGESTIONS_ENABLED) or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="news-fetch", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()


def scheduler_running() -> bool:
    return bool(_thread and _thread.is_alive())


def seed_starter_sources(cur) -> None:
    for name, feed, site, kind, sectors in STARTER_SOURCES:
        cur.execute(
            """
            INSERT INTO news_sources (name, feed_url, site_url, kind, sectors) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (feed_url) DO NOTHING
            """,
            (name, feed, site, kind, sectors),
        )


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    print(run_cycle("manual"))


def clean_stored_excerpts(cur) -> int:
    """Re-apply the excerpt clean-up to stored items (used after the clean-up rules change)."""
    cur.execute("SELECT id, excerpt FROM news_items WHERE excerpt IS NOT NULL")
    changed = 0
    for item_id, excerpt in cur.fetchall():
        cleaned = _clean(excerpt, 320)
        if cleaned != excerpt:
            cur.execute("UPDATE news_items SET excerpt = %s WHERE id = %s", (cleaned, item_id))
            changed += 1
    return changed
