"""
FastAPI application entrypoint.
"""

from datetime import datetime
from fastapi import FastAPI, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import distinct

from core.db import get_db
from core.models import Project, Competitor, Post, Keyword

app = FastAPI(title="Google Maps Competitor Intelligence Tool")
templates = Jinja2Templates(directory="app/templates")


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/projects")
def projects_page(request: Request, db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return templates.TemplateResponse(request, "projects.html", {"projects": projects})


@app.get("/projects/{project_id}")
def project_detail(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    competitors = db.query(Competitor).filter(Competitor.project_id == project_id).all()
    keywords = db.query(Keyword).filter(Keyword.project_id == project_id).all()
    return templates.TemplateResponse(
        request, "project_detail.html",
        {"project": project, "competitors": competitors, "keywords": keywords},
    )


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
    competitors = db.query(Competitor).filter(Competitor.project_id == project_id).all()
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