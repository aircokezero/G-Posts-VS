"""
Seed script — populates the demo dataset required by section 9 of the brief.
Run with: python -m seed.seed_data
"""

import os
import hashlib
import random
from datetime import datetime, timedelta, timezone

from core.db import SessionLocal
from core.models import Project, Competitor, Keyword, Post
from core.services import make_fingerprint, refresh_competitor_stats

# ─────────────────────────────────────────────
# CONFIG — swap this block for any vertical/city
# ─────────────────────────────────────────────

PROJECT_NAME = "Project: Kharghar Bites"
OWN_BUSINESS_NAME = "Kharghar Bites"
OWN_BUSINESS_URL = "https://maps.google.com/?cid=0000000000000000001"
CITY = "Kharghar"

COMPETITORS = [
    {"name": "Spice Route Kitchen", "profile_url": "https://maps.google.com/?cid=0000000000000000002"},
    {"name": "The Green Chilli", "profile_url": "https://maps.google.com/?cid=0000000000000000003"},
    {"name": "Urban Tadka", "profile_url": "https://maps.google.com/?cid=0000000000000000004"},
    {"name": "Coastal Curry House", "profile_url": "https://maps.google.com/?cid=0000000000000000005"},
    {"name": "The Grill Room", "profile_url": "https://maps.google.com/?cid=0000000000000000006"},
]

KEYWORDS = [
    f"restaurants in {CITY}",
    f"best food in {CITY}",
    f"dinner places {CITY}",
]

# templates: {} placeholders filled per-post. topic drives trend analysis.
POST_TEMPLATES = [
    {
        "topic": "Promotional Offer",
        "text": "This {festival} season, enjoy {discount}% off on your total bill! Valid till {date_str}. Bring your family and celebrate with us.",
        "cta": "Call to reserve",
        "content_type": "promotion",
        "offer": True,
    },
    {
        "topic": "New Product/Service",
        "text": "Introducing our new {dish}! Made fresh daily with locally sourced ingredients. Available for dine-in and takeaway starting this week.",
        "cta": "Order now",
        "content_type": "product_update",
        "offer": False,
    },
    {
        "topic": "Limited-Time Deal",
        "text": "Happy Hour is here! {discount}% off on all beverages from {time_start} to {time_end}, every weekday. Perfect spot to unwind after work.",
        "cta": "Visit us today",
        "content_type": "promotion",
        "offer": True,
    },
    {
        "topic": "Limited-Time Deal",
        "text": "This weekend only: try our {dish} at a special price. Limited tables available, walk-ins welcome but reservations recommended.",
        "cta": "Book a table",
        "content_type": "promotion",
        "offer": True,
    },
    {
        "topic": "Event",
        "text": "Join us this {day} for a live {event_type} night! Great food, great music, no entry fee. Doors open at {time_start}.",
        "cta": "Learn more",
        "content_type": "event",
        "offer": False,
    },
    {
        "topic": "Facility/Renovation Update",
        "text": "We've refreshed our dining space! New seating, new ambience, same great food. Come see what's changed and enjoy a meal on us with any main course.",
        "cta": "Visit us today",
        "content_type": "announcement",
        "offer": False,
    },
    {
        "topic": "Customer Appreciation",
        "text": "Thank you {city} for {years} years of support! To celebrate, we're offering a complimentary {dish} with every order above {amount}.",
        "cta": "Order now",
        "content_type": "promotion",
        "offer": True,
    },
    {
        "topic": "Promotional Offer",
        "text": "Celebrate {festival} with our special thali starting at {amount}. Available all week, dine-in and delivery both.",
        "cta": "Order now",
        "content_type": "promotion",
        "offer": True,
    },
]

# fill-in values used to vary templates across posts/competitors
FESTIVALS = ["Diwali", "Ganesh Chaturthi", "New Year", "Christmas", "Holi"]
DISHES = ["Butter Chicken Thali", "Paneer Tikka Platter", "Prawn Curry Bowl", "Veg Biryani", "Mutton Rogan Josh", "Margherita Pizza"]
EVENT_TYPES = ["acoustic", "jazz", "DJ", "karaoke"]
DAYS = ["Friday", "Saturday", "Sunday"]

# small pool of real image files you place locally before running this script
IMAGE_POOL_DIR = "seed/images"  # put ~8-10 .jpg/.png files here
IMAGE_POOL = [f"food_{i}.jpg" for i in range(1, 9)]  # adjust to match what's actually in the folder


# ─────────────────────────────────────────────
# GENERIC LOGIC — do not hardcode vertical here
# ─────────────────────────────────────────────


