"""Auto-detection of available LLM providers and models.

Detection populates the *pickable catalog* only. It NEVER creates assignments:
purposes are human intent and must be added explicitly. The detected providers
and models are persisted into SQLite as a cache so a management UI / CLI can
offer them without re-scanning.

Sources, in order of reliability:

- Environment keys -> known cloud providers (with their default base URLs and
  the actual key, since the router owns credentials).
- Localhost port probes -> local OpenAI-compatible servers
  (LM Studio, vLLM, llama.cpp, llamafile, Ollama).
- ``ollama list`` -> locally pulled Ollama models.
- (Future) ``models.dev`` catalog fetch for cloud model listings.
- Manual add as the escape hatch.
"""

import os
import socket
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

# env key -> (provider name, default base URL, prefix)
ENV_PROVIDERS = {
    "OPENAI_API_KEY": ("openai", "https://api.openai.com/v1", "openai"),
    "ANTHROPIC_API_KEY": ("anthropic", "https://api.anthropic.com", "anthropic"),
    "OPENROUTER_API_KEY": ("openrouter", "https://openrouter.ai/api/v1", "openrouter"),
    "GROQ_API_KEY": ("groq", "https://api.groq.com/openai/v1", "groq"),
    "GEMINI_API_KEY": (
        "google",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "google",
    ),
}

# (port, provider name, prefix, base URL) probes for local OpenAI-compatible servers
PORT_PROBES = [
    (11434, "ollama", "ollama", "http://localhost:11434/v1"),
    (1234, "lm-studio", "lmstudy", "http://localhost:1234/v1"),
    (8080, "vllm", "vllm", "http://localhost:8080/v1"),
    (8000, "llamafile", "llamafile", "http://localhost:8000/v1"),
]


@dataclass
class DetectedProvider:
    name: str
    prefix: str
    base_url: str
    api_key: Optional[str] = None


@dataclass
class DetectedModel:
    provider: str
    model: str


@dataclass
class DetectionResult:
    providers: List[DetectedProvider] = field(default_factory=list)
    models: List[DetectedModel] = field(default_factory=list)


def _probe_port(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if a TCP connection can be established to host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def detect_from_env() -> List[DetectedProvider]:
    """Discover cloud providers whose API key is present in the environment."""
    found: List[DetectedProvider] = []
    for key, (name, base_url, prefix) in ENV_PROVIDERS.items():
        value = os.environ.get(key)
        if value:
            found.append(
                DetectedProvider(
                    name=name, prefix=prefix, base_url=base_url, api_key=value
                )
            )
    return found


def detect_local_ports() -> List[DetectedProvider]:
    """Discover local OpenAI-compatible servers by probing well-known ports."""
    found: List[DetectedProvider] = []
    for port, name, prefix, base_url in PORT_PROBES:
        if _probe_port("127.0.0.1", port):
            found.append(DetectedProvider(name=name, prefix=prefix, base_url=base_url))
    return found


def detect_ollama_models() -> List[DetectedModel]:
    """Discover locally pulled Ollama models via ``ollama list``."""
    try:
        out = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return []
    models: List[DetectedModel] = []
    for line in out.strip().splitlines()[1:]:
        if not line.strip():
            continue
        name = line.split()[0]
        if ":" not in name:
            name = f"{name}:latest"
        models.append(DetectedModel(provider="ollama", model=name))
    return models


def scan() -> DetectionResult:
    """Run all detection sources and aggregate the results."""
    result = DetectionResult()
    result.providers = detect_from_env() + detect_local_ports()
    result.models = detect_ollama_models()
    return result
