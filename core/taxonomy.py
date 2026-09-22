"""
Fixed topic taxonomy. Kept generic (not tied to any one vertical) since
the tool is meant to work project-by-project across any business category.
Constrained rather than free-form so trend analysis (GROUP BY topic)
produces meaningful counts instead of near-duplicate labels fragmenting the data.
"""

TOPICS = [
    "Promotional Offer",
    "New Product/Service",
    "Limited-Time Deal",
    "Event",
    "Facility/Renovation Update",
    "Customer Appreciation",
    "Other",  # required fallback — every real post must map to something
]

CONTENT_TYPES = ["promotion", "product_update", "event", "announcement", "other"]