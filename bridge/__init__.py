"""Intercom Studio Chat Bridge - Lightweight middleware for AI-powered conversations."""

from dotenv import load_dotenv

__version__ = "1.0.0"

# Load .env at package import time so uvicorn can use env vars
load_dotenv()
