"""
LLM provider abstraction. Gemini primary, Groq fallback.
Two entry points the rest of the app calls:
  - analyze_posts_batch(): topic/CTA/keyword classification for scraped posts
  - generate_content(): grounded content idea generation with dedup support
  - embed_text() / cosine_similarity(): used for duplicate-idea detection
"""

import os
import json
import math
from google import genai
from openai import OpenAI
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from core.taxonomy import TOPICS, CONTENT_TYPES


# Schemas
class PostAnalysis(BaseModel):
    post_index: int
    topic: str
    subtopic: str | None = None
    keywords: list[str] = []
    cta: str | None = None
    content_type: str
    offer_detected: bool


class GeneratedContentOut(BaseModel):
    title: str
    topic: str
    copy_text: str
    keywords: list[str] = []
    cta: str
    image_concept: str


# Raw provider calls
@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
def _call_gemini(prompt: str) -> str:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
    )
    return response.text


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
def _call_groq(prompt: str, force_json: bool = True) -> str:
    client = OpenAI(
        api_key=os.environ["GROQ_API_KEY"],
        base_url="https://api.groq.com/openai/v1",
    )
    kwargs = {"response_format": {"type": "json_object"}} if force_json else {}
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
        **kwargs,
    )
    return response.choices[0].message.content


def _call_llm_with_fallback(prompt: str, force_json: bool = True) -> str:
    for provider_name in ["gemini", "groq"]:
        try:
            if provider_name == "gemini":
                return _call_gemini(prompt)
            else:
                return _call_groq(prompt, force_json=force_json)
        except Exception as e:
            cause = e.last_attempt.exception() if hasattr(e, "last_attempt") else e
            print(f"{provider_name} failed: {cause}")
            continue
    raise RuntimeError("All LLM providers failed.")


def _clean_json_text(text: str) -> str:
    """Strip markdown code fences some models add despite instructions not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


# Embeddings (used for idea-duplicate detection)
def embed_text(text: str) -> list[float]:
    """Single-text embedding call — avoids a documented batching bug in the
    gemini-embedding-2* family. True cosine similarity below is scale-invariant,
    so no manual vector normalization is needed regardless of dimensionality."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    result = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text,
    )
    return list(result.embeddings[0].values)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# Post analysis (topic/CTA/keyword classification)
def _build_analysis_prompt(posts: list[dict]) -> str:
    posts_block = "\n".join(f"{i}. {p['post_text']}" for i, p in enumerate(posts))
    return f"""You are analyzing Google Maps business update posts for a competitor intelligence tool.

For each post below, classify it using ONLY this fixed topic list: {TOPICS}
Use "Other" if genuinely nothing fits — do not force a bad match.
Content type must be one of: {CONTENT_TYPES}

Return ONLY a JSON object, no preamble, no markdown fences, in this exact shape:
{{"results": [{{"post_index": 0, "topic": "...", "subtopic": "...", "keywords": ["...", "..."], "cta": "...", "content_type": "...", "offer_detected": true}}]}}

Posts:
{posts_block}
"""


def analyze_posts_batch(posts: list[dict]) -> list[PostAnalysis]:
    """posts: list of dicts with at least {"post_text": str}. Returns validated
    PostAnalysis objects; caller maps post_index back to the original posts."""
    prompt = _build_analysis_prompt(posts)
    raw_text = _call_llm_with_fallback(prompt)

    cleaned = _clean_json_text(raw_text)
    parsed = json.loads(cleaned)
    items = parsed.get("results", []) if isinstance(parsed, dict) else parsed

    results = []
    for item in items:
        try:
            results.append(PostAnalysis(**item))
        except ValidationError as e:
            print(f"Skipping malformed analysis result: {e}")
    return results


# Content generation (grounded, deduplicated)
def _build_context_block(context: dict) -> str:
    trends_lines = "\n".join(
        f"- {t['topic']}: used by {t['percentage']}% of competitors"
        for t in context["top_trends"]
    ) or "- no trend data yet"

    ctas_lines = ", ".join(context["top_ctas"]) or "no clear pattern yet"
    sample_lines = "\n".join(f"- {p}" for p in context["sample_posts"]) or "- no sample posts available"

    return f"""Competitor research context for this project:

Trending topics among competitors:
{trends_lines}

Common calls to action competitors use: {ctas_lines}

Competitors post updates at an average rate of {context['post_frequency']} posts/week per competitor.

Sample of real competitor post text (for tone/style reference only, do not copy):
{sample_lines}
"""


