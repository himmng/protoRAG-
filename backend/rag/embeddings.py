"""OpenAI-compatible embeddings construction for every supported provider."""

from langchain_openai import OpenAIEmbeddings

from ..config import ChatConfig
from ..logging_config import get_logger

log = get_logger("embeddings")


def _safe_api_key(key: str) -> str:
    """Return 'dummy' for blank/none keys (OpenAI-compat servers ignore it anyway)."""
    return key.strip() if key and key.strip().lower() not in ("", "none") else "dummy"


def normalise_base_url(provider: str, base_url: str) -> str:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        return url
    if provider.lower() in ("ollama", "lmstudio"):
        return url + "/v1"
    return url


def get_embeddings(config: ChatConfig) -> OpenAIEmbeddings:
    """
    All providers use OpenAI-compatible embeddings.
    For Anthropic (which has no embedding API), base_url must point to a local
    embedding service, e.g. http://localhost:11434/v1 (Ollama).
    """
    if config.provider.lower() == "anthropic":
        embed_url = config.base_url.rstrip("/")
        embed_key = "dummy"
    else:
        embed_url = normalise_base_url(config.provider, config.base_url)
        embed_key = _safe_api_key(config.api_key)

    log.info("Embeddings client: provider=%s base_url=%s model=%s", config.provider, embed_url, config.embedding_model)
    return OpenAIEmbeddings(
        model=config.embedding_model,
        openai_api_base=embed_url,
        openai_api_key=embed_key,
        check_embedding_ctx_length=False,
    )
