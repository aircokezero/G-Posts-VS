"""
Shared logic used by both the seed script and the scraper,
so duplicate-detection and stat-tracking behave identically regardless
of where a post came from.
"""

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.models import Post, Competitor


def make_fingerprint(post_url: str | None, post_text: str, published_date: datetime | None) -> str:
    """
    Prefers post_url when available (most stable identifier). Falls back to
    normalized text + published_date when no URL exists, so that the SAME
    text posted on a DIFFERENT date is correctly treated as a new post, not
    a duplicate — real businesses often repeat identical weekly specials,
    and that repetition is itself the signal trend analysis is built to surface.
    competitor_id is NOT included here since the DB's unique constraint
    already scopes fingerprints per-competitor.
    """
    if post_url:
        raw = f"url:{post_url}"
    else:
        normalized_text = " ".join(post_text.lower().split())
        date_part = published_date.isoformat() if published_date else "no-date"
        raw = f"text:{normalized_text}|date:{date_part}"
    return hashlib.sha256(raw.encode()).hexdigest()


def refresh_competitor_stats(db: Session, competitor_id: int, mark_scraped: bool = True):
    """
    Recomputes stats from actual data rather than incrementing counters —
    self-correcting by construction, can't drift no matter how many code
    paths touch posts (seed script, scraper, manual edits, etc.).
    """
    post_count = db.query(Post).filter(Post.competitor_id == competitor_id).count()
    update_values = {"total_posts_collected": post_count}
    if mark_scraped:
        update_values["last_scraped_at"] = datetime.now(timezone.utc)
        update_values["last_scrape_status"] = "success"  # added — was never set for real scrapes

    db.query(Competitor).filter(Competitor.id == competitor_id).update(update_values)
    db.commit()