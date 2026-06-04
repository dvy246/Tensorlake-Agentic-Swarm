"""
Orchestrator — sequential baseline, parallel swarm, and main entry point.
"""

import asyncio
from typing import List

from tensorlake_swarm.agent import run_agent
from tensorlake_swarm.aggregator import aggregate_with_llm
from tensorlake_swarm.benchmark import print_benchmark, save_results
from tensorlake_swarm.config import (
    AGENT_COUNT,
    CLEANUP_ON_EXIT,
    EXISTING_SNAPSHOT_ID,
    PERSPECTIVES,
    log,
)
from tensorlake_swarm.models import AgentReport, SwarmResult
from tensorlake_swarm.snapshot import build_base_snapshot, cleanup_snapshot

import time


# ---------------------------------------------------------------------------
# Phase 3: Sequential baseline
# ---------------------------------------------------------------------------


async def run_sequential(snapshot_id: str, count: int) -> SwarmResult:
    """Run agents one after another. Provides the denominator for speedup."""
    log.info("Phase 3: sequential baseline (%d agents)", count)
    t_start = time.time()

    reports = []
    for i in range(count):
        reports.append(await run_agent(i, snapshot_id))

    total = time.time() - t_start
    log.info("sequential total: %.2fs", total)
    return SwarmResult(mode="sequential", total_time_s=total, agent_count=count, reports=reports)


# ---------------------------------------------------------------------------
# Phase 4: Parallel swarm
# ---------------------------------------------------------------------------


async def run_parallel(snapshot_id: str, count: int) -> SwarmResult:
    """Fork N sandboxes concurrently. One failing agent does not kill the batch."""
    log.info("Phase 4: parallel swarm (%d agents)", count)
    t_start = time.time()

    tasks = [asyncio.create_task(run_agent(i, snapshot_id)) for i in range(count)]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    reports: List[AgentReport] = []
    for i, result in enumerate(raw):
        if isinstance(result, Exception):
            log.warning("agent %d failed and was skipped: %s", i, result)
        else:
            reports.append(result)

    if not reports:
        raise RuntimeError("All agents failed. Check sandbox logs.")

    reports.sort(key=lambda r: r.agent_id)
    total = time.time() - t_start
    log.info("parallel total: %.2fs  (%d/%d agents succeeded)", total, len(reports), count)
    return SwarmResult(mode="parallel", total_time_s=total, agent_count=count, reports=reports)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    log.info("TensorLake parallel swarm  |  agents=%d  perspectives=%s",
             AGENT_COUNT, ", ".join(PERSPECTIVES))

    # Reuse an existing snapshot if SNAPSHOT_ID is set — skips Phase 1.
    if EXISTING_SNAPSHOT_ID:
        snapshot_id = EXISTING_SNAPSHOT_ID
        log.info("reusing snapshot: %s", snapshot_id)
    else:
        snapshot_id = await build_base_snapshot()

    try:
        sequential_result = await run_sequential(snapshot_id, AGENT_COUNT)
        parallel_result   = await run_parallel(snapshot_id, AGENT_COUNT)

        print_benchmark(parallel_result, sequential_result)

        log.info("Phase 5: LLM synthesis...")
        final_report = aggregate_with_llm(parallel_result, sequential_result)

        print("\n" + "=" * 64)
        print("CODE REVIEW REPORT")
        print("=" * 64)
        print(final_report)

        save_results(
            snapshot_id=snapshot_id,
            agent_count=AGENT_COUNT,
            sequential=sequential_result,
            parallel=parallel_result,
            final_report=final_report,
        )

        speedup = sequential_result.total_time_s / parallel_result.total_time_s
        log.info("results saved -> benchmark_results.json")
        log.info("speedup: %.2fx", speedup)

    finally:
        if CLEANUP_ON_EXIT:
            await cleanup_snapshot(snapshot_id)
        else:
            log.info("snapshot retained: %s  (set CLEANUP_SNAPSHOT_ON_EXIT=true to auto-delete)", snapshot_id)
