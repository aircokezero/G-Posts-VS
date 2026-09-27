"""
Core database models.

Six tables:
- Project: the container (our profile + client info)
- Competitor: manually added competitor businesses, scoped to a project
- Keyword: discovery keywords, scoped to a project
- Post: the actual scraped Google Maps updates (the repository)
- ScrapeJob: one row per scrape run, used for logs/stats/dashboard
- GeneratedIdea: AI-generated content ideas / complete updates, with dedup support
"""

from datetime import datetime, timezone
from sqlalchemy import (
    String, Text, Integer, Boolean, ForeignKey, DateTime, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    own_business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    own_business_profile_url: Mapped[str] = mapped_column(String(1000), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    competitors: Mapped[list["Competitor"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    keywords: Mapped[list["Keyword"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    posts: Mapped[list["Post"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    scrape_jobs: Mapped[list["ScrapeJob"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    generated_ideas: Mapped[list["GeneratedIdea"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    dashboard_insights: Mapped[dict | None] = mapped_column(JSONB)
    chat_messages: Mapped[list["ChatMessage"]] = relationship(cascade="all, delete-orphan")


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    is_own_business: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scrape_status: Mapped[str | None] = mapped_column(String(50))  # success | failed | needs_verification
    total_posts_collected: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="competitors")
    posts: Mapped[list["Post"]] = relationship(back_populates="competitor", cascade="all, delete-orphan")
    scrape_jobs: Mapped[list["ScrapeJob"]] = relationship(back_populates="competitor", cascade="all, delete-orphan")


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)

    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="keywords")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("competitor_id", "fingerprint", name="uq_competitor_fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)

    post_url: Mapped[str | None] = mapped_column(String(1000))
    post_text: Mapped[str | None] = mapped_column(Text)
    published_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image_urls: Mapped[list] = mapped_column(JSONB, default=list)

    cta: Mapped[str | None] = mapped_column(String(255))
    detected_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    topic: Mapped[str | None] = mapped_column(String(255))
    subtopic: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(100))
    offer_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_reference: Mapped[str | None] = mapped_column(String(255))
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)

    project: Mapped["Project"] = relationship(back_populates="posts")
    competitor: Mapped["Competitor"] = relationship(back_populates="posts")


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    competitor_id: Mapped[int] = mapped_column(ForeignKey("competitors.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(50), default="pending")
    # pending | running | awaiting_manual_verification | success | failed

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    posts_found: Mapped[int] = mapped_column(Integer, default=0)
    new_posts_added: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_skipped: Mapped[int] = mapped_column(Integer, default=0)
    images_downloaded: Mapped[int] = mapped_column(Integer, default=0)

    captcha_encountered: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    project: Mapped["Project"] = relationship(back_populates="scrape_jobs")
    competitor: Mapped["Competitor"] = relationship(back_populates="scrape_jobs")


class GeneratedIdea(Base):
    __tablename__ = "generated_ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)

    kind: Mapped[str] = mapped_column(String(20), default="idea")  # idea | complete_update

    topic: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(500))
    copy_text: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSONB, default=list)
    cta: Mapped[str | None] = mapped_column(String(255))
    image_concept: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(1000))

    embedding: Mapped[list | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="generated_ideas")

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)