"""
Parses Google Maps' relative timestamp strings ("2 days ago", "a week ago", etc.)
into actual datetimes. Written flexibly since exact wording can vary.
"""

import re
from datetime import datetime, timedelta, timezone


def parse_relative_date(text: str, reference: datetime | None = None) -> datetime | None:
    if not text:
        return None
    text = text.strip().lower()
    reference = reference or datetime.now(timezone.utc)

    if "just now" in text or "moment" in text:
        return reference

    match = re.search(r"\b(a|an|\d+)\s+(hour|day|week|month|year)s?\s+ago", text)
    if match:
        amount = 1 if match.group(1) in ("a", "an") else int(match.group(1))
        unit = match.group(2)
        deltas = {
            "hour": timedelta(hours=amount),
            "day": timedelta(days=amount),
            "week": timedelta(weeks=amount),
            "month": timedelta(days=amount * 30),
            "year": timedelta(days=amount * 365),
        }
        return reference - deltas[unit]

    return None