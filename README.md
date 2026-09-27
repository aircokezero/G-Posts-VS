# G-Posts V/S: A Google Maps Competitor Posts Monitoring Intelligence Tool

A web interface that enables businesses to track their competitors on Google Maps posts, analyze that data, and use GenAI features that create actionable insights.

Built project-by-project: create a project, add your own business profile and manually-added competitors, optionally add discovery keywords, collect Google Maps Updates/Posts (via a pre-populated demo dataset and/or live scraping), analyze what competitors are publishing with AI, see trends and content gaps, and generate grounded, deduplicated content ideas — including AI-generated images — for your own next post.

---

## Live Deployment

The hosted version runs the full application against a shared database pre-populated with a working demo dataset, so every feature — repository browsing, AI analysis, trends, the dashboard, the insights chatbot, and content generation — is usable immediately without any setup or login.

Live scraping is intentionally **not** triggerable from the hosted site. A real, interactive Google Maps scraping session (with a visible browser window and manual CAPTCHA-solving support) cannot run inside a headless cloud container. Instead, the hosted "Queue Scrape Job(s)" trigger and the local worker architecture (see **Scraper Architecture** below) are designed so a scrape can be *queued* from the hosted site and *executed* by a locally-running worker against the same shared database — demonstrated separately, as intended by the assignment brief (see "Demo and Pre-Scraped Repository" in the brief: live scraping must never be the only way to evaluate the system).

The scraping logs page on the hosted site shows real results from live scraping runs already performed against real, publicly findable businesses, as direct evidence the scraper works end-to-end.

---

## Core Features