def fill_template(template: dict) -> dict:
    text = template["text"].format(
        festival=random.choice(FESTIVALS),
        discount=random.choice([10, 15, 20, 25, 30]),
        date_str=(datetime.now(timezone.utc) + timedelta(days=random.randint(5, 20))).strftime("%d %b"),
        dish=random.choice(DISHES),
        time_start=random.choice(["5 PM", "6 PM", "7 PM"]),
        time_end=random.choice(["8 PM", "9 PM"]),
        event_type=random.choice(EVENT_TYPES),
        day=random.choice(DAYS),
        city=CITY,
        years=random.choice([3, 5, 7, 10]),
        amount=random.choice(["₹499", "₹699", "₹999"]),
    )
    return {**template, "text": text}


def random_recent_date() -> datetime:
    days_ago = random.randint(1, 90)
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def get_available_images() -> list[str]:
    """Read whatever files actually exist in the folder, rather than trusting a hardcoded list."""
    if not os.path.isdir(IMAGE_POOL_DIR):
        return []
    return [f for f in os.listdir(IMAGE_POOL_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png"))]


def upload_random_image(supabase_client, bucket: str) -> str | None:
    """
    Uploads a random image from the local pool to Supabase storage and
    returns its public URL. Returns None if the pool is empty/misconfigured —
    seeding should not hard-fail just because images aren't set up yet.
    """
    images = get_available_images()
    if not images:
        return None

    filename = random.choice(images)
    local_path = os.path.join(IMAGE_POOL_DIR, filename)

    ext = filename.split(".")[-1].lower()
    content_type = "image/png" if ext == "png" else "image/jpeg"

    remote_path = f"seed/{filename}_{random.randint(1000,9999)}.jpg"
    with open(local_path, "rb") as f:
        supabase_client.storage.from_(bucket).upload(remote_path, f, {"content-type": content_type})
    return supabase_client.storage.from_(bucket).get_public_url(remote_path)


def run():
    db = SessionLocal()

    # optional: only set this up if images are ready, else posts get empty image lists
    supabase_client = None
    bucket = None
    try:
        from supabase import create_client
        import os
        from dotenv import load_dotenv
        load_dotenv()
        supabase_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
        bucket = os.environ["SUPABASE_BUCKET"]
    except Exception as e:
        print(f"Skipping image upload (Supabase not configured): {e}")

    project = Project(
        name=PROJECT_NAME,
        own_business_name=OWN_BUSINESS_NAME,
        own_business_profile_url=OWN_BUSINESS_URL,
    )
    db.add(project)
    db.flush()  # get project.id without committing yet

    for kw in KEYWORDS:
        db.add(Keyword(project_id=project.id, keyword=kw))

    for comp_data in COMPETITORS:
        competitor = Competitor(project_id=project.id, **comp_data)
        db.add(competitor)
        db.flush()

        # sample without replacement so no competitor gets the same
        # static (no-placeholder) template twice -> no fingerprint collisions
        competitor_templates = random.sample(POST_TEMPLATES, len(POST_TEMPLATES))

        for template in competitor_templates:
            filled = fill_template(template)
            image_url = upload_random_image(supabase_client, bucket) if supabase_client else None
            post_url = f"{comp_data['profile_url']}&post={random.randint(10000,99999)}"
            published_date = random_recent_date()

            post = Post(
                project_id=project.id,
                competitor_id=competitor.id,
                post_url=post_url,
                post_text=filled["text"],
                published_date=published_date,
                image_urls=[image_url] if image_url else [],
                cta=filled["cta"],
                topic=filled["topic"],
                content_type=filled["content_type"],
                offer_detected=filled["offer"],
                fingerprint=make_fingerprint(post_url, filled["text"], published_date),
                source_reference="seed_demo_data",
            )
            db.add(post)

        competitor.total_posts_collected = len(competitor_templates)
        competitor.last_scraped_at = datetime.now(timezone.utc)
        competitor.last_scrape_status = "success"

    db.commit()  # commit posts first so refresh_competitor_stats can count them

    for comp_data in COMPETITORS:
        competitor = db.query(Competitor).filter(
            Competitor.project_id == project.id, Competitor.name == comp_data["name"]
        ).first()
        if competitor:
            refresh_competitor_stats(db, competitor.id)
            competitor.last_scrape_status = "success"

    db.commit()
    print(f"Seeded project '{PROJECT_NAME}' with {len(COMPETITORS)} competitors and posts.")
    db.close()


if __name__ == "__main__":
    run()