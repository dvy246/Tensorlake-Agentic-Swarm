# TensorLake: Parallel Code Review Swarm

Five specialist agents analyze a Python codebase in parallel. Each runs in an
isolated MicroVM forked from a single shared base snapshot. A lead LLM
synthesizes all five findings into a prioritized fix list.

This is the companion code for the article
**"I Ran 5 AI Agents in Parallel from a Single Memory Snapshot."**

-----

## How it works

```
Base sandbox
  - installs bandit + radon
  - writes target project
  - takes a MEMORY snapshot
         |
    snapshot_id
    /    |    \
fork  fork  fork  ...  (5 total)
  |    |    |
Agent  Agent  Agent     <- all run concurrently via asyncio.gather
Security Complexity Docstrings Tests Structure
    \    |    /
     aggregate
     lead LLM
     fix list
```

A MEMORY snapshot captures the full VM state: filesystem, memory, and running
processes. Each fork warm-restores without a cold boot. Setup time is paid
once — not five times.

### Phases

- **Phase 1 — Base Snapshot:** Spins up one sandbox, installs `bandit` + `radon`, writes the target project files, and takes a `CheckpointType.MEMORY` snapshot. This is the only phase that pays the full setup cost.
- **Phase 2 — Agent Fork:** Each agent gets its own sandbox forked from the snapshot via `AsyncSandbox.create(snapshot_id=...)`. The fork warm-restores in ~1 second with tools already installed.
- **Phase 3 — Sequential Baseline:** Runs all five agents one after another to establish a timing baseline. Used to measure the speedup gained by parallelism.
- **Phase 4 — Parallel Swarm:** Runs all five agents concurrently via `asyncio.gather`. Each agent executes `analyze.py` inside its isolated sandbox with a different `PERSPECTIVE` environment variable.
- **Phase 5 — LLM Aggregation:** Collects all five agent reports plus the benchmark data and sends them to GPT-4o. The lead agent synthesizes a single prioritized fix list.

-----

## Project structure

```
tensorlake-swarm/
├── .env.example              Template for API keys
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt          Python dependencies (local)
├── docs/
│   └── article.md            Full technical article
└── src/
    └── tensorlake_swarm/     Main Python package
        ├── __init__.py       Package init (version 1.0.0)
        ├── __main__.py       Entry point: python -m tensorlake_swarm
        ├── config.py         Env vars, logging, constants
        ├── models.py         AgentReport and SwarmResult dataclasses
        ├── snapshot.py       Phase 1: build base sandbox + MEMORY snapshot
        ├── agent.py          Phase 2: fork sandbox + run single agent
        ├── orchestrator.py   Phases 3-4: sequential + parallel execution
        ├── aggregator.py     Phase 5: LLM synthesis of all reports
        ├── benchmark.py      Timing display + JSON persistence
        ├── analyze.py        Analysis script that runs inside each forked sandbox
        ├── verify_imports.py Import validation test
        ├── test_e2e.py       Mock end-to-end integration test
        └── target/
            ├── auth.py       Sample file with intentional security issues
            └── logic.py      Sample file with high cyclomatic complexity
```

-----

## Setup

### 1. Clone and install

```bash
git clone https://github.com/your-username/tensorlake-swarm
cd tensorlake-swarm
pip install -r requirements.txt
```

### 2. Set your API keys

```bash
cp .env.example .env
# Edit .env and fill in TENSORLAKE_API_KEY and OPENAI_API_KEY
```

Or export directly:

```bash
export TENSORLAKE_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
```

Get your TensorLake key at [cloud.tensorlake.ai](https://cloud.tensorlake.ai).

### 3. Run

```bash
python -m tensorlake_swarm
```

Expected runtime: 3-5 minutes. Most of that is the base sandbox build (Phase 1)
and the LLM calls. The parallel swarm itself is fast.

-----

## What it measures

| Metric           | Description                                     |
|------------------|-------------------------------------------------|
| Sequential total | Five agents run one after another (denominator) |
| Parallel total   | Five agents run simultaneously (wall-clock)     |
| Speedup          | Sequential / Parallel                           |
| Efficiency       | Speedup / Agent count × 100                     |

Results are saved to `benchmark_results.json` after each run.

-----

## Reusing the snapshot

Phase 1 (base build and snapshot) only needs to run once. To skip it on
subsequent runs, pass an existing snapshot ID directly:

```python
# In orchestrator.py, replace the build_base_snapshot() call with:
snapshot_id = "snps_your_existing_snapshot_id"
```

The snapshot persists until you delete it. Set `CLEANUP_SNAPSHOT_ON_EXIT=true`
as an environment variable to delete it automatically after each run.

-----

## The five agents

| Agent      | Tool       | What it finds                                  |
|------------|------------|------------------------------------------------|
| Security   | `bandit`   | Hardcoded secrets, unsafe `eval`, `shell=True` |
| Complexity | `radon cc` | Functions with cyclomatic complexity > 5       |
| Docstrings | `ast`      | Functions and classes missing docstrings       |
| Tests      | `pathlib`  | Test file ratio vs source files                |
| Structure  | `ast`      | Function, class, and import counts             |

`bandit` and `radon` are installed inside the base sandbox, not locally.
The other three use the Python standard library only — no extra packages needed.

-----

## Module overview

| Module            | Responsibility                                                    |
|-------------------|-------------------------------------------------------------------|
| `config.py`       | Loads `.env`, configures logging, defines constants                |
| `models.py`       | `AgentReport` and `SwarmResult` dataclasses                       |
| `snapshot.py`     | Creates base sandbox, installs tools, writes target, takes snapshot |
| `agent.py`        | Forks a sandbox from snapshot and runs a single agent              |
| `orchestrator.py` | Runs sequential baseline, then parallel swarm via `asyncio.gather` |
| `aggregator.py`   | Sends all reports to an LLM for a synthesized fix list             |
| `benchmark.py`    | Formats and prints the benchmark table, saves JSON                 |
| `analyze.py`      | Runs inside the sandbox — receives `PERSPECTIVE` env var, outputs JSON |

-----

## Adapting for your own codebase

Replace `src/tensorlake_swarm/target/` with your own Python project. The
`analyze.py` script reads from `/workspace/target` inside the sandbox. To point
it at a different path, update the `TARGET` constant at the top of `analyze.py`.

-----

## Running tests

```bash
# Syntax validation (all .py files parse correctly)
python -c "import ast, os; [ast.parse(open(os.path.join(r,f)).read()) for r,_,fs in os.walk('src/tensorlake_swarm') for f in fs if f.endswith('.py')]"

# Internal import resolution
PYTHONPATH=src python src/tensorlake_swarm/verify_imports.py

# End-to-end mock test (no API keys needed)
PYTHONPATH=src python src/tensorlake_swarm/test_e2e.py
```

-----

## Documentation

- [TensorLake Sandboxes](https://docs.tensorlake.ai/sandboxes/introduction)
- [SDK Reference](https://docs.tensorlake.ai/sandboxes/sdk-reference)
- [Snapshots](https://docs.tensorlake.ai/sandboxes/snapshots)
- [Async SDK](https://docs.tensorlake.ai/sandboxes/async)