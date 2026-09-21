"""
Run once to create all tables in the database.
Usage: python init_db.py
"""

from core.db import engine
from core.models import Base

Base.metadata.create_all(bind=engine)
print("Tables created successfully.")