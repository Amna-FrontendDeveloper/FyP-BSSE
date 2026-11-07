"""Production WSGI entry point.

Run with: gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:app
"""

from app import app

__all__ = ["app"]
