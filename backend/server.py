"""
FastAPI server entry point for the CHR Analytics chatbot API.

Usage:
    cd backend
    python server.py

Or directly via uvicorn (from the backend/ directory):
    uvicorn app.api.chat:app --port 8000 --reload
"""
import os
import sys

# Ensure `app.*` imports resolve when run as `python server.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import uvicorn  # noqa: E402
from app.api.chat import app  # noqa: E402  (must come after load_dotenv)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