- **Project-based workflow** — create a project, define your own business, manually add competitors, optionally add discovery keywords
- **Own-business tracking** — your own profile is modeled as a specially-flagged competitor entry, enabling direct "you vs. them" comparison throughout the app, not just standalone competitor data
- **Google Maps Updates/Posts scraping** — Selenium-based, focused strictly on owner-authored posts (not reviews, not visitor-submitted "updates," per the assignment's scope)
- **Duplicate detection** — database-level fingerprinting (post URL, or normalized text + date as a fallback) prevents re-inserting the same post twice on re-scrape
- **Duplicate-competitor detection** — Google's internal place identifier is extracted from resolved URLs to prevent the same real business from existing as two separate competitor entries
- **CAPTCHA / anti-automation handling** — the scraper detects CAPTCHA/block pages, pauses, and waits for manual solving before continuing; every scrape attempt is logged, including verification events
- **AI-powered post analysis** — every post is classified into a fixed topic taxonomy, with CTA, content type, and offer detection, using a two-provider LLM setup with automatic fallback
- **Trend analysis** — topic usage computed as "X of Y competitors (Z%)," matching the assignment's own worked example
- **Actionable dashboard** — not just metrics: a content-gap visualization (topics competitors use that you don't), a posting-frequency comparison (you vs. competitor average over time), and cached, automatically-refreshed natural-language insights under each chart
- **Insights chatbot** — a grounded, conversational way to ask questions about the collected competitive data, with suggested starter questions and a daily usage cap
- **Content idea generation** — grounded in real trend/CTA/frequency data from the project's own repository, not generic content; supports generating any requested quantity of ideas per the assignment's examples (3, 10, 50)
- **Duplicate-idea prevention** — embedding-based similarity checking (not just exact-text matching) plus prompt-level exclusion of prior ideas, so repeated generation requests don't return near-identical content
- **AI image generation** — a free, no-API-key image generation provider is used to produce an accompanying image for any generated content idea
- **Full repository browser** — search and filter the collected post repository by project, competitor, topic, date, keyword, and data source (demo vs. live-scraped)
- **Scraping logs** — a full history of every scrape attempt, including status, timing, posts found/added/skipped, and CAPTCHA events

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python) |
| Templates / Frontend | Jinja2 + HTMX + Tailwind CSS (CDN) |
| Charts | Chart.js |
| ORM | SQLAlchemy 2.0 |
| Database | Postgres, hosted on Neon |
| Object storage | Supabase Storage (storage only — no Supabase database is used) |
| Scraping | Python + Selenium + undetected-chromedriver |
| AI text (analysis, generation, chat) | Google Gemini (primary), Groq (automatic fallback) |
| AI image generation | Pollinations.ai (free, no API key required) |
| Hosting | Render |

### Why this combination

- **FastAPI + Jinja2 + HTMX** avoids a separate frontend build/deploy pipeline entirely — server-rendered HTML with HTMX-driven partial updates gives a responsive, app-like feel without a JS framework.
- **Neon over a self-hosted or free-tier-paused Postgres** — some managed Postgres free tiers auto-pause a project's compute after a period of inactivity, which risks the evaluator hitting a dead database mid-evaluation. Neon's free tier scales compute to zero but does not lock the project behind a manual restore step.
- **Supabase Storage, not Supabase's database** — used purely for object storage (post images, generated images), specifically to avoid requiring a payment method (a blocker with some alternative storage providers) while keeping the actual application database on Neon.
- **Two independent AI providers (Gemini + Groq)** with automatic fallback on any failure (quota exhaustion, transient error) — satisfies the assignment's requirement for at least two AI providers in a way that provides resilience.
- **Pollinations.ai for images** — both Gemini's and Groq's image-generation capabilities require paid access even at low volume; Pollinations offers a genuinely free, keyless, URL-based generation endpoint suited to a student-budget project.

---

## AI Providers Used

1. **Google Gemini** (`gemini-2.5-flash` for text; `gemini-embedding-001` for duplicate-idea detection) — primary text provider
2. **Groq** (`openai/gpt-oss-120b`) — automatic fallback if Gemini fails or is rate-limited
3. **Pollinations.ai** — image generation for AI-generated post concepts

---

## Scraper Architecture

The scraper is a separate Python process from the web application, by design:

- **CAPTCHA handling requires a real, visible browser** a person can interact with — this cannot run headless on a cloud host, and a headless scraper is also far more likely to trigger anti-automation defenses in the first place.
- **Local worker model**: `scraper/worker.py` runs on a local machine and polls the shared database for queued scrape jobs. The hosted web app's "Queue Scrape Job(s)" button simply inserts pending job rows — it does not attempt to run Selenium itself. A manual, single-project CLI (`scraper/run.py`) is also available for direct local use.
- **Navigation**: rather than requiring a user to supply an exact, "correct" Google Maps URL format (fragile — Maps URLs vary significantly by how they were copied/shared), the scraper navigates to whatever URL the user provided, lets Google's own redirects resolve it, and reads the final resolved URL back from the browser. A URL transformation (confirmed empirically against multiple real businesses across two countries) is then applied to reach the owner-posts view specifically.
- **Owner-posts scoping**: the extractor distinguishes genuine owner-authored posts from Google's separate "Updated by visitors" content (which is closer to review/photo activity than a business post) using structural signals confirmed against real inspected markup, and only stores owner posts — keeping the repository within the assignment's defined scope ("Google Maps Updates/Posts" specifically).
- **Duplicate detection** operates at two levels: per-post (via a stable fingerprint derived from post URL, or normalized text + publish date as a fallback) and per-competitor (via Google's internal place identifier, preventing the same real business from being tracked as two separate competitor entries).

---

## Environment Variables

```
# Database (Neon)
DATABASE_URL=postgresql://...

# Storage (Supabase — storage only)
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_BUCKET=media

# AI providers
GEMINI_API_KEY=...
GROQ_API_KEY=...

# Deployment
IS_HOSTED=true   # set only on the hosted deployment; hides the local-only scrape trigger
```

Pollinations.ai requires no API key or signup.

---

## Local Setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Create the schema
python init_db.py

# Populate the demo dataset (optional, you can directly host and create a project)
python -m seed.seed_data

# Run the app
uvicorn app.main:app --reload
```

To run the scraper locally:

```bash
# One-off, whole-project scrape. Same functionality from the web UI.
python -m scraper.run <project_id>
```

---

## Project Structure

```
app/        FastAPI routes, Jinja2 templates
core/       SQLAlchemy models, DB session, shared business logic, LLM integration
scraper/    Selenium scraper: navigation, extraction, CAPTCHA handling, worker/CLI entry points
seed/       Demo dataset generator
```

`core/` is shared between the web app and the scraper so that logic like duplicate fingerprinting and competitor-stat refreshing behaves identically regardless of which part of the system wrote the data.

---

## Bonus Features Implemented

- Automatic identification of content gaps — topics competitors post about that the client's own profile has not covered, visualized and explained in plain language
- Posting-frequency comparison between the client's own business and the competitor average, visualized over time
- A grounded, conversational insights assistant for ad hoc questions about the collected competitive data
- AI-generated images accompanying generated content ideas
- Duplicate-competitor detection via Google place identifiers, in addition to the required duplicate-post detection

---

## Known Limitations

- Live scraping requires a locally-run worker process; it is not triggerable end-to-end from the hosted deployment alone (see **Scraper Architecture**)
- AI-generated insights and chatbot responses are best treated as a supplementary, exploratory layer — the dashboard's data visualizations and their auto-generated summary insights are the more reliable source for decision-making on complex questions
- CAPTCHA-solving is manual (a person completes the challenge in a visible browser window); no third-party CAPTCHA-solving service is integrated

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.