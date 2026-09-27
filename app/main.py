"""
FastAPI application entrypoint.
"""

import base64
from supabase import create_client
from collections import Counter
from datetime import datetime, timezone, time as dtime
from fastapi import FastAPI, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import distinct, func
from core.db import get_db
import json as json_module
import subprocess
import sys
import os

from core.models import Project, Competitor, Post, Keyword, GeneratedIdea, ScrapeJob, GeneratedIdea, ChatMessage
from core.insights import compute_gap_data, compute_frequency_data, get_or_generate_insight
from core.llm import analyze_posts_batch, embed_text, cosine_similarity, generate_content, generate_image, generate_gap_insight, generate_frequency_insight, generate_starter_questions, generate_chat_response
from core.taxonomy import TOPICS

DAILY_GENERATION_LIMIT = 50
DAILY_CHAT_LIMIT = 15
DAILY_IMAGE_LIMIT = 10

app = FastAPI(title="Google Maps Competitor Intelligence Tool")
templates = Jinja2Templates(directory="app/templates")


@app.get("/")
def root(request: Request):
    return templates.TemplateResponse(request, "landing.html", {})


@app.get("/projects")
def projects_page(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(request, "projects.html", {"projects": projects})


@app.get("/projects/{project_id}")
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    competitors = (
        db.query(Competitor)
        .filter(Competitor.project_id == project_id)
        .order_by(Competitor.is_own_business.desc(), Competitor.created_at)
        .all()
    )
    keywords = db.query(Keyword).filter(Keyword.project_id == project_id).all()
    return templates.TemplateResponse(
        request, "project_detail.html",
        {"project": project, "competitors": competitors, "keywords": keywords},
    )


@app.get("/projects/{project_id}/generate")
def generate_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    ideas = db.query(GeneratedIdea).filter(GeneratedIdea.project_id == project_id).order_by(GeneratedIdea.created_at.desc()).all()

    analyzed_post_count = db.query(Post).filter(
        Post.project_id == project_id, Post.analyzed_at.isnot(None)
    ).count()

    return templates.TemplateResponse(request, "generate.html",
        {"project": project, "ideas": ideas, "topics": TOPICS, "has_grounding_data": analyzed_post_count > 0})


@app.get("/posts")
def posts_page(
    request: Request,
    project_id: str | None = None,
    competitor_id: str | None = None,
    topic: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    project_id = int(project_id) if project_id else None
    competitor_id = int(competitor_id) if competitor_id else None

    query = db.query(Post)

    if project_id:
        query = query.filter(Post.project_id == project_id)
    if competitor_id:
        query = query.filter(Post.competitor_id == competitor_id)
    if topic:
        query = query.filter(Post.topic == topic)
    if source:
        query = query.filter(Post.source_reference == source)
    if keyword:
        query = query.filter(Post.post_text.ilike(f"%{keyword}%"))
    if date_from:
        query = query.filter(Post.published_date >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Post.published_date <= datetime.fromisoformat(date_to))

    posts = query.order_by(Post.published_date.desc()).limit(200).all()

    projects = db.query(Project).all()
    competitors = db.query(Competitor).all()
    topics = [t[0] for t in db.query(distinct(Post.topic)).filter(Post.topic.isnot(None)).all()]

    filters = {
        "project_id": project_id,
        "competitor_id": competitor_id,
        "topic": topic,
        "source": source,
        "keyword": keyword,
        "date_from": date_from,
        "date_to": date_to,
    }

    template = "_posts_list.html" if request.headers.get("HX-Request") else "posts.html"
    return templates.TemplateResponse(
        request,
        template,
        {"posts": posts, "projects": projects,
         "competitors": competitors, "topics": topics, "filters": filters},
    )


@app.get("/projects/{project_id}/dashboard")
def project_dashboard(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()

    competitor_count = db.query(Competitor).filter(
        Competitor.project_id == project_id, Competitor.is_own_business == False
    ).count()
    total_posts = db.query(Post).filter(Post.project_id == project_id).count()
    generated_count = db.query(GeneratedIdea).filter(GeneratedIdea.project_id == project_id).count()

    last_scraped = (
        db.query(func.max(Competitor.last_scraped_at)).filter(Competitor.project_id == project_id).scalar()
    )

    latest_job_stats = (
        db.query(
            func.coalesce(func.sum(ScrapeJob.new_posts_added), 0).label("new_posts"),
            func.coalesce(func.sum(ScrapeJob.duplicates_skipped), 0).label("duplicates"),
            func.count(ScrapeJob.id).filter(ScrapeJob.status == "failed").label("failed"),
        )
        .filter(ScrapeJob.project_id == project_id).first()
    )

    topic_rows = (
        db.query(Post.topic, func.count(func.distinct(Post.competitor_id)).label("competitor_count"),
                  func.count(Post.id).label("occurrence_count"))
        .join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Post.topic.isnot(None), Competitor.is_own_business == False)
        .group_by(Post.topic).order_by(func.count(func.distinct(Post.competitor_id)).desc()).all()
    )
    trends = [
        {"topic": r.topic, "competitor_count": r.competitor_count, "total_competitors": competitor_count,
         "occurrence_count": r.occurrence_count,
         "percentage": round((r.competitor_count / competitor_count) * 100) if competitor_count else 0}
        for r in topic_rows
    ]

    all_posts_keywords = (
        db.query(Post.detected_keywords).join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Post.detected_keywords.isnot(None), Competitor.is_own_business == False)
        .all()
    )
    keyword_counter = Counter()
    for (keywords,) in all_posts_keywords:
        if keywords:
            keyword_counter.update(k.lower() for k in keywords)
    top_keywords = keyword_counter.most_common(8)

    # new: gap + frequency data and their cached insights
    gap_data = compute_gap_data(db, project_id)
    freq_data = compute_frequency_data(db, project_id)
    gap_insight = get_or_generate_insight(db, project, "gap", gap_data, generate_gap_insight) if gap_data["topics"] else None
    freq_insight = get_or_generate_insight(db, project, "frequency", freq_data, generate_frequency_insight) if freq_data["weeks"] else None

    return templates.TemplateResponse(
        request, "dashboard.html",
        {
            "project": project, "competitor_count": competitor_count, "total_posts": total_posts,
            "generated_count": generated_count, "last_scraped": last_scraped,
            "new_posts": latest_job_stats.new_posts, "duplicates": latest_job_stats.duplicates,
            "failed": latest_job_stats.failed, "trends": trends, "top_keywords": top_keywords,
            "gap_data_json": json_module.dumps(gap_data), "freq_data_json": json_module.dumps(freq_data),
            "gap_insight": gap_insight, "freq_insight": freq_insight,
        },
    )


@app.get("/projects/{project_id}/logs")
def scrape_logs_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    jobs = (
        db.query(ScrapeJob, Competitor.name)
        .join(Competitor, ScrapeJob.competitor_id == Competitor.id)
        .filter(ScrapeJob.project_id == project_id)
        .order_by(ScrapeJob.started_at.desc().nullslast())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse(request, "logs.html", {"project": project, "jobs": jobs})


@app.get("/projects/{project_id}/insights")
def insights_chat_page(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    messages = db.query(ChatMessage).filter(ChatMessage.project_id == project_id).order_by(ChatMessage.created_at).all()

    starter_questions = []
    if not messages:
        context = build_project_context(db, project_id)
        try:
            starter_questions = generate_starter_questions(context)
        except Exception as e:
            print(f"Starter question generation failed: {e}")

    return templates.TemplateResponse(
        request, "insights.html",
        {"project": project, "messages": messages, "starter_questions": starter_questions},
    )


@app.post("/projects/{project_id}/analyze")
def analyze_project_posts(project_id: int, request: Request, db: Session = Depends(get_db)):
    unanalyzed = db.query(Post).filter(Post.project_id == project_id, Post.analyzed_at.is_(None)).all()

    if not unanalyzed:
        return templates.TemplateResponse(request, "_analysis_status.html",
            {"message": "All posts are already analyzed — nothing to do.", "analyzed_count": 0})

    BATCH_SIZE = 8
    total_analyzed = 0

    for i in range(0, len(unanalyzed), BATCH_SIZE):
        batch = unanalyzed[i:i + BATCH_SIZE]
        batch_dicts = [{"post_text": p.post_text or ""} for p in batch]

        try:
            results = analyze_posts_batch(batch_dicts)
        except Exception as e:
            print(f"Batch analysis failed: {e}")
            continue

        for result in results:
            if result.post_index >= len(batch):
                continue
            post = batch[result.post_index]
            post.topic = result.topic
            post.subtopic = result.subtopic
            post.detected_keywords = result.keywords
            post.cta = result.cta or post.cta
            post.content_type = result.content_type
            post.offer_detected = result.offer_detected
            post.analyzed_at = datetime.now(timezone.utc)
            total_analyzed += 1

    db.commit()
    return templates.TemplateResponse(request, "_analysis_status.html",
        {"message": f"Analyzed {total_analyzed} post(s).", "analyzed_count": total_analyzed})


@app.post("/projects")
def create_project(
    request: Request,
    name: str = Form(...),
    own_business_name: str = Form(...),
    own_business_profile_url: str = Form(...),
    db: Session = Depends(get_db),
):
    project = Project(
        name=name,
        own_business_name=own_business_name,
        own_business_profile_url=own_business_profile_url,
    )
    db.add(project)
    db.flush()  # get project.id before creating the competitor row

    own_business_competitor = Competitor(
        project_id=project.id,
        name=own_business_name,
        profile_url=own_business_profile_url,
        is_own_business=True,
    )
    db.add(own_business_competitor)

    db.commit()
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(request, "_project_list.html", {"projects": projects})


@app.post("/projects/{project_id}/competitors")
def add_competitor(
    project_id: int, request: Request,
    name: str = Form(...), profile_url: str = Form(...),
    db: Session = Depends(get_db),
):
    db.add(Competitor(project_id=project_id, name=name, profile_url=profile_url))
    db.commit()
    competitors = (
        db.query(Competitor)
        .filter(Competitor.project_id == project_id)
        .order_by(Competitor.is_own_business.desc(), Competitor.created_at)
        .all()
    )
    return templates.TemplateResponse(request, "_competitor_list.html", {"competitors": competitors})


@app.post("/projects/{project_id}/keywords")
def add_keyword(
    project_id: int, request: Request,
    keyword: str = Form(...),
    db: Session = Depends(get_db),
):
    db.add(Keyword(project_id=project_id, keyword=keyword))
    db.commit()
    keywords = db.query(Keyword).filter(Keyword.project_id == project_id).all()
    return templates.TemplateResponse(request, "_keyword_list.html", {"keywords": keywords})


@app.post("/projects/{project_id}/generate-ideas")
def do_generate_ideas(project_id: int, request: Request, count: str = Form("5"), topic: str = Form(""), db: Session = Depends(get_db)):
    today_start = datetime.combine(datetime.now(timezone.utc).date(), dtime.min, tzinfo=timezone.utc)
    generated_today = db.query(GeneratedIdea).filter(
        GeneratedIdea.project_id == project_id,
        GeneratedIdea.created_at >= today_start,
    ).count()

    if generated_today >= DAILY_GENERATION_LIMIT:
        ideas = db.query(GeneratedIdea).filter(GeneratedIdea.project_id == project_id).order_by(GeneratedIdea.created_at.desc()).all()
        return templates.TemplateResponse(request, "_generated_list.html",
            {"ideas": ideas, "limit_message": f"Daily generation limit ({DAILY_GENERATION_LIMIT}) reached for this project. Try again tomorrow."})

    count = max(1, min(int(count) if count.isdigit() else 5, 50))
    count = min(count, DAILY_GENERATION_LIMIT - generated_today)

    context = build_project_context(db, project_id)
    existing_ideas = (
        db.query(GeneratedIdea)
        .filter(GeneratedIdea.project_id == project_id, GeneratedIdea.title.isnot(None))
        .order_by(GeneratedIdea.created_at.desc())
        .limit(DAILY_GENERATION_LIMIT)
        .all()
    )
    exclude_summaries = [_idea_summary_for_prompt(i) for i in existing_ideas]

    all_saved = []
    attempts = 0
    while len(all_saved) < count and attempts < 4:
        remaining = count - len(all_saved)
        try:
            batch = generate_content(
                context, min(remaining + 3, 15),
                exclude_summaries + [_idea_summary_for_prompt(i) for i in all_saved],
                topic_focus=topic or None,
            )
        except Exception as e:
            print(f"Generation failed: {e}")
            break
        candidates = [b.model_dump() for b in batch]
        saved = dedup_and_save(db, project_id, candidates, kind="idea", max_to_save=remaining)
        all_saved.extend(saved)
        attempts += 1

    ideas = db.query(GeneratedIdea).filter(GeneratedIdea.project_id == project_id).order_by(GeneratedIdea.created_at.desc()).all()
    return templates.TemplateResponse(request, "_generated_list.html", {"ideas": ideas})


@app.post("/generated-ideas/{idea_id}/generate-image")
def generate_idea_image(idea_id: int, request: Request, db: Session = Depends(get_db)):
    idea = db.query(GeneratedIdea).filter(GeneratedIdea.id == idea_id).first()
    if not idea:
        return templates.TemplateResponse(request, "_generated_list.html", {"ideas": []})

    today_start = datetime.combine(datetime.now(timezone.utc).date(), dtime.min, tzinfo=timezone.utc)
    images_today = db.query(GeneratedIdea).filter(
        GeneratedIdea.project_id == idea.project_id,
        GeneratedIdea.image_generated_at >= today_start,
    ).count()

    if images_today >= DAILY_IMAGE_LIMIT:
        return _render_ideas_with_message(db, idea.project_id, request,
            f"Daily image generation limit ({DAILY_IMAGE_LIMIT}) reached for this project.")

    if not idea.image_concept:
        return _render_ideas_with_message(db, idea.project_id, request, "No image concept available for this idea.")

    prompt = f"A professional marketing photo for a Google Maps business update. Concept: {idea.image_concept}. Photorealistic, appetizing/appealing commercial style, no text overlays."

    try:
        image_bytes = generate_image(prompt)
        if not image_bytes:
            return _render_ideas_with_message(db, idea.project_id, request, "Image generation failed — no image returned.")

        supabase = _get_supabase_client()
        bucket = os.environ["SUPABASE_BUCKET"]
        remote_path = f"generated/{idea.id}_{datetime.now(timezone.utc).timestamp():.0f}.png"
        supabase.storage.from_(bucket).upload(remote_path, image_bytes, {"content-type": "image/png"})
        url = supabase.storage.from_(bucket).get_public_url(remote_path)

        idea.image_url = url
        idea.image_generated_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        print(f"Image generation failed: {e}")
        return _render_ideas_with_message(db, idea.project_id, request, "Image generation failed — please try again later.")

    ideas = db.query(GeneratedIdea).filter(GeneratedIdea.project_id == idea.project_id).order_by(GeneratedIdea.created_at.desc()).all()
    return templates.TemplateResponse(request, "_generated_list.html", {"ideas": ideas})


@app.post("/generated-ideas/bulk-delete")
def bulk_delete_ideas(request: Request, project_id: int = Form(...), idea_ids: list[int] = Form(default=[]), db: Session = Depends(get_db)):
    if idea_ids:
        db.query(GeneratedIdea).filter(GeneratedIdea.id.in_(idea_ids)).delete(synchronize_session=False)
        db.commit()
    ideas = db.query(GeneratedIdea).filter(GeneratedIdea.project_id == project_id).order_by(GeneratedIdea.created_at.desc()).all()
    return templates.TemplateResponse(request, "_generated_list.html", {"ideas": ideas})


@app.post("/projects/{project_id}/insights/chat")
def send_chat_message(project_id: int, request: Request, message: str = Form(...), db: Session = Depends(get_db)):
    today_start = datetime.combine(datetime.now(timezone.utc).date(), dtime.min, tzinfo=timezone.utc)
    sent_today = db.query(ChatMessage).filter(
        ChatMessage.project_id == project_id, ChatMessage.role == "user", ChatMessage.created_at >= today_start
    ).count()

    if sent_today >= DAILY_CHAT_LIMIT:
        messages = db.query(ChatMessage).filter(ChatMessage.project_id == project_id).order_by(ChatMessage.created_at).all()
        return templates.TemplateResponse(request, "_chat_messages.html",
            {"messages": messages, "limit_message": f"Daily question limit ({DAILY_CHAT_LIMIT}) reached for this project. Try again tomorrow."})

    db.add(ChatMessage(project_id=project_id, role="user", content=message))
    db.commit()

    history = db.query(ChatMessage).filter(ChatMessage.project_id == project_id).order_by(ChatMessage.created_at).all()
    history_dicts = [{"role": m.role, "content": m.content} for m in history[:-1]]  # exclude the message just sent

    context = build_project_context(db, project_id)
    try:
        reply = generate_chat_response(context, history_dicts, message)
    except Exception as e:
        reply = "Sorry, I couldn't generate a response right now — please try again."
        print(f"Chat generation failed: {e}")

    db.add(ChatMessage(project_id=project_id, role="assistant", content=reply))
    db.commit()

    messages = db.query(ChatMessage).filter(ChatMessage.project_id == project_id).order_by(ChatMessage.created_at).all()
    return templates.TemplateResponse(request, "_chat_messages.html", {"messages": messages})


@app.delete("/projects/{project_id}")
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        db.delete(project)
        db.commit()
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(request, "_project_list.html", {"projects": projects})


@app.delete("/competitors/{competitor_id}")
def delete_competitor(competitor_id: int, request: Request, db: Session = Depends(get_db)):
    competitor = db.query(Competitor).filter(Competitor.id == competitor_id).first()
    project_id = competitor.project_id if competitor else None
    if competitor:
        db.delete(competitor)
        db.commit()
    competitors = db.query(Competitor).filter(Competitor.project_id == project_id).all()
    return templates.TemplateResponse(request, "_competitor_list.html", {"competitors": competitors})


@app.delete("/keywords/{keyword_id}")
def delete_keyword(keyword_id: int, request: Request, db: Session = Depends(get_db)):
    keyword = db.query(Keyword).filter(Keyword.id == keyword_id).first()
    project_id = keyword.project_id if keyword else None
    if keyword:
        db.delete(keyword)
        db.commit()
    keywords = db.query(Keyword).filter(Keyword.project_id == project_id).all()
    return templates.TemplateResponse(request, "_keyword_list.html", {"keywords": keywords})


# Context building + dedup helpers
def build_project_context(db: Session, project_id: int) -> dict:
    competitor_count = db.query(Competitor).filter(
        Competitor.project_id == project_id, Competitor.is_own_business == False
    ).count()

    topic_rows = (
        db.query(Post.topic, func.count(func.distinct(Post.competitor_id)).label("cc"))
        .join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Post.topic.isnot(None), Competitor.is_own_business == False)
        .group_by(Post.topic).order_by(func.count(func.distinct(Post.competitor_id)).desc())
        .limit(4).all()
    )
    top_trends = [
        {"topic": r.topic, "percentage": round((r.cc / competitor_count) * 100) if competitor_count else 0}
        for r in topic_rows
    ]

    cta_rows = (
        db.query(Post.cta, func.count(Post.id).label("c"))
        .join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Post.cta.isnot(None), Competitor.is_own_business == False)
        .group_by(Post.cta).order_by(func.count(Post.id).desc()).limit(3).all()
    )
    top_ctas = [r.cta for r in cta_rows]

    total_posts = (
        db.query(Post).join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Competitor.is_own_business == False).count()
    )
    date_range = (
        db.query(func.min(Post.published_date), func.max(Post.published_date))
        .join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Post.published_date.isnot(None), Competitor.is_own_business == False)
        .first()
    )
    if date_range and date_range[0] and date_range[1] and competitor_count:
        span_days = max((date_range[1] - date_range[0]).days, 1)
        post_frequency = round((total_posts / competitor_count) / (span_days / 7), 1)
    else:
        post_frequency = 0

    sample_posts = [
        p.post_text for p in
        db.query(Post).join(Competitor, Post.competitor_id == Competitor.id)
        .filter(Post.project_id == project_id, Post.post_text.isnot(None), Competitor.is_own_business == False)
        .order_by(func.random()).limit(5).all()
    ]

    return {
        "top_trends": top_trends,
        "top_ctas": top_ctas,
        "post_frequency": post_frequency,
        "sample_posts": sample_posts,
    }


