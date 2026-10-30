"""
WSGI entrypoint fallback for hosting providers (e.g. Render default 'gunicorn app:app').
"""
import os
import sys

# Ensure project root is in Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set Django settings module if not already set
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

# Import the standard Django WSGI application
from backend.wsgi import application as app

# Expose 'application' for standard WSGI servers
application = app
