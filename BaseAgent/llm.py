# This file is modified from the biomni package
# https://github.com/openbmb/Biomni
# https://github.com/openbmb/Biomni/blob/main/biomni/llm.py
# This is used to get the llm instance based on the model name and source.

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.rate_limiters import InMemoryRateLimiter

if TYPE_CHECKING:
    from BaseAgent.config import BaseAgentConfig

SourceType = Literal["OpenAI", "AzureOpenAI", "Anthropic", "AnthropicFoundry", "Ollama", "Gemini", "Bedrock", "Groq", "Custom"]
ALLOWED_SOURCES: set[str] = set(SourceType.__args__)

# Configure the rate limiter
rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.5,  # Allows one request every 1 second
    check_every_n_seconds=1,  # Checks every second if a request is allowed
    max_bucket_size=1,  # Controls the maximum burst size of requests
)


@dataclass
class UsageMetrics:
    """Unified usage metrics returned by language model clients.

    Token counts follow provider semantics:
    - For Anthropic: ``input_tokens`` is uncached prompt tokens only;
      ``cache_creation_tokens`` and ``cache_read_tokens`` are reported separately.
    - For OpenAI: ``input_tokens`` includes cached tokens; ``cache_read_tokens``
      holds the cached subset (a billing discount, not additive context).
    - ``total_tokens`` = ``input_tokens + output_tokens`` (context size; excludes cache tokens).
    - ``cost`` is the provider-reported or client-estimated USD cost across all token types.
    """

    provider: SourceType
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None  # Anthropic: tokens written to cache (1.25× input rate)
    cache_read_tokens: int | None = None       # Anthropic: from cache (0.1× input rate); OpenAI: cached subset of input_tokens
    thinking_tokens: int | None = None         # Anthropic extended thinking tokens (billed at output rate)
    total_tokens: int | None = None            # input_tokens + output_tokens; see class docstring
    cost: float | None = None
    currency: str | None = "USD"
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Convert the metrics to a serialisable dictionary."""

        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "thinking_tokens": self.thinking_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
            "currency": self.currency if self.cost is not None else None,
            "details": self.details,
        }


def _ensure_mapping(value: Any) -> Mapping[str, Any] | None:
    if hasattr(value, "items"):
        try:
            return dict(value.items())
        except Exception:  # noqa: BLE001
            try:
                return dict(value)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                return None
    return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_response_metadata(response: Any) -> Mapping[str, Any] | None:
    # BaseMessage object with response_metadata or metadata attr: LangChain objects
    if isinstance(response, BaseMessage):
        meta = getattr(response, "response_metadata", None)
        mapping = _ensure_mapping(meta)
        if mapping is not None:
            return mapping
        meta = getattr(response, "metadata", None)
        mapping = _ensure_mapping(meta)
        if mapping is not None:
            return mapping

    mapping = None
    # Plain dict response: Raw client JSON or normalized dict
    if isinstance(response, Mapping):
        mapping = _ensure_mapping(response.get("response_metadata"))
        if mapping is not None:
            return mapping
        return _ensure_mapping(response)

    # Custom object with response_metadata attr: Custom or SDK objects
    if hasattr(response, "response_metadata"):
        mapping = _ensure_mapping(getattr(response, "response_metadata"))
        if mapping is not None:
            return mapping

    return None


def _extract_usage_metrics_unified(provider: SourceType, model: str | None, metadata: Mapping[str, Any]) -> UsageMetrics:
    """Unified usage metrics extraction that handles all provider-specific field variations."""
    raw_metadata = dict(metadata)

    model_name = (
        raw_metadata.get("model")
        or raw_metadata.get("model_name")
        or raw_metadata.get("modelId")  # Bedrock
        or model
    )

    token_usage = _ensure_mapping(raw_metadata.get("token_usage"))
    if token_usage is None:
        token_usage = _ensure_mapping(raw_metadata.get("usage"))

    def lookup(*keys: str) -> Any:
        current: Any = raw_metadata
        for key in keys:
            if not isinstance(current, Mapping):
                return None
            current = current.get(key)
        return current

    if token_usage is None:
        token_usage = _ensure_mapping(lookup("response", "usage"))

    usage_dict = dict(token_usage) if token_usage is not None else {}

    input_tokens = _coerce_int(
        raw_metadata.get("prompt_eval_count")  # Ollama
        or usage_dict.get("prompt_tokens")     # OpenAI
        or usage_dict.get("input_tokens")      # Anthropic/others
        or usage_dict.get("inputTokens")       # Bedrock camelCase
        or raw_metadata.get("inputTokens")     # Bedrock top-level
        or raw_metadata.get("input_tokens")
        or lookup("usage", "prompt_tokens")
        or lookup("usage", "input_tokens")
    )

    output_tokens = _coerce_int(
        raw_metadata.get("eval_count")          # Ollama
        or usage_dict.get("completion_tokens")  # OpenAI
        or usage_dict.get("output_tokens")      # Anthropic/others
        or usage_dict.get("outputTokens")       # Bedrock camelCase
        or raw_metadata.get("outputTokens")     # Bedrock top-level
        or raw_metadata.get("output_tokens")
        or lookup("usage", "completion_tokens")
        or lookup("usage", "output_tokens")
    )

    total_tokens = _coerce_int(
        usage_dict.get("total_tokens")
        or usage_dict.get("totalTokens")    # Bedrock camelCase
        or raw_metadata.get("totalTokens")  # Bedrock top-level
        or raw_metadata.get("total_tokens")
        or lookup("usage", "total_tokens")
    )
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    # Prompt-cache write tokens: Anthropic cache_creation_input_tokens / Bedrock equivalent
    cache_creation_tokens = _coerce_int(
        usage_dict.get("cache_creation_input_tokens")
        or usage_dict.get("cacheCreationInputTokens")  # Bedrock camelCase
    )

    # Prompt-cache read tokens: Anthropic cache_read_input_tokens; OpenAI prompt_tokens_details.cached_tokens
    _prompt_details = _ensure_mapping(usage_dict.get("prompt_tokens_details")) or {}
    cache_read_tokens = _coerce_int(
        usage_dict.get("cache_read_input_tokens")
        or usage_dict.get("cacheReadInputTokens")      # Bedrock camelCase
        or _prompt_details.get("cached_tokens")        # OpenAI
    )

    # Anthropic extended thinking tokens (reported separately from output_tokens)
    thinking_tokens = _coerce_int(usage_dict.get("thinking_input_tokens"))

    # Provider-reported cost only; cost may be None for providers that do not return it
    # (e.g. Anthropic does not include cost in streaming event metadata).
    cost = _coerce_float(
        usage_dict.get("total_cost")
        or usage_dict.get("cost")
        or usage_dict.get("totalCost")      # Bedrock camelCase
        or raw_metadata.get("total_cost")
        or raw_metadata.get("cost")
        or raw_metadata.get("totalCost")    # Bedrock top-level
        or lookup("usage", "total_cost")
        or lookup("usage", "cost")
        or lookup("usage", "estimated_cost")
    )

    currency = raw_metadata.get("currency") or usage_dict.get("currency")

    return UsageMetrics(
        provider=provider,
        model=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        thinking_tokens=thinking_tokens,
        total_tokens=total_tokens,
        cost=cost,
        currency=currency,
        details={"response_metadata": raw_metadata},
    )


def extract_usage_metrics(
    provider: SourceType,
    response: Any,
    *,
    model: str | None = None,
) -> UsageMetrics | None:
    """Extract normalised usage metrics from a language model response."""

    metadata = _get_response_metadata(response)
    if metadata is None:
        return None

    metrics: UsageMetrics = _extract_usage_metrics_unified(provider, model, metadata)
    return metrics


def _detect_source(
    model: str, 
    base_url: str | None = None,
    ) -> SourceType:
    """
    Detect the source of the model based on the model name and base URL. This function is not catching all the cases.
    Args:
        model (str): The model name to detect the source of.
        base_url (str): The base URL of the model.
    Returns:
        SourceType: The source of the model.
    """
    lower_model = model.lower()

    prefix_rules: list[tuple[str | tuple[str, ...], SourceType]] = [
        ("claude-", "Anthropic"),
        ("gpt-oss", "Ollama"),
        ("gpt-", "OpenAI"),
        ("azure-claude-", "AnthropicFoundry"),
        ("azure-gpt-", "AzureOpenAI"),
        ("gemini-", "Gemini"),
    ]

    for prefix, source in prefix_rules:
        if model.startswith(prefix):
            return source

    if base_url is not None:
        return "Custom"

    ollama_markers = {
        "llama",
        "mistral",
        "qwen",
        "gemma",
        "phi",
        "dolphin",
        "orca",
        "vicuna",
        "deepseek",
    }
    if "/" in model or any(marker in lower_model for marker in ollama_markers):
        return "Ollama"

    raise ValueError("Unable to determine model source. Please specify 'source' parameter.")


def get_chatmodel(source: SourceType) -> type[BaseChatModel]:
    """
    Get the appropriate LangChain chat model class for the given source.

    Args:
        source: The provider source type

    Returns:
        The chat model class for the provider

    Raises:
        ImportError: If required package for the source is not installed
        ValueError: If source is not supported
    """
    if source in ("OpenAI", "AzureOpenAI", "Gemini", "Groq", "Custom"):
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI
        except ImportError:
            raise ImportError(
                f"langchain-openai package is required for {source} models. Install with: pip install langchain-openai"
            ) from None

    elif source in ("Anthropic", "AnthropicFoundry"):
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic
        except ImportError:
            raise ImportError(
                "langchain-anthropic package is required for Anthropic models. Install with: pip install langchain-anthropic"
            ) from None

    elif source == "Ollama":
        try:
            from langchain_ollama import ChatOllama
            return ChatOllama
        except ImportError:
            raise ImportError(
                "langchain-ollama package is required for Ollama models. Install with: pip install langchain-ollama"
            ) from None

    elif source == "Bedrock":
        try:
            from langchain_aws import ChatBedrock
            return ChatBedrock
        except ImportError:
            raise ImportError(
                "langchain-aws package is required for Bedrock models. Install with: pip install langchain-aws"
            ) from None

    else:
        raise ValueError(
            f"Invalid source: {source}. Valid options are: {', '.join(ALLOWED_SOURCES)}"
        )


def _build_model_kwargs(
    source: SourceType,
    model: str,
    temperature: float | None = None,
    stop_sequences: list[str] | None = None,
    max_tokens: int = 8192,
    base_url: str | None = None,
    api_key: str | None = None,
    rate_limiter: InMemoryRateLimiter | None = None,
) -> dict[str, Any]:
    """
    Build provider-specific kwargs for chat model initialization.

    Args:
        source: The provider source type
        model: The model name
        temperature: Temperature setting
        stop_sequences: Stop sequences for generation
        max_tokens: Maximum number of tokens for generation
        base_url: Base URL for API
        api_key: API key for authentication
        rate_limiter: Rate limiter for the model
    Returns:
        Dictionary of kwargs for the chat model
    """
    # Base kwargs shared by most providers
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
    }

    # Update optional kwargs
    optional_params = {
        "temperature": temperature,
        "stop_sequences": stop_sequences,
        "max_tokens": max_tokens,
        "base_url": base_url,
        "rate_limiter": rate_limiter,
    }
    kwargs.update({k: v for k, v in optional_params.items() if v is not None})

    # Special handling for gpt-5
    if model.startswith("gpt-5"):
        print("Tuning parameters for gpt-5: temperature=1.0, stop_sequences=None")
        kwargs["temperature"] = 1.0
        kwargs["stop_sequences"] = None

    # Claude Opus 4.7 does not accept temperature
    if "opus-4-7" in model:
        kwargs.pop("temperature", None)

    # Specific handling for each source
    if source == "OpenAI":
        if api_key is None:
            kwargs["api_key"] = os.getenv("OPENAI_API_KEY")
            assert kwargs["api_key"] is not None, f"Please provide an API key or ensure the \"OPENAI_API_KEY\" environment variable is set in .env or config.py file."

    elif source == "AzureOpenAI":
        kwargs["model"] = model.replace("azure-", "")
        if api_key is None:
            kwargs["api_key"] = os.getenv("AZURE_FOUNDRY_API_KEY")
            assert kwargs["api_key"] is not None, f"Please provide an API key or ensure the \"AZURE_FOUNDRY_API_KEY\" environment variable is set in .env or config.py file."
        if base_url is None:
            kwargs["base_url"] = os.getenv("AZURE_FOUNDRY_BASE_URL")
        assert kwargs.get("base_url") is not None, f"Base URL must be provided for {model} in .env or config.py file."

    elif source == "Anthropic":
        if api_key is None:
            kwargs["api_key"] = os.getenv("ANTHROPIC_API_KEY")
            assert kwargs["api_key"] is not None, f"Please provide an API key or ensure the \"ANTHROPIC_API_KEY\" environment variable is set in .env or config.py file."
        # Enable prompt caching by defaultfor supported models
        supported_models = [
            "claude-3-haiku-20240307", "claude-3-5-haiku-20241022", "claude-3-7-sonnet-20250219",
            "claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-opus-4-1-20250805",
            "claude-sonnet-4-5-20250929", "claude-haiku-4-5-20251001"
        ]
        if model in supported_models:
            kwargs["default_headers"] = {"anthropic-beta": "prompt-caching-2024-07-31"}

    elif source == "AnthropicFoundry":
        kwargs["model"] = model.replace("azure-", "")
        if api_key is None:
            kwargs["api_key"] = os.getenv("ANTHROPIC_FOUNDRY_API_KEY")
            assert kwargs["api_key"] is not None, f"Please provide an API key or ensure the \"ANTHROPIC_FOUNDRY_API_KEY\" environment variable is set in .env or config.py file."
        if base_url is None:
            kwargs["base_url"] = os.getenv("ANTHROPIC_FOUNDRY_BASE_URL")
        assert kwargs.get("base_url") is not None, f"Base URL must be provided for {model} in .env or config.py file."

    elif source == "Gemini":
        if api_key is None:
            kwargs["api_key"] = os.getenv("GEMINI_API_KEY")
            assert kwargs["api_key"] is not None, f"Please provide an API key or ensure the \"GEMINI_API_KEY\" environment variable is set in .env or config.py file."
        if base_url is None and os.getenv("GEMINI_BASE_URL"):
            print(f"Using base URL from environment variable \"GEMINI_BASE_URL\".")
            kwargs["base_url"] = os.getenv("GEMINI_BASE_URL")
        else: 
            default_gemini_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            print(f"Using default base URL for Gemini: {default_gemini_base_url}")
            kwargs["base_url"] = default_gemini_base_url

    elif source == "Groq":
        if api_key is None:
            kwargs["api_key"] = os.getenv("GROQ_API_KEY")
            assert kwargs["api_key"] is not None, f"Please provide an API key or ensure the \"GROQ_API_KEY\" environment variable is set in .env or config.py file."
        if base_url is None and os.getenv("GROQ_BASE_URL"):
            print(f"Using base URL from environment variable \"GROQ_BASE_URL\".")
            kwargs["base_url"] = os.getenv("GROQ_BASE_URL")
        else:
            default_groq_base_url = "https://api.groq.com/openai/v1"
            print(f"Using default base URL for Groq: {default_groq_base_url}")
            kwargs["base_url"] = default_groq_base_url

    elif source == "Ollama":
        kwargs["num_ctx"] = 8192 # increase context window to 8192 tokens
        kwargs["num_predict"] = max_tokens or -1
        del kwargs["max_tokens"]

    # Todo: add more specific handling for Bedrock
    elif source == "Bedrock":
        kwargs["region_name"] = os.getenv("AWS_REGION", "us-east-1")

    elif source == "Custom":
        assert base_url is not None, f"Base URL must be provided for custom models."
        assert api_key is not None, f"API key must be provided for custom models."

    return kwargs


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
    stop_sequences: list[str] | None = None,
    source: SourceType | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    config: Optional["BaseAgentConfig"] = None,
) -> tuple[SourceType, BaseChatModel]:
    """
    Get a language model instance based on the specified model name and source.
    This function supports models from OpenAI, Azure OpenAI, Anthropic, Ollama, Gemini, Bedrock, and custom model serving.
    Args:
        model (str): The model name to use
        temperature (float): Temperature setting for generation
        stop_sequences (list): Sequences that will stop generation
        source (str): Source provider: "OpenAI", "AzureOpenAI", "AnthropicFoundry", "Anthropic", "Ollama", "Gemini", "Bedrock", or "Custom"
                      If None, will attempt to auto-detect from model name
        base_url (str): The base URL for custom model serving (e.g., "http://localhost:8000/v1"), default is None
        api_key (str): The API key for the custom llm
        config (BaseAgentConfig): Optional configuration object. If provided, unspecified parameters will use config values
    """
    # Use config values for any unspecified parameters
    if config is not None:
        model = model or config.llm
        temperature = temperature or config.temperature
        source = source or config.source
        base_url = base_url or config.base_url
        api_key = api_key or config.api_key

    # Ensure the model name is provided
    assert model is not None, f"Model name must be provided specifically or available in config.py file."

    # Auto-detect source from model name if not specified
    if source is None:
        print(f"Auto-detecting source from model name: {model}")
        source = _detect_source(model, base_url)

    # Get the appropriate chat model class
    ChatModelClass = get_chatmodel(source)

    # Build provider-specific kwargs
    kwargs = _build_model_kwargs(
        source=source, 
        model=model, 
        temperature=temperature, 
        stop_sequences=stop_sequences, 
        base_url=base_url, 
        api_key=api_key, 
        rate_limiter=rate_limiter,
    )

    # Handle special cases that need custom initialization
    if source == "AnthropicFoundry":
        from anthropic import AnthropicFoundry, AsyncAnthropicFoundry
        import re

        azure_endpoint = kwargs["base_url"]
        azure_api_key = kwargs["api_key"]

        # Extract resource name from base_url (e.g., https://my-resource.services.ai.azure.com/... -> my-resource)
        resource_match = re.match(r"https?://([^.]+)\.services\.ai\.azure\.com", azure_endpoint)
        azure_resource = resource_match.group(1) if resource_match else None

        # Create ChatAnthropic instance
        chat = ChatModelClass(**kwargs)

        # Override both sync and async clients with AnthropicFoundry
        # This is necessary because ChatAnthropic expects standard Anthropic auth,
        # but Azure Foundry uses different auth headers (api-key instead of x-api-key)
        _sync_client_cache = {}
        _async_client_cache = {}

        def _get_sync_client(self):
            if 'client' not in _sync_client_cache:
                # Clear conflicting env vars to avoid SDK picking them up
                saved_env = {}
                for env_key in ['ANTHROPIC_FOUNDRY_RESOURCE', 'ANTHROPIC_FOUNDRY_BASE_URL']:
                    if env_key in os.environ:
                        saved_env[env_key] = os.environ.pop(env_key)
                try:
                    _sync_client_cache['client'] = AnthropicFoundry(
                        api_key=azure_api_key,
                        resource=azure_resource,
                        max_retries=self.max_retries,
                        default_headers=self.default_headers,
                    )
                finally:
                    os.environ.update(saved_env)
            return _sync_client_cache['client']

        def _get_async_client(self):
            if 'client' not in _async_client_cache:
                # Clear conflicting env vars to avoid SDK picking them up
                saved_env = {}
                for env_key in ['ANTHROPIC_FOUNDRY_RESOURCE', 'ANTHROPIC_FOUNDRY_BASE_URL']:
                    if env_key in os.environ:
                        saved_env[env_key] = os.environ.pop(env_key)
                try:
                    _async_client_cache['client'] = AsyncAnthropicFoundry(
                        api_key=azure_api_key,
                        resource=azure_resource,
                        max_retries=self.max_retries,
                        default_headers=self.default_headers,
                    )
                finally:
                    os.environ.update(saved_env)
            return _async_client_cache['client']

        chat.__class__._client = property(_get_sync_client)
        chat.__class__._async_client = property(_get_async_client)

        print(f"Creating AnthropicFoundry model: {model}")
        return source, chat

    elif source == "Ollama":
        chat = ChatModelClass(**kwargs)

        # Apply wrapper for gpt-oss models with tool calling issues
        if "gpt-oss" in model.lower():
            print(f"⚠️  Warning: {model} has tool calling behavior in Ollama.")
            print("   BaseAgent will extract code from tool call errors and wrap it in <execute> tags.")
            print("   For better experience, consider using: 'llama3.2:3b' or 'qwen2.5:7b'")

            class OllamaWithToolCallExtraction:
                """Wrapper that extracts code from Ollama tool call parsing errors for gpt-oss models."""

                def __init__(self, base_llm):
                    self._base_llm = base_llm
                    self.model_name = getattr(base_llm, 'model', None) or getattr(base_llm, 'model_name', None)

                def invoke(self, input, config=None, **kwargs):
                    """Intercept tool call errors and extract the raw code."""
                    try:
                        return self._base_llm.invoke(input, config=config, **kwargs)
                    except Exception as e:
                        error_msg = str(e)
                        if "error parsing tool call" in error_msg and "raw=" in error_msg:
                            import re
                            from langchain_core.messages import AIMessage

                            match = re.search(r"raw='(.*?)'(?:,| \()", error_msg, re.DOTALL)
                            if match:
                                raw_content = match.group(1)
                                raw_content = raw_content.replace('\\n', '\n').replace("\\'", "'").replace('\\"', '"')
                                wrapped_content = f"<execute>\n{raw_content}\n</execute>"
                                return AIMessage(content=wrapped_content)
                        raise

                def __getattr__(self, name):
                    """Forward all other attribute access to the base LLM."""
                    return getattr(self._base_llm, name)

            return source, OllamaWithToolCallExtraction(chat)

        return source, chat

    else:
        # Standard initialization for all other providers
        chat = ChatModelClass(**kwargs)
        return source, chat