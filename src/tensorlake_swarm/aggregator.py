"""
Phase 5: Lead LLM aggregation — synthesize agent findings.
"""

import time
import logging

from openai import OpenAI, RateLimitError

from tensorlake_swarm.config import log
from tensorlake_swarm.models import SwarmResult


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
