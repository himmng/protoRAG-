"""Run the backend with `python -m backend`."""

import uvicorn


if __name__ == "__main__":
    print("Starting protoRAG+...")
    print("Open http://localhost:8000 in your browser.")
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=True)
