"""Vercel / ASGI entrypoint for FastAPI backend."""
from app.main import app

__all__ = ["app"]
