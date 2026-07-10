"""LLM client construction for streaming chat across providers."""

from langchain_openai import ChatOpenAI

from ..config import ChatConfig
from ..logging_config import get_logger
from .embeddings import _safe_api_key, normalise_base_url

log = get_logger("llm")


def get_llm(config: ChatConfig):
    provider = config.provider.lower()

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            log.error("langchain-anthropic not installed")
            raise RuntimeError(
                "langchain-anthropic not installed. Run: pip install langchain-anthropic"
            )
        log.info("LLM client: provider=anthropic model=%s", config.model_name)
        return ChatAnthropic(
            model=config.model_name,
            anthropic_api_key=config.api_key,
            streaming=True,
            max_tokens=8192,
        )

    # All OpenAI-compatible providers: Ollama, LM Studio, LiteLLM, OpenAI, Custom
    base_url = normalise_base_url(config.provider, config.base_url)
    api_key = _safe_api_key(config.api_key)
    log.info("LLM client: provider=%s base_url=%s model=%s", provider, base_url, config.model_name)
    return ChatOpenAI(
        model=config.model_name,
        openai_api_base=base_url,
        openai_api_key=api_key,
        streaming=True,
    )
