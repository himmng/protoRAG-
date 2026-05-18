"""protoRAG+ backend package.

Re-exports the FastAPI app so `uvicorn backend:app` keeps working after the
single-file → package refactor.
"""

from .app import app

__all__ = ["app"]
