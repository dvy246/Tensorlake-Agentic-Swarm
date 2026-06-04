"""
End-to-End Mock Integration Test for tensorlake-swarm.
Run: PYTHONPATH=src python3 src/tensorlake_swarm/test_e2e.py
"""
import sys
import os
import asyncio
import types
import json
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 1. Define Mock classes for TensorLake and OpenAI
# ---------------------------------------------------------------------------

class MockCommandResult:
    def __init__(self, exit_code, stdout, stderr):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

class MockSnapshotStatus:
    def __init__(self, value):
        self.value = value

class MockSnapshotInfo:
    def __init__(self, snapshot_id, status_val):
        self.snapshot_id = snapshot_id
        self.status = MockSnapshotStatus(status_val)

class MockSandbox:
    def __init__(self, name=None, snapshot_id=None):
        self.sandbox_id = "sbx_mock_123"
        self.name = name
        self.snapshot_id = snapshot_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def run(self, cmd, args=None, env=None, timeout=None):
        if cmd == "python3" and args and args[0] == "/workspace/analyze.py":
            perspective = env.get("PERSPECTIVE", "Unknown")
            # Simulate json output produced by analyze.py
            stdout_data = {
                "score": 90,
                "finding": f"Mock finding for {perspective} (All checks passed)",
                "perspective": perspective
            }
            return MockCommandResult(0, json.dumps(stdout_data), "")
        elif cmd == "python3" and args and "bandit" in args:
            return MockCommandResult(0, "bandit 1.7.0", "")
        else:
            return MockCommandResult(0, "success", "")

    async def write_file(self, path, content):
        pass

    async def checkpoint(self, checkpoint_type=None):
        return MockSnapshotInfo("snps_mock_456", "completed")

    @classmethod
    def delete_snapshot(cls, snapshot_id):
        print(f"[Mock Sandbox] Deleted snapshot: {snapshot_id}")

class MockAsyncSandbox:
    @classmethod
    async def create(cls, name=None, cpus=None, memory_mb=None, timeout_secs=None, snapshot_id=None, allow_internet_access=None):
        return MockSandbox(name=name, snapshot_id=snapshot_id)

class MockMessage:
    def __init__(self, content):
        self.content = content

class MockChoice:
    def __init__(self, content):
        self.message = MockMessage(content)

class MockResponse:
    def __init__(self, content):
        self.choices = [MockChoice(content)]

class MockChatCompletions:
    def create(self, model, messages, **kwargs):
        return MockResponse("### Mock Lead Agent Report\n- Overall Health Score: 90/100\n- Top 3 issues: None (Mock runs are clean).\n- Speedup is highly efficient.")

class MockChat:
    def __init__(self):
        self.completions = MockChatCompletions()

class MockOpenAI:
    def __init__(self, **kwargs):
        self.chat = MockChat()

class DummyRateLimitError(Exception):
    pass

# ---------------------------------------------------------------------------
# 2. Inject Mocks into sys.modules
# ---------------------------------------------------------------------------
mock_dotenv = types.ModuleType("dotenv")
mock_dotenv.load_dotenv = lambda: None
sys.modules["dotenv"] = mock_dotenv

mock_tl = types.ModuleType("tensorlake")
sys.modules["tensorlake"] = mock_tl

mock_tl_sb = types.ModuleType("tensorlake.sandbox")
mock_tl_sb.AsyncSandbox = MockAsyncSandbox
mock_tl_sb.Sandbox = MockSandbox
# Define CheckpointType enum mock
@dataclass
class CheckpointTypeMock:
    MEMORY: str = "MEMORY"
    FILESYSTEM: str = "FILESYSTEM"
mock_tl_sb.CheckpointType = CheckpointTypeMock()
sys.modules["tensorlake.sandbox"] = mock_tl_sb

mock_openai = types.ModuleType("openai")
mock_openai.OpenAI = MockOpenAI
mock_openai.RateLimitError = DummyRateLimitError
sys.modules["openai"] = mock_openai

# ---------------------------------------------------------------------------
# 3. Run the E2E Orchestrator Test
# ---------------------------------------------------------------------------
from tensorlake_swarm.orchestrator import main

if __name__ == "__main__":
    print("=" * 64)
    print("STARTING E2E INTEGRATION TEST (MOCKED)")
    print("=" * 64)
    
    # Run the main orchestrator entrypoint
    asyncio.run(main())
    
    print("\n" + "=" * 64)
    print("E2E INTEGRATION TEST COMPLETED SUCCESSFULLY!")
    print("=" * 64)
