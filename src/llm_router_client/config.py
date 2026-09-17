"""LLM router client configuration."""

import os
from typing import Optional

DEFAULT_ROUTER_URL = "http://localhost:8202"  # reserved port, see ~/devel/port-map


def router_url() -> str:
    """Base URL of the running llm-router service."""
    return os.environ.get("LLM_ROUTER_URL", DEFAULT_ROUTER_URL).rstrip("/")


def router_token() -> Optional[str]:
    """Bearer JWT for the router, if configured via ``LLM_ROUTER_TOKEN``."""
    return os.environ.get("LLM_ROUTER_TOKEN") or None
