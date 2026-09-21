"""
FastAPI application entrypoint.
"""

from fastapi import FastAPI

app = FastAPI(title="Google Maps Competitor Intelligence Tool")


@app.get("/")
def root():
    return {"status": "ok"}