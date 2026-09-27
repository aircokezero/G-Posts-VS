"""
Scraper entry point. Usage: python -m scraper.run <project_id>
Scrapes the own-business profile first, then every competitor.
"""

import sys
import time
from datetime import datetime, timezone

from core.db import SessionLocal
from core.models import Competitor, Post, ScrapeJob
from core.services import make_fingerprint, refresh_competitor_stats
from scraper.config import get_driver
from scraper.captcha import looks_like_captcha_or_block
from scraper.nav import build_posts_url, extract_place_id
from scraper.post_scraper import extract_posts_from_profile


def _json_safe(raw: dict) -> dict:
    """raw_data is stored as JSONB and may contain a live datetime object
    (published_date) that Python's default JSON serializer can't handle —
    convert it to a plain string before it touches the DB layer."""
    safe = dict(raw)
    if isinstance(safe.get("published_date"), datetime):
        safe["published_date"] = safe["published_date"].isoformat()
    return safe


def scrape_competitor(db, driver, competitor: Competitor, project_id: int):
    job = ScrapeJob(project_id=project_id, competitor_id=competitor.id, status="running", started_at=datetime.now(timezone.utc))
    db.add(job)
    db.commit()

    try:
        driver.get(competitor.profile_url)
        time.sleep(3)

        if looks_like_captcha_or_block(driver):
            job.status = "awaiting_manual_verification"
            job.captcha_encountered = True
            db.commit()
            input(f"\nCAPTCHA/verification detected for {competitor.name}. Solve it in the browser window, then press Enter here to continue...")
            if looks_like_captcha_or_block(driver):
                job.status = "failed"
                job.error_message = "Still blocked after manual verification attempt."
                job.ended_at = datetime.now(timezone.utc)
                db.commit()
                return

        resolved_url = driver.current_url
        
        place_id = extract_place_id(resolved_url)
        if place_id:
            duplicate = db.query(Competitor).filter(
                Competitor.project_id == project_id,
                Competitor.place_id == place_id,
                Competitor.id != competitor.id,
            ).first()
            if duplicate:
                job.status = "failed"
                job.error_message = f"Duplicate business detected — same as competitor '{duplicate.name}' (id={duplicate.id}). Skipped to avoid double-counting."
                job.ended_at = datetime.now(timezone.utc)
                db.commit()
                return
            competitor.place_id = place_id
            db.commit()

        posts_url = build_posts_url(resolved_url)
        if not posts_url:
            job.status = "failed"
            job.error_message = f"Could not derive a posts URL from the resolved page ({resolved_url[:200]}...). This may not be a valid Google Maps business profile."
            job.ended_at = datetime.now(timezone.utc)
            db.commit()
            return

        driver.get(posts_url)
        time.sleep(2)

        raw_posts = extract_posts_from_profile(driver)

        new_count = 0
        dup_count = 0
        for raw in raw_posts:
            fingerprint = make_fingerprint(raw.get("post_url"), raw["post_text"], raw.get("published_date"))
            exists = db.query(Post).filter(Post.competitor_id == competitor.id, Post.fingerprint == fingerprint).first()
            if exists:
                dup_count += 1
                continue

            post = Post(
                project_id=project_id,
                competitor_id=competitor.id,
                post_url=raw.get("post_url"),
                post_text=raw["post_text"],
                published_date=raw.get("published_date"),
                image_urls=raw.get("image_urls", []),
                cta=raw.get("cta"),
                fingerprint=fingerprint,
                source_reference="live_scrape",
                raw_data=_json_safe(raw),
            )
            db.add(post)
            new_count += 1

        db.commit()
        refresh_competitor_stats(db, competitor.id)

        job.status = "success"
        job.posts_found = len(raw_posts)
        job.new_posts_added = new_count
        job.duplicates_skipped = dup_count
        job.ended_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        db.rollback()
        job.status = "failed"
        job.error_message = str(e)
        job.ended_at = datetime.now(timezone.utc)
        db.commit()
        db.query(Competitor).filter(Competitor.id == competitor.id).update({"last_scrape_status": "failed"})
        db.commit()
        print(f"Failed scraping {competitor.name}: {e}")


def run(project_id: int):
    db = SessionLocal()
    driver = get_driver()

    competitors = (
        db.query(Competitor)
        .filter(Competitor.project_id == project_id)
        .order_by(Competitor.is_own_business.desc(), Competitor.created_at)
        .all()
    )

    for competitor in competitors:
        print(f"Scraping: {competitor.name}{' (own business)' if competitor.is_own_business else ''}")
        scrape_competitor(db, driver, competitor, project_id)

    driver.quit()
    db.close()
    print("Scrape run complete.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scraper.run <project_id>")
        sys.exit(1)
    run(int(sys.argv[1]))