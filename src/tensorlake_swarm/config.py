"""
Configuration, logging, and environment-driven constants.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tensorlake_swarm")

# ---------------------------------------------------------------------------
# Config — override via environment variables
# ---------------------------------------------------------------------------

AGENT_COUNT           = int(os.environ.get("AGENT_COUNT", 5))
CLEANUP_ON_EXIT       = os.environ.get("CLEANUP_SNAPSHOT_ON_EXIT", "false").lower() == "true"
EXISTING_SNAPSHOT_ID  = os.environ.get("SNAPSHOT_ID", "")   # skip Phase 1 if set

PERSPECTIVES = ["Security", "Complexity", "Docstrings", "Tests", "Structure"]

# Analysis script is loaded from disk and written into each forked sandbox.
ANALYZE_SCRIPT = (Path(__file__).parent / "analyze.py").read_text()
