# TensorLake: Parallel Code Review Swarm

Five specialist agents analyze a Python codebase in parallel. Each runs in an
isolated MicroVM forked from a single shared base snapshot. A lead LLM
synthesizes all five findings into a prioritized fix list.

This is the companion code for the article
**“I Ran 5 AI Agents in Parallel from a Single Memory Snapshot.”**

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

-----

## Project structure

```
tensorlake-parallel-swarm/
├── demo_swarm.py        Main orchestration script
├── analyze.py           Analysis script that runs inside each forked sandbox
├── requirements.txt     Python dependencies (local)
├── .env.example         Template for API keys
├── .gitignore
└── target/
    ├── auth.py          Sample file with intentional security issues
    └── logic.py         Sample file with high cyclomatic complexity
```

-----

## Setup

### 1. Clone and install

```bash
git clone https://github.com/your-username/tensorlake-parallel-swarm
cd tensorlake-parallel-swarm
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
python3 demo_swarm.py
```

Expected runtime: 3-5 minutes. Most of that is the base sandbox build (Phase 1)
and the LLM calls. The parallel swarm itself is fast.

-----

## What it measures

|Metric          |Description                                    |
|----------------|-----------------------------------------------|
|Sequential total|Five agents run one after another (denominator)|
|Parallel total  |Five agents run simultaneously (wall-clock)    |
|Speedup         |Sequential / Parallel                          |
|Efficiency      |Speedup / Agent count x 100                    |

Results are saved to `benchmark_results.json` after each run.

-----

## Reusing the snapshot

Phase 1 (base build and snapshot) only needs to run once. To skip it on
subsequent runs, pass an existing snapshot ID directly:

```python
# In demo_swarm.py, replace:
snapshot_id = await build_base_snapshot()

# With:
snapshot_id = "snps_your_existing_snapshot_id"
```

The snapshot persists until you delete it. Set `CLEANUP_SNAPSHOT_ON_EXIT = True`
at the top of `demo_swarm.py` to delete it automatically after each run.

-----

## The five agents

|Agent     |Tool      |What it finds                                 |
|----------|----------|----------------------------------------------|
|Security  |`bandit`  |Hardcoded secrets, unsafe `eval`, `shell=True`|
|Complexity|`radon cc`|Functions with cyclomatic complexity > 5      |
|Docstrings|`ast`     |Functions and classes missing docstrings      |
|Tests     |`pathlib` |Test file ratio vs source files               |
|Structure |`ast`     |Function, class, and import counts            |

`bandit` and `radon` are installed inside the base sandbox, not locally.
The other three use the Python standard library only — no extra packages needed.

-----

## Adapting for your own codebase

Replace `target/` with your own Python project. The `analyze.py` script reads
from `/workspace/target` inside the sandbox. To point it at a different path,
update the `TARGET` constant at the top of `analyze.py`.

-----

## Key files explained

**`demo_swarm.py`** — orchestrates the full lifecycle: build base sandbox,
take snapshot, run sequential baseline, run parallel swarm, aggregate with LLM,
print benchmark, save results.

**`analyze.py`** — the script that runs inside each forked VM. Receives
`PERSPECTIVE` via environment variable, runs the appropriate analysis,
prints one JSON line to stdout. All analysis is offline.

**`target/`** — sample Python project with intentional issues for the agents
to find. Replace with your own codebase.

-----

## Documentation

- [TensorLake Sandboxes](https://docs.tensorlake.ai/sandboxes/introduction)
- [SDK Reference](https://docs.tensorlake.ai/sandboxes/sdk-reference)
- [Snapshots](https://docs.tensorlake.ai/sandboxes/snapshots)
- [Async SDK](https://docs.tensorlake.ai/sandboxes/async)