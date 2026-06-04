"""
Data models for agent reports and swarm results.
"""

from dataclasses import dataclass
from typing import List


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
