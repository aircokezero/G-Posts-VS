"""
Transforms a Google Maps place URL into its owner-posts view URL.

Two confirmed transformations, tried in order:
1. Full pattern (4mX -> 4mX+2, 3mY -> 3mY+2, !11m1!2e1! inserted before !16s,
   entry=tts -> entry=ttu): confirmed 3-for-3 across two countries on
   businesses that actually have owner posts. This appears to be the URL
   Google's own client generates specifically to request the "owner posts"
   data panel (2e1 likely = mode 2, owner-authored).
2. Fallback: entry=tts -> entry=ttu alone. Seen when a business has NO
   owner posts (confirmed on one case) — Google's JS has nothing to
   request via the full pattern, so it degrades to the generic Updates
   tab URL, which shows whatever exists (often visitor content).

These patterns were confirmed against live markup, but Google could change them at any time.
Moreover, they are global in nature, and not tied to specific region, location, 
or any other type of point of separation.

If a business has no owner posts, trying pattern 1 anyway is safe: the
container selector (jslog^="49745") only matches genuine owner-post
cards — confirmed against real markup, where visitor-updates content
used a completely different jslog family (137884). So an owner-posts
URL on a business with none simply yields zero matched containers,
not wrong data.
"""

import re

_FULL_PATTERN = re.compile(r"!4m(\d+)!3m(\d+)!(.*?)!16s")


def build_posts_url(resolved_url: str) -> str | None:
    match = _FULL_PATTERN.search(resolved_url)
    if match:
        m4, m3, middle = match.groups()
        new_segment = f"!4m{int(m4) + 2}!3m{int(m3) + 2}!{middle}!11m1!2e1!16s"
        url = _FULL_PATTERN.sub(new_segment, resolved_url, count=1)
        return url.replace("entry=tts", "entry=ttu")

    if "entry=tts" in resolved_url:
        return resolved_url.replace("entry=tts", "entry=ttu")

    return None


_PLACE_ID_PATTERN = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)")

def extract_place_id(resolved_url: str) -> str | None:
    """
    Extracts Google's internal place identifier from a resolved Maps URL —
    used to detect duplicate competitor entries (same business added twice
    under different URL formats), not for the posts-URL transform itself.
    Composite URLs can contain two hex pairs (a contextual reference and
    the actual target); takes the LAST match, consistent with what was
    confirmed for CID extraction — the resolved place sits in the final position.
    """
    matches = _PLACE_ID_PATTERN.findall(resolved_url)
    return matches[-1] if matches else None