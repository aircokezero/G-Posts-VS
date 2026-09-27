"""
Dashboard "deliverable" logic: coverage-gap and posting-frequency data,
plus cached natural-language insights that only regenerate when the
underlying data actually changes (via a content hash), not on every page load.
"""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from core.models import Post, Competitor, Project
from core.taxonomy import TOPICS


def compute_gap_data(db: Session, project_id: int) -> dict:
    """Per-topic: % of competitors who've posted it, vs whether the own
    business has ever posted it. 'Other' excluded — it's a catch-all,
    not a real actionable content category."""
    competitor_count = db.query(Competitor).filter(
        Competitor.project_id == project_id, Competitor.is_own_business == False
    ).count()

    competitor_topic_rows = (
        db.query(Post.topic, func.count(func.distinct(Post.competitor_id)).label("cc"))
        .join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Post.topic.isnot(None),
                Post.topic != "Other", Competitor.is_own_business == False)
        .group_by(Post.topic).all()
    )
    competitor_topic_pct = {
        r.topic: round((r.cc / competitor_count) * 100) if competitor_count else 0
        for r in competitor_topic_rows
    }

    own_topics = set(
        t[0] for t in
        db.query(Post.topic).join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Competitor.is_own_business == True, Post.topic.isnot(None))
        .distinct().all()
    )

    topics, competitor_pct, own_pct = [], [], []
    for topic in TOPICS:
        if topic == "Other" or topic not in competitor_topic_pct:
            continue  # only show topics with at least one competitor post, per requirement
        topics.append(topic)
        competitor_pct.append(competitor_topic_pct[topic])
        own_pct.append(100 if topic in own_topics else 0)

    return {"topics": topics, "competitor_pct": competitor_pct, "own_pct": own_pct}


def compute_frequency_data(db: Session, project_id: int) -> dict:
    """Weekly post counts, own vs. competitor average (normalized per-competitor
    so a single 'own' series is fairly comparable to the competitor group)."""
    competitor_count = db.query(Competitor).filter(
        Competitor.project_id == project_id, Competitor.is_own_business == False
    ).count()

    rows = (
        db.query(
            func.date_trunc("week", Post.published_date).label("week"),
            Competitor.is_own_business,
            func.count(Post.id).label("cnt"),
        )
        .join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Post.published_date.isnot(None))
        .group_by("week", Competitor.is_own_business)
        .order_by("week")
        .all()
    )

    buckets: dict[str, dict[str, int]] = {}
    for week, is_own, cnt in rows:
        key = week.date().isoformat()
        buckets.setdefault(key, {"own": 0, "comp": 0})
        buckets[key]["own" if is_own else "comp"] += cnt

    weeks = sorted(buckets.keys())
    own_series = [buckets[w]["own"] for w in weeks]
    competitor_series = [
        round(buckets[w]["comp"] / competitor_count, 1) if competitor_count else 0
        for w in weeks
    ]

    return {"weeks": weeks, "own_series": own_series, "competitor_series": competitor_series}


def _hash_data(data: dict) -> str:
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def get_or_generate_insight(db: Session, project: Project, kind: str, data: dict, generator_fn) -> str | None:
    new_hash = _hash_data(data)
    insights = dict(project.dashboard_insights or {})  # real copy, not the same reference
    cached = insights.get(kind)

    if cached and cached.get("hash") == new_hash:
        return cached.get("text")

    try:
        text = generator_fn(data)
    except Exception as e:
        print(f"Insight generation failed for '{kind}': {e}")
        return cached.get("text") if cached else None

    insights[kind] = {
        "text": text,
        "hash": new_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    project.dashboard_insights = insights
    flag_modified(project, "dashboard_insights")  # forces SQLAlchemy to write it regardless of reference identity
    db.add(project)
    db.commit()
    return text