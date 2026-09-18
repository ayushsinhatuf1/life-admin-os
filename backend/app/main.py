from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import admin, assistant, auth, deadlines, documents, me, registry

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Life Admin OS API",
    version="1.0.0",
    description="Personal and family record intelligence. Not a legal, financial or land-record authority.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.app_env != "development":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logging.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Try again."})


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.app_env}


app.include_router(auth.router)
app.include_router(me.router)
app.include_router(admin.router)
app.include_router(documents.router)
app.include_router(documents.page_router)
app.include_router(deadlines.router)
app.include_router(registry.router)
app.include_router(registry.invite_router)
app.include_router(assistant.router)

