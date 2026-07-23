from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name, "region": settings.region}


@app.get("/trends")
def trends(category: str = "hashtag"):
    # stub — diisi di M4 (baca dari DB)
    return {"category": category, "trends": [], "note": "stub, implemented in M4"}
