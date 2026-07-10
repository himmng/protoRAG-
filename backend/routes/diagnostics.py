"""Live self-test of the pieces that actually have to work for chat to work.

Answers "is X actually reachable from the backend's own point of view, with
this exact config" directly — instead of a user (or us, several messages
into a support thread) guessing from a vague frontend error whether the
problem is CORS, the backend, or the LLM provider.
"""

import os
import time

import httpx
from fastapi import APIRouter

from ..config import DATA_DIR, ChatConfig
from ..logging_config import get_logger
from ..rag.embeddings import normalise_base_url

router = APIRouter()
log = get_logger("diagnostics")


async def _check_provider(provider: str, base_url: str, api_key: str, timeout: float = 5.0) -> dict:
    """GET <base_url>/models (OpenAI-compatible) and report what happened."""
    if not base_url:
        return {"ok": False, "detail": "No base_url configured."}
    url = normalise_base_url(provider, base_url).rstrip("/") + "/models"
    key = (api_key or "").strip() or "dummy"
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        elapsed_ms = (time.monotonic() - started) * 1000
        if resp.status_code >= 400:
            return {
                "ok": False,
                "detail": f"HTTP {resp.status_code} from {url}",
                "elapsed_ms": round(elapsed_ms),
            }
        models = []
        try:
            models = [m.get("id") for m in resp.json().get("data", [])]
        except Exception:
            pass
        return {"ok": True, "detail": f"Reached {url}", "elapsed_ms": round(elapsed_ms), "models": models}
    except httpx.TimeoutException:
        return {"ok": False, "detail": f"Timed out after {timeout}s reaching {url} — is it running/reachable from the backend host?"}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e} (reaching {url})"}


@router.post("/api/diagnostics")
async def run_diagnostics(config: ChatConfig):
    log.info(
        "diagnostics run: provider=%s base_url=%s model=%s embedding_model=%s",
        config.provider, config.base_url, config.model_name, config.embedding_model,
    )

    checks = {}

    # Data dir: writable is a prerequisite for uploads/sessions/history.
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        probe = os.path.join(DATA_DIR, ".diagnostics_probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        checks["data_dir"] = {"ok": True, "detail": f"{os.path.abspath(DATA_DIR)} is writable"}
    except Exception as e:
        checks["data_dir"] = {"ok": False, "detail": f"{os.path.abspath(DATA_DIR)} not writable: {e}"}

    # CORS: report what's configured so a browser-side "blocked" error is
    # traceable to an actual allowlist mismatch instead of a guess.
    cors_env = os.environ.get("PROTORAG_CORS_ORIGINS", "").strip()
    checks["cors"] = {
        "ok": True,
        "detail": (
            f"PROTORAG_CORS_ORIGINS = {cors_env}" if cors_env
            else "PROTORAG_CORS_ORIGINS unset — wildcard (*) origin, credentials NOT allowed. "
                 "Credentialed requests (guest/Google login) from a different origin will fail."
        ),
    }

    # The two calls that actually have to succeed for a chat message to work.
    if config.provider.lower() == "anthropic":
        checks["llm_provider"] = {"ok": True, "detail": "Anthropic — checked via API key at call time, not pinged here."}
        checks["embedding_provider"] = await _check_provider("anthropic", config.base_url, config.api_key)
    else:
        result = await _check_provider(config.provider, config.base_url, config.api_key)
        checks["llm_provider"] = result
        checks["embedding_provider"] = result  # same OpenAI-compatible endpoint for both

    if checks["llm_provider"].get("ok") and config.model_name:
        available = checks["llm_provider"].get("models") or []
        if available and config.model_name not in available:
            checks["llm_model"] = {
                "ok": False,
                "detail": f"'{config.model_name}' not in the provider's model list: {available}",
            }
        else:
            checks["llm_model"] = {"ok": True, "detail": f"'{config.model_name}' looks available"}

    all_ok = all(c.get("ok") for c in checks.values())
    log.info("diagnostics result: %s", {k: v["ok"] for k, v in checks.items()})
    return {"ok": all_ok, "checks": checks}
