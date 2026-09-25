"""
Extraction logic, built from real inspected markup across three tested
businesses. Distinguishes owner posts (in scope) from visitor-review-shaped
cards (out of scope per brief section 4) using structural signals confirmed
against a real "Updated by visitors" card: a "Local Guide" badge and/or a
photo carousel, neither of which appear on genuine owner posts.
"""

from datetime import datetime, timezone

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from scraper.date_parser import parse_relative_date

POST_CONTAINER_SELECTOR = 'div[jslog^="49745"]'


def _looks_like_visitor_review(container) -> bool:
    try:
        container.find_element(By.CSS_SELECTOR, ".TwZujd")  # "Local Guide" badge
        return True
    except NoSuchElementException:
        pass
    try:
        container.find_element(By.CSS_SELECTOR, '[aria-roledescription="carousel"]')
        return True
    except NoSuchElementException:
        pass
    return False


def _parse_post_date(raw_text: str) -> datetime | None:
    raw_text = raw_text.strip()
    parsed = parse_relative_date(raw_text)
    if parsed:
        return parsed
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(raw_text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    print(f"Unrecognized date format, storing as None: '{raw_text}'")
    return None


def extract_posts_from_profile(driver) -> list[dict]:
    """
    Returns a list of dicts shaped for Post(**dict) minus project/competitor ids:
    post_text, post_url, published_date, image_urls, cta.
    Assumes the driver is already on the Updates/Posts view.
    """
    containers = driver.find_elements(By.CSS_SELECTOR, POST_CONTAINER_SELECTOR)
    if not containers:
        print("No post cards found — either this profile has no owner posts, "
              "or navigation didn't land on the right view.")
        return []

    results = []
    skipped_reviews = 0

    for container in containers:
        if _looks_like_visitor_review(container):
            skipped_reviews += 1
            continue

        try:
            post_text = container.find_element(By.CSS_SELECTOR, ".hfJtQe").text.strip()
        except NoSuchElementException:
            post_text = ""

        if not post_text:
            continue

        try:
            date_raw = container.find_element(By.CSS_SELECTOR, ".mgX1W").text.strip()
        except NoSuchElementException:
            date_raw = ""
        published_date = _parse_post_date(date_raw) if date_raw else None

        post_url = None
        try:
            share_btn = container.find_element(By.CSS_SELECTOR, "button[data-sharing-url]")
            post_url = share_btn.get_attribute("data-sharing-url")
        except NoSuchElementException:
            pass

        image_urls = []
        try:
            img = container.find_element(By.CSS_SELECTOR, ".oHJe9 img")
            src = img.get_attribute("src")
            if src:
                image_urls.append(src)
        except NoSuchElementException:
            pass

        cta = None
        try:
            cta_el = container.find_element(By.CSS_SELECTOR, ".sGOmPe")
            cta = cta_el.text.strip()
        except NoSuchElementException:
            pass

        results.append({
            "post_text": post_text,
            "post_url": post_url,
            "published_date": published_date,
            "image_urls": image_urls,
            "cta": cta,
        })

    if skipped_reviews:
        print(f"Skipped {skipped_reviews} visitor-review-shaped card(s) — out of scope per brief section 4.")

    return results