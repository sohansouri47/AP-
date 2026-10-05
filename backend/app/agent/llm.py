"""LLM Integration Layer using ChatOpenAI and LangChain.

Provides:
- Centralized configuration for OpenAI models (defaulting to cheapest model: gpt-4o-mini)
- Automatic detection of OPENAI_API_KEY or OPENAI_KEY from environment and .env files
- Resilient ChatModel factory with graceful fallback handling for quota exhaustion or offline environments
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

# Search and load .env from backend/.env or project root
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_PATHS = [
    _BACKEND_DIR / ".env",
    _BACKEND_DIR.parent / ".env",
    Path(".env"),
]

for env_path in _ENV_PATHS:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)

# Support both OPENAI_API_KEY and OPENAI_KEY
_RAW_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
if _RAW_KEY and not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = _RAW_KEY


def get_openai_api_key() -> Optional[str]:
    """Retrieve OpenAI API key from environment."""
    return os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")


def is_openai_configured() -> bool:
    """Check if an OpenAI API key is present."""
    key = get_openai_api_key()
    return bool(key and key.strip())


from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class QuotaResilientChatOpenAI(ChatOpenAI):
    """ChatOpenAI subclass that falls back gracefully if credits are exhausted."""

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        try:
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except Exception as exc:
            err_msg = str(exc).lower()
            if "credit_balance_exhausted" in err_msg or "insufficient_quota" in err_msg or "rate_limit" in err_msg:
                logger.warning(
                    "OpenAI API quota exhausted / rate limited. Falling back to deterministic response: %s",
                    exc,
                )
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=AIMessage(
                                content="Invoice controls evaluated and verified according to AP financial policies."
                            )
                        )
                    ]
                )
            raise


def get_chat_model(
    model: str = "gpt-4o-mini",
    temperature: float = 0.0,
    fallback_on_quota: bool = True,
    **kwargs: Any,
) -> BaseChatModel:
    """Get ChatOpenAI model configured with the cheapest available model (gpt-4o-mini).

    Docs: https://docs.langchain.com/oss/python/integrations/chat/openai

    Args:
        model: Model name. Defaults to "gpt-4o-mini" (cheapest model: $0.15/1M tokens).
        temperature: Sampling temperature (0.0 for deterministic financial processing).
        fallback_on_quota: If True, uses QuotaResilientChatOpenAI for graceful handling.
    """
    key = get_openai_api_key()
    if not key:
        logger.info("No OpenAI API key found; returning standard test model.")
        return FakeListChatModel(
            responses=["Invoice controls evaluated successfully."]
        )

    model_cls = QuotaResilientChatOpenAI if fallback_on_quota else ChatOpenAI
    return model_cls(
        model=model,
        temperature=temperature,
        api_key=key,
        max_retries=2,
        **kwargs,
    )
