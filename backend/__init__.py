"""protoRAG+ backend package.

Re-exports the FastAPI app so `uvicorn backend:app` keeps working after the
single-file → package refactor.
"""

# Load .env BEFORE importing app — submodules (auth/deps.py, etc.) read env
# vars at import time, so populating os.environ must happen first. Real env
# vars set by the host (Render, systemd, etc.) win over .env values.
try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    # python-dotenv not installed → just rely on real env vars.
    pass

from .app import app

__all__ = ["app"]
