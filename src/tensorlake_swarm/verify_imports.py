"""
Verify all modular imports resolve correctly.
Run: PYTHONPATH=src python3 src/tensorlake_swarm/verify_imports.py
"""
import sys
import unittest.mock

# ---------------------------------------------------------------------------
# Mock external dependencies so we can run internal import checks
# ---------------------------------------------------------------------------
mock_dotenv = unittest.mock.MagicMock()
mock_tensorlake = unittest.mock.MagicMock()
mock_tensorlake_sandbox = unittest.mock.MagicMock()
mock_openai = unittest.mock.MagicMock()

# Inject mocks into sys.modules
sys.modules['dotenv'] = mock_dotenv
sys.modules['tensorlake'] = mock_tensorlake
sys.modules['tensorlake.sandbox'] = mock_tensorlake_sandbox
sys.modules['openai'] = mock_openai

print("Mocking external dependencies (dotenv, tensorlake, openai)...")

# ---------------------------------------------------------------------------
# Perform package and module imports
# ---------------------------------------------------------------------------
# Verify config
from tensorlake_swarm.config import AGENT_COUNT, PERSPECTIVES, ANALYZE_SCRIPT, log
print("  - config imported OK")

# Verify models
from tensorlake_swarm.models import AgentReport, SwarmResult
print("  - models imported OK")

# Verify benchmark
from tensorlake_swarm.benchmark import print_benchmark, save_results
print("  - benchmark imported OK")

# Verify snapshot
from tensorlake_swarm.snapshot import build_base_snapshot, cleanup_snapshot
print("  - snapshot imported OK")

# Verify agent
from tensorlake_swarm.agent import run_agent
print("  - agent imported OK")

# Verify aggregator
from tensorlake_swarm.aggregator import aggregate_with_llm
print("  - aggregator imported OK")

# Verify orchestrator
from tensorlake_swarm.orchestrator import run_sequential, run_parallel, main
print("  - orchestrator imported OK")

print("\n" + "=" * 40)
print("ALL INTERNAL PACKAGE IMPORTS OK — Package is valid")
print("=" * 40)
