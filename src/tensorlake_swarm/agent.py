"""
Phase 2: Single agent — fork from snapshot, run one perspective.
"""

import json
import time

from tensorlake.sandbox import AsyncSandbox

from tensorlake_swarm.config import ANALYZE_SCRIPT, PERSPECTIVES, log
from tensorlake_swarm.models import AgentReport



async def run_agent(agent_id: int, snapshot_id: str) -> AgentReport:
    """Fork one sandbox from snapshot_id and run analysis for one perspective."""
    perspective = PERSPECTIVES[agent_id % len(PERSPECTIVES)]
    t_start = time.time()
    log.info("  agent %d  forking -> %s", agent_id, perspective)

    async with await AsyncSandbox.create(
        snapshot_id=snapshot_id,
        allow_internet_access=False,
        timeout_secs=120,
    ) as sandbox:

        await sandbox.write_file("/workspace/analyze.py", ANALYZE_SCRIPT.encode())

        result = await sandbox.run(
            "python3",
            ["/workspace/analyze.py"],
            env={"PERSPECTIVE": perspective},
            timeout=60,
        )

    elapsed = time.time() - t_start

    if result.exit_code != 0:
        raise RuntimeError(
            f"agent {agent_id} ({perspective}) exit {result.exit_code}:\n{result.stderr}"
        )

    output = json.loads(result.stdout.strip())
    log.info(
        "  agent %d  %-14s  score=%3d/100  %.2fs",
        agent_id, perspective, output["score"], elapsed,
    )
    return AgentReport(
        agent_id=agent_id,
        perspective=perspective,
        score=output["score"],
        finding=output["finding"],
        execution_time_s=elapsed,
    )