def generate_content(context: dict, count: int, exclude_summaries: list[str], topic_focus: str | None = None) -> list[GeneratedContentOut]:
    context_block = _build_context_block(context)
    exclude_block = (
        "\nDo NOT repeat these previously generated ideas (shown as title — topic — summary), "
        "and avoid close variations of the same underlying offer or concept:\n"
        + "\n".join(f"- {s}" for s in exclude_summaries)
        if exclude_summaries else ""
    )
    topic_instruction = f'Focus specifically on the topic: "{topic_focus}".' if topic_focus else \
        f"Choose whichever topics from this list make the most strategic sense: {TOPICS}"

    prompt = f"""{context_block}
{exclude_block}

Generate {count} NEW, DISTINCT, ready-to-publish Google Maps updates for this business, grounded in the
competitor research above — not generic content. Each one must be a complete post a business owner could
publish as-is, not just a title. Each idea must use a genuinely different underlying concept or offer —
not just different wording of the same promotion.

{topic_instruction}

Return ONLY a JSON object, no preamble, no markdown fences:
{{"updates": [{{"title": "short internal label", "topic": "...", "copy_text": "full post text, 2-4 sentences", "keywords": ["...", "..."], "cta": "...", "image_concept": "short description of a suggested image"}}]}}
"""
    raw = _call_llm_with_fallback(prompt)
    parsed = json.loads(_clean_json_text(raw))
    items = parsed.get("updates", []) if isinstance(parsed, dict) else parsed

    results = []
    for item in items:
        try:
            results.append(GeneratedContentOut(**item))
        except ValidationError as e:
            print(f"Skipping malformed generated item: {e}")
    return results


def generate_gap_insight(data: dict) -> str:
    lines = "\n".join(
        f"- {t}: competitors {cp}%, you {op}%"
        for t, cp, op in zip(data["topics"], data["competitor_pct"], data["own_pct"])
    ) or "- no topic data yet"

    prompt = f"""Topic coverage comparison for a business vs its Google Maps competitors:
{lines}

Write ONE short, specific, actionable sentence (max 2 sentences) telling the business owner
the single most important content gap to address. Name the topic explicitly. No preamble, no markdown."""
    return _call_llm_with_fallback(prompt, force_json=False).strip()


def generate_frequency_insight(data: dict) -> str:
    prompt = f"""Posting frequency comparison, posts per week:
Weeks: {data['weeks']}
Your business: {data['own_series']}
Competitor average: {data['competitor_series']}

Write ONE short, specific, actionable sentence (max 2 sentences) about how this business's
posting frequency compares to competitors and what to do about it. No preamble, no markdown."""
    return _call_llm_with_fallback(prompt, force_json=False).strip()


def generate_starter_questions(context: dict) -> list[str]:
    context_block = _build_context_block(context)
    prompt = f"""{context_block}

Generate exactly 3 short, specific questions (under 12 words each) a business owner might ask
about this competitive data — questions this data can actually answer.

Return ONLY a JSON object, no preamble, no markdown fences:
{{"questions": ["...", "...", "..."]}}"""
    raw = _call_llm_with_fallback(prompt, force_json=True)
    parsed = json.loads(_clean_json_text(raw))
    return parsed.get("questions", [])[:3]


def generate_chat_response(context: dict, history: list[dict], user_message: str) -> str:
    context_block = _build_context_block(context)
    history_block = "\n".join(f"{m['role']}: {m['content']}" for m in history[-10:]) or "(no previous messages)"

    prompt = f"""{context_block}

You are a competitor-intelligence assistant helping a business owner understand their competitive
position, grounded ONLY in the data above. If something isn't covered by this data, say so honestly
rather than inventing an answer.

Conversation so far:
{history_block}

User: {user_message}

Respond conversationally and concisely (2-4 sentences unless more detail is genuinely warranted),
grounded in the data above. No markdown formatting."""
    return _call_llm_with_fallback(prompt, force_json=False).strip()