@app.post("/projects/{project_id}/scrape")
def start_scrape_job(project_id: int, request: Request):
    """
    Launches scraper/run.py as a separate background process rather than
    calling it inline — a live Selenium session (with a possible manual
    CAPTCHA pause) can run for minutes, far longer than an HTTP request
    should block for. The browser window it opens is visible on this
    machine; the web request just doesn't wait for it to finish.
    """
    try:
        subprocess.Popen(
            [sys.executable, "-m", "scraper.run", str(project_id)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,  # Windows-only: opens its own terminal window for visibility
        )
        message = "Scrape job started in a new window. Check the scraping logs page for progress."
        success = True
    except Exception as e:
        message = f"Failed to start scrape job: {e}"
        success = False

    return templates.TemplateResponse(
        request, "_scrape_status.html",
        {"message": message, "success": success},
    )


def _idea_embedding_text(c: dict) -> str:
    """Topic + title + a slice of actual copy — richer than title alone, so two
    differently-worded versions of the same offer embed as genuinely similar."""
    topic = c.get("topic", "")
    title = c.get("title", "")
    copy_snippet = (c.get("copy_text") or "")[:150]
    return f"{topic} — {title} — {copy_snippet}"


def _idea_summary_for_prompt(idea: GeneratedIdea) -> str:
    copy_snippet = (idea.copy_text or "")[:100] if idea.copy_text else ""
    return f"{idea.title} — {idea.topic} — {copy_snippet}"


def dedup_and_save(db: Session, project_id: int, candidates: list[dict], kind: str,
                    max_to_save: int | None = None, similarity_threshold: float = 0.82) -> list[GeneratedIdea]:
    # bounded comparison set — cost stays flat even as a project accumulates ideas over months
    existing = (
        db.query(GeneratedIdea.embedding)
        .filter(GeneratedIdea.project_id == project_id, GeneratedIdea.embedding.isnot(None))
        .order_by(GeneratedIdea.created_at.desc())
        .limit(300)
        .all()
    )
    existing_embeddings = [e[0] for e in existing if e[0]]

    accepted_embeddings = []
    saved = []

    for c in candidates:
        if max_to_save is not None and len(saved) >= max_to_save:
            break

        try:
            emb = embed_text(_idea_embedding_text(c))
        except Exception as e:
            print(f"Embedding failed, saving without dedup check: {e}")
            emb = None

        if emb:
            too_similar = any(cosine_similarity(emb, e) > similarity_threshold for e in existing_embeddings) or \
                          any(cosine_similarity(emb, e) > similarity_threshold for e in accepted_embeddings)
            if too_similar:
                continue
            accepted_embeddings.append(emb)

        idea = GeneratedIdea(
            project_id=project_id, kind=kind,
            topic=c.get("topic"), title=c.get("title"), copy_text=c.get("copy_text"),
            keywords=c.get("keywords", []), cta=c.get("cta"), image_concept=c.get("image_concept"),
            embedding=emb,
        )
        db.add(idea)
        saved.append(idea)

    db.commit()
    return saved


def _render_ideas_with_message(db, project_id, request, message):
    ideas = db.query(GeneratedIdea).filter(GeneratedIdea.project_id == project_id).order_by(GeneratedIdea.created_at.desc()).all()
    return templates.TemplateResponse(request, "_generated_list.html", {"ideas": ideas, "limit_message": message})


def _get_supabase_client():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])