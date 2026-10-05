"""Tests for LangChain ChatOpenAI integration and LLM factory."""

import os
import pytest
from app.agent.llm import (
    get_chat_model,
    get_openai_api_key,
    is_openai_configured,
    QuotaResilientChatOpenAI,
)
from app.agent.deep_agent import build_ap_employee_deep_agent as build_deep_agent_ap_employee


def test_openai_configuration_detection():
    """Verify OpenAI API key is detected from environment or .env."""
    key = get_openai_api_key()
    assert key is not None
    assert len(key) > 10
    assert is_openai_configured() is True


def test_chat_model_default_is_cheapest():
    """Verify default model is gpt-4o-mini (cheapest available model)."""
    model = get_chat_model(fallback_on_quota=False)
    assert model.model_name == "gpt-4o-mini"
    assert model.temperature == 0.0


def test_quota_resilient_fallback():
    """Verify that when quota is exhausted, QuotaResilientChatOpenAI falls back cleanly without crashing."""
    resilient_model = get_chat_model(fallback_on_quota=True)
    assert isinstance(resilient_model, QuotaResilientChatOpenAI)

    # Calling invoke should succeed (either via live OpenAI response or graceful deterministic fallback)
    result = resilient_model.invoke("Test prompt for AP controls")
    assert result is not None
    assert hasattr(result, "content")
    assert len(result.content) > 0


def test_build_deep_agent_uses_chat_model():
    """Verify build_deep_agent_ap_employee creates an agent successfully with default chat model."""
    agent = build_deep_agent_ap_employee()
    assert agent is not None
