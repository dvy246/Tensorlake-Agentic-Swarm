"""
Phase 1: Build base environment and take a MEMORY snapshot.
Snapshot cleanup utility.
"""

import logging
from pathlib import Path

from tensorlake.sandbox import AsyncSandbox, CheckpointType, Sandbox

from tensorlake_swarm.config import log


# ---------------------------------------------------------------------------
# Phase 1: Build base environment and take a MEMORY snapshot
# ---------------------------------------------------------------------------


async def build_base_snapshot() -> str:
    """Install tools, write target project, snapshot. Returns snapshot_id."""
    log.info("Phase 1: building base environment")

    async with await AsyncSandbox.create(
        name="base-swarm-env",
        cpus=2.0,
        memory_mb=2048,
        timeout_secs=600,
    ) as sandbox:
        log.info("  sandbox %s ready", sandbox.sandbox_id)

        result = await sandbox.run(
            "pip",
            ["install", "bandit", "radon", "--user", "--break-system-packages", "-q"],
            timeout=180,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"pip install failed:\n{result.stderr}")
        log.info("  bandit + radon installed")

        # Write target project. All forks inherit this from the snapshot.
        target_dir = Path(__file__).parent / "target"
        for src in target_dir.glob("*.py"):
            dest = f"/workspace/target/{src.name}"
            await sandbox.run("mkdir", ["-p", "/workspace/target"])
            await sandbox.write_file(dest, src.read_bytes())
            log.info("  wrote %s", dest)

        verify = await sandbox.run("python3", ["-m", "bandit", "--version"])
        if verify.exit_code != 0:
            raise RuntimeError(f"bandit not found after install:\n{verify.stderr}")

        log.info("  taking MEMORY snapshot...")
        snapshot = await sandbox.checkpoint(checkpoint_type=CheckpointType.MEMORY)

    if snapshot.status.value != "completed":
        raise RuntimeError(f"Snapshot failed with status: {snapshot.status.value}")

    log.info("  snapshot ready: %s", snapshot.snapshot_id)
    return snapshot.snapshot_id


# ---------------------------------------------------------------------------
# Snapshot cleanup
# ---------------------------------------------------------------------------


async def cleanup_snapshot(snapshot_id: str) -> None:
    """Delete snapshot to avoid storage charges."""
    Sandbox.delete_snapshot(snapshot_id)
    log.info("snapshot %s deleted", snapshot_id)
