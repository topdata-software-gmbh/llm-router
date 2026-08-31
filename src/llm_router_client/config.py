"""LLM router client configuration."""

import os

DEFAULT_ROUTER_URL = "http://localhost:8000"


def router_url() -> str:
    """Base URL of the running llm-router service."""
    return os.environ.get("LLM_ROUTER_URL", DEFAULT_ROUTER_URL).rstrip("/")
