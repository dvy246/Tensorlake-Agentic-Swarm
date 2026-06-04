"""
Benchmark display and results persistence.
"""

import json
from dataclasses import asdict

from tensorlake_swarm.models import SwarmResult


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
# Results persistence
# ---------------------------------------------------------------------------


def save_results(
    snapshot_id: str,
    agent_count: int,
    sequential: SwarmResult,
    parallel: SwarmResult,
    final_report: str,
    output_path: str = "benchmark_results.json",
) -> None:
    """Save benchmark results and final report to JSON."""
    speedup = sequential.total_time_s / parallel.total_time_s
    output = {
        "snapshot_id":   snapshot_id,
        "snapshot_type": "MEMORY",
        "agent_count":   agent_count,
        "sequential": {
            "total_time_s": sequential.total_time_s,
            "reports":      [asdict(r) for r in sequential.reports],
        },
        "parallel": {
            "total_time_s": parallel.total_time_s,
            "speedup":      round(speedup, 3),
            "reports":      [asdict(r) for r in parallel.reports],
        },
        "final_report": final_report,
    }
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
