"""LLM client construction for streaming chat across providers."""

from langchain_openai import ChatOpenAI

from ..config import ChatConfig
from .embeddings import _safe_api_key, normalise_base_url


def get_llm(config: ChatConfig):
    provider = config.provider.lower()

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise RuntimeError(
                "langchain-anthropic not installed. Run: pip install langchain-anthropic"
            )
        return ChatAnthropic(
            model=config.model_name,
            anthropic_api_key=config.api_key,
            streaming=True,
            max_tokens=8192,
        )

    # All OpenAI-compatible providers: Ollama, LM Studio, LiteLLM, OpenAI, Custom
    base_url = normalise_base_url(config.provider, config.base_url)
    api_key = _safe_api_key(config.api_key)
    return ChatOpenAI(
        model=config.model_name,
        openai_api_base=base_url,
        openai_api_key=api_key,
        streaming=True,
    )
