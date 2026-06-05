"""
TensorLake parallel code review swarm.
Five agents analyze a codebase concurrently from a single MEMORY snapshot.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError
from tensorlake.sandbox import AsyncSandbox, CheckpointType, Sandbox

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — override via environment variables
# ---------------------------------------------------------------------------

AGENT_COUNT           = int(os.environ.get("AGENT_COUNT", 5))
CLEANUP_ON_EXIT       = os.environ.get("CLEANUP_SNAPSHOT_ON_EXIT", "false").lower() == "true"
EXISTING_SNAPSHOT_ID  = os.environ.get("SNAPSHOT_ID", "")   # skip Phase 1 if set

PERSPECTIVES = ["Security", "Complexity", "Docstrings", "Tests", "Structure"]

# Analysis script is loaded from disk and written into each forked sandbox.
ANALYZE_SCRIPT = (Path(__file__).parent / "analyze.py").read_text()

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AgentReport:
    agent_id: int
    perspective: str
    score: int
    finding: str
    execution_time_s: float


@dataclass
class SwarmResult:
    mode: str
    total_time_s: float
    agent_count: int
    reports: List[AgentReport]


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
# Phase 2: Single agent — fork from snapshot, run one perspective
# ---------------------------------------------------------------------------


async def run_agent(agent_id: int, snapshot_id: str) -> AgentReport:
    """Fork one sandbox from snapshot_id and run analysis for one perspective."""
    perspective = PERSPECTIVES[agent_id % len(PERSPECTIVES)]
    t_start = time.time()
    log.info("  agent %d  forking -> %s", agent_id, perspective)

    async with await AsyncSandbox.create(
        snapshot_id=snapshot_id,
        # cpus / memory_mb omitted — inherited from snapshot for MEMORY restores
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
# Phase 5: Lead LLM aggregation
# ---------------------------------------------------------------------------


def aggregate_with_llm(parallel: SwarmResult, sequential: SwarmResult) -> str:
    """Synthesize all agent findings into a single prioritized report."""
    client   = OpenAI()
    speedup  = sequential.total_time_s / parallel.total_time_s

    reports_block = "\n".join(
        f"[{r.perspective}] Score: {r.score}/100 | {r.finding}"
        for r in parallel.reports
    )

    prompt = (
        "You are a senior engineering lead reviewing a parallel code analysis report.\n\n"
        f"Agent Findings:\n{reports_block}\n\n"
        "Benchmark:\n"
        f"  Sequential : {sequential.total_time_s:.2f}s\n"
        f"  Parallel   : {parallel.total_time_s:.2f}s\n"
        f"  Speedup    : {speedup:.2f}x\n\n"
        "Provide: overall codebase health score, top three issues to fix immediately "
        "(with file and severity), recommended next actions, and one sentence on what "
        "the parallel speedup means for running this at scale."
    )

    for attempt in range(5):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except RateLimitError:
            wait = 2 ** attempt
            log.warning("OpenAI rate limit hit, retrying in %ds...", wait)
            time.sleep(wait)

    raise RuntimeError("OpenAI rate limit: all retries exhausted.")


# ---------------------------------------------------------------------------
# Benchmark display
# ---------------------------------------------------------------------------


def print_benchmark(parallel: SwarmResult, sequential: SwarmResult) -> None:
    speedup    = sequential.total_time_s / parallel.total_time_s
    efficiency = (speedup / parallel.agent_count) * 100

    print("\n" + "=" * 64)
    print("BENCHMARK")
    print("=" * 64)
    print(f"{'Mode':<16} {'Total':>10}  {'Agents':>6}  {'Avg/Agent':>10}")
    print(f"{'-'*16} {'-'*10}  {'-'*6}  {'-'*10}")
    avg_seq = sequential.total_time_s / sequential.agent_count
    avg_par = parallel.total_time_s   / parallel.agent_count
    print(f"{'Sequential':<16} {sequential.total_time_s:>9.2f}s  {sequential.agent_count:>6}  {avg_seq:>9.2f}s")
    print(f"{'Parallel':<16}   {parallel.total_time_s:>9.2f}s  {parallel.agent_count:>6}  {avg_par:>9.2f}s")
    print(f"\n  Speedup    : {speedup:.2f}x")
    print(f"  Efficiency : {efficiency:.1f}%")
    print("=" * 64)

    print("\nPer-agent (parallel):")
    for r in parallel.reports:
        bar = "#" * int(r.execution_time_s * 2)
        print(f"  [{r.agent_id}] {r.perspective:<14} {r.execution_time_s:.2f}s  score={r.score}/100  {bar}")


# ---------------------------------------------------------------------------
# Snapshot cleanup
# ---------------------------------------------------------------------------


async def cleanup_snapshot(snapshot_id: str) -> None:
    """Delete snapshot to avoid storage charges."""
    Sandbox.delete_snapshot(snapshot_id)
    log.info("snapshot %s deleted", snapshot_id)


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

        speedup = sequential_result.total_time_s / parallel_result.total_time_s
        output = {
            "snapshot_id":   snapshot_id,
            "snapshot_type": "MEMORY",
            "agent_count":   AGENT_COUNT,
            "sequential": {
                "total_time_s": sequential_result.total_time_s,
                "reports":      [asdict(r) for r in sequential_result.reports],
            },
            "parallel": {
                "total_time_s": parallel_result.total_time_s,
                "speedup":      round(speedup, 3),
                "reports":      [asdict(r) for r in parallel_result.reports],
            },
            "final_report": final_report,
        }
        with open("benchmark_results.json", "w") as f:
            json.dump(output, f, indent=2)

        log.info("results saved -> benchmark_results.json")
        log.info("speedup: %.2fx", speedup)

    finally:
        if CLEANUP_ON_EXIT:
            await cleanup_snapshot(snapshot_id)
        else:
            log.info("snapshot retained: %s  (set CLEANUP_SNAPSHOT_ON_EXIT=true to auto-delete)", snapshot_id)


if __name__ == "__main__":
    asyncio.run(main())
