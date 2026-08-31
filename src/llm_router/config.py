"""Application configuration.

Environment-driven settings for the llm-router service. The router exercises a
trusted home-LAN single-admin model: no auth, no TLS. It owns provider
credentials and purpose->assignment resolution for the whole fleet.
"""

import os
from pathlib import Path

# --- Runtime settings -----------------------------------------------------
# Path to the SQLite database file.
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "llm_router.db")
DATABASE_PATH = os.environ.get("LLM_ROUTER_DB", DEFAULT_DB_PATH)
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Base URL advertised for client resolution (used by docs/CLI hints).
DEFAULT_BASE_URL = os.environ.get("LLM_ROUTER_URL", "http://localhost:8000")

# --- CLI conventions ------------------------------------------------------
CLI_CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
}
