# I Ran 5 AI Agents in Parallel from a Single Memory Snapshot. Here Is What Took 3 Iterations to Get Right.

### Most engineers treat multi-agent speed as a concurrency problem. It is not. The bottleneck is setup time, and memory snapshots change the math entirely.

*~10 min read | AI Engineering | Sandbox Infrastructure | Agent Orchestration | TensorLake | Parallel Execution*

---

My second attempt at a multi-agent benchmark was technically correct and practically useless.

The agents ran in parallel. The code was clean. And the wall-clock time was barely better than sequential. Each agent had spent the first 90 seconds installing analysis tools before running a single line.

You can solve the concurrency problem perfectly and still lose on setup time. 

Five agents each paying a 90-second setup tax is 450 seconds of pure overhead before a single analysis runs. Run that at scale (twenty agents, fifty) and the parallelism gains disappear before you measure them.

The fix was not more threads. It was a memory snapshot. Build the environment once, checkpoint the entire VM state (filesystem, memory, running processes), and fork all five agents from that single frozen moment. Each fork warm-restores rapidly with the tools already loaded. No re-installs. No cold boots.

Here is what that looks like, what took three iterations to get right, and where it still has rough edges.

---

## What This Does (30 Seconds)

The idea is straightforward: instead of five agents each spending 90 seconds installing the same tools, install them once, freeze that environment, and stamp out five identical copies. Each copy runs a different analysis in parallel. A lead LLM reads all five results and tells you what to fix first.

In code:

1. Creates one Linux VM, installs code analysis tools (bandit, radon) and writes a sample Python project
2. Freezes the entire VM state into a memory snapshot (filesystem, memory, running processes included)
3. Forks 5 independent copies, each agent assigned a different analysis task (Security, Complexity, Docstrings, Tests, Structure)
4. Runs all 5 in parallel via `asyncio.gather`, finishing in seconds instead of minutes
5. Feeds all results to a lead LLM that produces a single prioritized fix list

Setup time is paid once, upfront, before any agent runs. The rest of this article explains how.

---

## Why Sandboxes Matter for Agent Workloads

If you have not worked with sandboxes before: think of one as a disposable computer that lives in the cloud. You spin it up, run whatever code you need inside it, and throw it away when you're done. It has its own filesystem, its own processes, its own network. Nothing it does can touch your machine or any other sandbox running at the same time.

That isolation is the whole point. Your agent can install packages, write files, crash badly, or spin up a browser, and none of it bleeds out. When the task is done, you terminate the VM and it is gone. The next agent starts clean.

Most agent frameworks treat the execution environment as an afterthought. The LLM call is the interesting part. The environment is just "wherever the code runs."

That works fine for single-turn tasks. It breaks down fast for anything multi-step.

When an agent needs to install packages, write intermediate files, maintain a browser session across multiple pages, or resume a task from a different machine, you need the execution environment to behave like a persistent object, not a function call that resets on every invocation.

TensorLake gives each agent a MicroVM backed by Firecracker and CloudHypervisor, optimized for fast boot times and strong isolation. Each sandbox is a full Linux VM. It boots in hundreds of milliseconds, persists filesystem and memory state across sessions, and can be snapshotted at any point in its lifecycle.

What changes the math is a single question: what does the snapshot actually capture?

---

## Two Kinds of Snapshots. Very Different Behavior.

Quick vocabulary before the details. TensorLake sandboxes have four lifecycle modes. An **ephemeral** sandbox runs a task and disappears when done, with no name and no persistence between runs. A **named** sandbox outlives the process that created it and can be suspended then reconnected to from any machine. **Suspend** freezes the VM exactly as it is and **resume** brings it back to that same state. A **snapshot** is that frozen moment saved as a reusable artifact. A **fork** is a snapshot restored into a fresh, independent VM.

This article uses the last two.

TensorLake supports two checkpoint types. Most tutorials only mention one.

`CheckpointType.FILESYSTEM` captures disk state only. Restore from it and the new sandbox does a full cold boot: processes restart from scratch, packages get re-imported. Your pip installs survive. Nothing that was in memory does.

`CheckpointType.MEMORY` is different. It captures disk state, VM memory, and all running processes. The restored VM resumes mid-stride, exactly as the source was at checkpoint time. No boot sequence. No re-initialization. If Python had already imported bandit, the fork starts with it loaded. The environment is not rebuilt. It is copied.

> The checkpoint type is not a performance detail. It determines whether your fork is a clone or a restart.

The default when you call `sandbox.checkpoint()` with no arguments is filesystem. That is the wrong choice for a parallel swarm where agents share a prepared environment. You want memory.

One more constraint worth knowing upfront: for memory snapshots, resources (CPUs, RAM) are baked into the snapshot at checkpoint time. You cannot override them when creating forks. Set the right `cpus` and `memory_mb` on the base sandbox before you checkpoint. Every fork inherits them automatically.

---

## The Architecture

The pattern has five distinct phases. Each one has a single responsibility.

```
┌────────────────────────────────────────────────────┐
│             Phase 1: Base Environment              │
│                                                    │
│  AsyncSandbox.create(cpus=2.0, memory_mb=2048)     │
│        │                                           │
│        ▼                                           │
│  run("pip install bandit radon")                   │
│  write_file("/workspace/target/auth.py", ...)      │
│        │                                           │
│        ▼                                           │
│  checkpoint(CheckpointType.MEMORY)                 │
│        │                                           │
│        ▼                                           │
│  snapshot.snapshot_id = "snps_xxxx"                │
│        │                                           │
│  terminate()   ← base sandbox done                 │
└──────────────────────────┬─────────────────────────┘
                           │  snapshot_id
        ┌──────────────────┼────────────────────────────┐
        ▼                  ▼                             ▼
  fork(0)            fork(1)            ...            fork(4)
  Security           Complexity         ...           Structure
        │                  │                             │
        └──────────────────┴─────────────────────────────┘
                           │ asyncio.gather
                           ▼
                 aggregate_with_llm(reports)
```

### The 5 Orchestration Phases

- **Phase 1 — Base Snapshot:** Spins up a single baseline sandbox, installs analysis tools (`bandit`, `radon`), writes the target code, and checkpoints the entire running VM state using `CheckpointType.MEMORY`. The base sandbox is then terminated, leaving behind the reusable snapshot ID.
- **Phase 2 — Agent Forking:** Restores 5 independent sandboxes concurrently from the base snapshot using `sandbox.fork(...)`. Each fork is a warm start that inherits all installed tools, environment settings, and target files.
- **Phase 3 — Sequential Baseline (Timing):** Runs each agent's analysis script (`analyze.py`) one-by-one inside its respective sandbox to measure sequential time as a benchmark denominator.
- **Phase 4 — Parallel Swarm:** Executes all 5 agents concurrently using `asyncio.gather(...)`. Each agent runs the same analysis script inside its isolated sandbox but with a different focus configuration passed via the `PERSPECTIVE` environment variable.
- **Phase 5 — LLM Aggregation:** Collects the individual reports (Security, Complexity, Docstrings, Tests, Structure) alongside the timing data, and passes them to the lead LLM (GPT-4o) to synthesize a single prioritized fix list.

Phase 1 runs once. Phases 2 through 5 run every time you want results. The fork is cheap. The base environment build is not, but you only pay that cost once per snapshot.

---

## Phase 1: Build and Snapshot

The base sandbox installs the analysis tools, writes the target codebase into the VM, then snapshots the entire state. Every fork inherits both the tools and the target project automatically.

```python
from tensorlake.sandbox import AsyncSandbox, CheckpointType

async def build_base_snapshot() -> str:
    async with await AsyncSandbox.create(
        name="base-swarm-env",
        cpus=2.0,
        memory_mb=2048,
        timeout_secs=600,
    ) as sandbox:

        # Install analysis tools. These are baked into the snapshot
        # and available to every forked agent at no extra install cost.
        result = await sandbox.run(
            "pip",
            ["install", "bandit", "radon", "--user", "--break-system-packages", "-q"],
            timeout=180,
        )
        if result.exit_code != 0:
            raise RuntimeError(f"pip install failed:\n{result.stderr}")

        # Write a sample Python project with intentional issues for agents to find.
        # All forks inherit this from the snapshot; no need to write per-agent.
        target_files = {
            "/workspace/target/auth.py": b'''
import subprocess
DB_PASSWORD = "hardcoded_secret_123"

def authenticate(user_input):
    return eval(user_input)

def run_command(cmd):
    return subprocess.call(cmd, shell=True)
''',
            "/workspace/target/logic.py": b'''
def classify(a, b, c, d, e, f, g, h):
    if a and b:
        if c or d:
            if not e and f:
                return "path_a"
            elif e and not f:
                return "path_b"
            elif g and h:
                return "path_c"
            else:
                return "path_d"
        elif g:
            return "path_e"
    return "path_f"
''',
        }
        for path, content in target_files.items():
            parent = "/".join(path.split("/")[:-1])
            await sandbox.run("mkdir", ["-p", parent])
            await sandbox.write_file(path, content)

        # Verify tools work before snapshotting.
        # A broken tool in the snapshot means broken forks.
        verify = await sandbox.run(
            "python3", ["-m", "bandit", "--version"]
        )
        if verify.exit_code != 0:
            raise RuntimeError(f"Tool verification failed:\n{verify.stderr}")

        snapshot = await sandbox.checkpoint(
            checkpoint_type=CheckpointType.MEMORY
        )

    # Context manager terminates the base sandbox here.
    if snapshot.status.value != "completed":
        raise RuntimeError(f"Snapshot failed: {snapshot.status.value}")

    return snapshot.snapshot_id
```

The `async with` pattern guarantees `terminate()` is called on exit, including on exceptions. Without it, any exception before a manual `terminate()` call leaves an orphaned VM running in the background. TensorLake's async documentation shows this pattern explicitly.

`result.exit_code` comes from `CommandResult`, the SDK's return type for `run()`. It has `stdout: str`, `stderr: str`, and `exit_code: int`. Note that `stdout` is already a string, not bytes, so no `.decode()` is needed anywhere.

The status check after `checkpoint()`: `SnapshotStatus` is an enum, so `.value` gives you `"completed"`, `"in_progress"`, or `"failed"`. The documentation shows `checkpoint()` returns a `SnapshotInfo` with a `status` field. Checking that status before proceeding is a useful defensive practice. I learned this after a failed snapshot left me debugging downstream agent failures.

---

## Phase 2: Fork and Run an Agent

This is the actual fork. The call is `AsyncSandbox.create(snapshot_id=snapshot_id)`. No special `fork()` method. No copy-on-write API. Just `create()` with a snapshot ID. Every call produces a fully independent VM starting from that snapshot's frozen state.

```python
PERSPECTIVES = ["Security", "Complexity", "Docstrings", "Tests", "Structure"]

async def run_agent(agent_id: int, snapshot_id: str) -> AgentReport:
    perspective = PERSPECTIVES[agent_id % len(PERSPECTIVES)]
    t_start = time.time()

    # cpus and memory_mb intentionally omitted.
    # For MEMORY snapshots, resources are inherited from the snapshot
    # and cannot be overridden at restore time.
    async with await AsyncSandbox.create(
        snapshot_id=snapshot_id,
        allow_internet_access=False,  # code analysis is offline; no outbound needed
        timeout_secs=120,
    ) as sandbox:

        await sandbox.write_file(
            "/workspace/analyze.py",
            ANALYSIS_SCRIPT.encode("utf-8")
        )

        result = await sandbox.run(
            "python3",
            ["/workspace/analyze.py"],
            env={"PERSPECTIVE": perspective},
            timeout=60,
        )

    elapsed = time.time() - t_start

    if result.exit_code != 0:
        raise RuntimeError(f"Agent {agent_id} failed:\n{result.stderr}")

    output = json.loads(result.stdout.strip())
    return AgentReport(
        agent_id=agent_id,
        perspective=perspective,
        score=output["score"],
        finding=output["finding"],
        execution_time_s=elapsed,
    )
```

`allow_internet_access=False` is safe here because bandit and radon analyze source code and do not make network calls. This parameter is not locked by MEMORY snapshots. TensorLake's networking documentation recommends disabling outbound internet access for untrusted code.

The dispatch script gets written fresh into each forked VM via `sandbox.write_file()`. Each agent's VM is fully isolated: writing to `/workspace/analyze.py` in fork 0 has no effect on fork 1. The target project files are already there, inherited from the snapshot.

Since `result.stdout` is already a Python string, `json.loads(result.stdout.strip())` works directly. The `.strip()` handles the trailing newline from `print()` inside the sandbox.

---

## Sequential First, Then Parallel

The sequential baseline exists for one reason: to give the speedup calculation a real denominator. Without it, you have a time with no context.

```python
async def run_sequential(snapshot_id: str, count: int) -> SwarmResult:
    reports = []
    for i in range(count):
        reports.append(await run_agent(i, snapshot_id))
    return SwarmResult(mode="sequential", ...)

async def run_parallel(snapshot_id: str, count: int) -> SwarmResult:
    # asyncio.gather returns a list of results when awaited.
    reports = await asyncio.gather(
        *(run_agent(i, snapshot_id) for i in range(count))
    )
    reports.sort(key=lambda r: r.agent_id)
    return SwarmResult(mode="parallel", ...)
```

`asyncio.gather` is what TensorLake's async documentation recommends for concurrent sandbox fan-out. The `ThreadPoolExecutor` approach works too (the sync Sandbox API supports it), but if you are already in an async context, `gather` is cleaner.

---

## What the Analysis Script Does

The dispatch script runs inside each forked sandbox. It reads the `PERSPECTIVE` environment variable, routes to the right analysis function, and prints one JSON line to stdout. All five analyses are fully offline, with no network calls needed.

```python
# ANALYSIS_SCRIPT — runs INSIDE each forked sandbox
import json, os, subprocess, ast, pathlib, sys

PERSPECTIVE = os.environ["PERSPECTIVE"]
TARGET = "/workspace/target"

def run_security():
    """bandit: find hardcoded secrets, unsafe eval, shell injection."""
    r = subprocess.run(
        ["python3", "-m", "bandit", "-r", TARGET, "-f", "json", "-q"],
        capture_output=True, text=True
    )
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"score": 0, "finding": "bandit parse error"}
    issues = data.get("results", [])
    high = [i for i in issues if i.get("issue_severity") == "HIGH"]
    return {
        "issues": len(issues), "high": len(high),
        "score": max(0, 100 - len(issues) * 10),
        "finding": high[0]["issue_text"] if high else ("Minor issues" if issues else "Clean"),
    }

def run_complexity():
    """radon: cyclomatic complexity per function."""
    r = subprocess.run(
        ["python3", "-m", "radon", "cc", TARGET, "-j"],
        capture_output=True, text=True
    )
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"score": 0, "finding": "radon parse error"}
    blocks = [b for file_blocks in data.values() for b in file_blocks]
    complex_blocks = [b for b in blocks if b.get("complexity", 0) > 5]
    avg = sum(b["complexity"] for b in blocks) / len(blocks) if blocks else 0
    top = f"{complex_blocks[0]['name']} (cc={complex_blocks[0]['complexity']})" if complex_blocks else "All within threshold"
    return {
        "functions": len(blocks), "complex_count": len(complex_blocks),
        "avg_cc": round(avg, 2),
        "score": max(0, 100 - len(complex_blocks) * 15),
        "finding": top,
    }

def run_docstrings():
    """ast: count functions and classes that lack docstrings."""
    total, documented = 0, 0
    for path in pathlib.Path(TARGET).rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                total += 1
                if ast.get_docstring(node):
                    documented += 1
    pct = int(documented / total * 100) if total else 100
    return {"total": total, "documented": documented, "score": pct,
            "finding": f"{documented}/{total} documented ({pct}%)"}

def run_tests():
    """Count test files relative to source files."""
    all_py = list(pathlib.Path(TARGET).rglob("*.py"))
    test_files = [f for f in all_py if f.stem.startswith("test_") or f.stem.endswith("_test")]
    ratio = len(test_files) / len(all_py) * 100 if all_py else 0
    return {
        "source_files": len(all_py), "test_files": len(test_files),
        "score": min(100, int(ratio * 2)),
        "finding": f"{len(test_files)}/{len(all_py)} files are tests ({ratio:.0f}%)",
    }

def run_structure():
    """ast: count functions, classes, imports across the codebase."""
    stats = {"functions": 0, "classes": 0, "imports": 0, "files": 0}
    for path in pathlib.Path(TARGET).rglob("*.py"):
        stats["files"] += 1
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):          stats["functions"] += 1
            elif isinstance(node, ast.ClassDef):           stats["classes"] += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)): stats["imports"] += 1
    fpr = stats["functions"] / stats["files"] if stats["files"] else 0
    return {**stats, "functions_per_file": round(fpr, 1),
            "score": min(100, int(fpr * 20)),
            "finding": f"{stats['functions']} functions across {stats['files']} files"}

dispatch = {
    "Security":   run_security,
    "Complexity": run_complexity,
    "Docstrings": run_docstrings,
    "Tests":      run_tests,
    "Structure":  run_structure,
}

fn = dispatch.get(PERSPECTIVE)
if fn is None:
    print(json.dumps({"error": f"Unknown perspective: {PERSPECTIVE}"}))
    sys.exit(1)

result = fn()
result["perspective"] = PERSPECTIVE
print(json.dumps(result))
```

Two things worth keeping when you adapt this.

Parameters via environment variables: `sandbox.run(env={"KEY": "val"})` passes per-command variables and avoids shell escaping issues when values contain spaces or special characters. It also keeps the dispatch script stateless, with no hardcoded perspective names inside the script itself.

JSON to stdout: the orchestrator reads `result.stdout.strip()` and passes it directly to `json.loads()`. The script has one job: print exactly one valid JSON line. Any other stdout output (debug prints, progress bars) breaks the parse. Keep it strict.

---

## Phase 5: Lead Agent Synthesis

After all five agents return, a single GPT-4o call synthesizes their findings into a prioritized action list.

```python
def aggregate_with_llm(parallel: SwarmResult, sequential: SwarmResult) -> str:
    client = OpenAI()
    speedup = sequential.total_time_s / parallel.total_time_s

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

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content
```

The lead agent sees both the analysis findings and the timing benchmark in the same context. That is the reduce step in a map-reduce agent pattern: give the aggregator everything the workers produced, not just the domain data. The call is synchronous because there is nothing left to concurrently await at this point.

---

## Where the Time Actually Goes

Both timelines contain the same agents doing the same work. What changes is when setup happens. These numbers are structural projections based on typical pip install times and sandbox warm-restore behavior, not measured results. Your numbers will vary by workload and network conditions. Run the demo to measure your case.

Without memory snapshots:
```
Agent 0: [setup ~90s][work ~8s]
Agent 1: [setup ~90s][work ~9s]
Agent 2: [setup ~90s][work ~8s]
Agent 3: [setup ~90s][work ~9s]
Agent 4: [setup ~90s][work ~8s]

Sequential total: ~490s
Parallel total:   ~100s  (setup still paid by each fork separately)
```

With memory snapshots (MEMORY type):
```
Base build:  [setup ~90s][checkpoint ~3s]  ← paid once, outside the loop
Agent 0: [warm fork ~1s][work ~8s]
Agent 1: [warm fork ~1s][work ~9s]
Agent 2: [warm fork ~1s][work ~8s]
Agent 3: [warm fork ~1s][work ~9s]
Agent 4: [warm fork ~1s][work ~8s]

Sequential total: ~48s
Parallel total:   ~10s
```

The speedup ratio looks similar on paper. The absolute time is not. At five agents the gap is 450 seconds versus 5 seconds of overhead. At fifty agents it is 4,500 seconds versus 50 seconds.

> Setup time does not scale down with parallelism. It multiplies. The snapshot moves it outside the loop entirely.

The benchmark captures four numbers: sequential total time (the denominator), parallel total time (wall-clock from first fork to last return), speedup (sequential divided by parallel), and efficiency (speedup divided by agent count, multiplied by 100).

Efficiency is the one most benchmarks skip. A 4.2x speedup across five agents is 84% parallel efficiency: 16% is lost to fork startup, scheduling, and I/O contention. That number matters when you scale from five agents to fifty.

---

## What the Code Does Not Handle

The demo covers the happy path. Three things to add before production:

- **LLM rate limits.** Twenty or thirty concurrent agents all hitting the OpenAI API will trigger rate limit errors. The demo has no retry logic. Add exponential backoff before you scale.
- **Snapshot storage.** Snapshots may incur charges depending on your plan. Use `Sandbox.delete_snapshot(snapshot_id)` when done. The demo has a `CLEANUP_SNAPSHOT_ON_EXIT` flag at the top of the file.
- **Agent error isolation.** If one `run_agent()` coroutine raises inside `asyncio.gather`, the whole batch fails. In production, wrap each coroutine with `asyncio.create_task()` and handle errors per-agent.

---

## When to Use This Pattern (And When Not To)

Use it when:

- Multiple agents need the same environment
- Their tasks are independent (no inter-agent communication mid-run)
- Setup time is a meaningful fraction of total runtime
- Reproducibility matters: every fork starts from an identical state

Skip it when:

- Agents need to share state during execution. Forks are fully isolated. If agent 2 needs to react to what agent 1 found, use shared storage or message queues instead.
- The task is fast enough for a single agent. Forking five sandboxes for a 3-second job adds overhead, not speed.
- Environment setup takes under 5 seconds. The snapshot overhead only pays off when setup is the actual bottleneck.

| Your situation | Right choice |
|---|---|
| Multiple agents, shared dependencies, independent outputs | Memory snapshot, fork N copies |
| Single agent, long task, needs to pause and resume | Named sandbox with suspend/resume |
| Pure browser automation, no code execution | Stagehand or BrowserBase |
| Stateless task, resets every run | Ephemeral sandbox, no snapshot needed |
| Environment setup under 5 seconds | Filesystem snapshot or skip snapshots |

On filesystem performance: TensorLake publishes performance benchmarks on their GitHub comparing sandbox execution times across providers. Refer to their repository for current numbers.

---

## Running This

```bash
pip install tensorlake openai
export TENSORLAKE_API_KEY="your-key"
export OPENAI_API_KEY="your-key"
python3 demo_swarm.py
```

Free tier at cloud.tensorlake.ai, no credit card required. The demo takes 3-5 minutes end to end. After it runs, `benchmark_results.json` has the full per-agent timing data.

Phase 1 (base build and snapshot) runs once. If you want to run the benchmark multiple times, pass your existing snapshot ID directly and skip Phase 1. The snapshot persists between runs until you delete it.

---

## What Actually Took Three Iterations

The first version had plain `await sandbox.terminate()` at the end of each function. Two exceptions during testing left sandboxes running and billing for idle compute. Switched to `async with await AsyncSandbox.create(...) as sandbox:` and that stopped.

The second version called `sandbox.checkpoint(sandbox.sandbox_id)`. I had copied the pattern from a CLI reference (`tl sbx checkpoint <sandbox-id>`) and assumed the Python SDK matched. It does not. The Python instance method takes no positional arguments: `sandbox.checkpoint(checkpoint_type=CheckpointType.MEMORY)`. That is it.

The third version was the first one that ran end to end, but with `CheckpointType.FILESYSTEM` by default because I had not read the snapshots documentation carefully. The benchmark looked reasonable. The forks were doing full cold boots and I was measuring them alongside the actual work. Switching to `CheckpointType.MEMORY` was the change that made setup time disappear from per-fork timing.

Small mistakes individually. What they share: TensorLake's API is well documented, but the snapshot docs, the SDK reference, and the async docs are three separate pages. Read only the quickstart and you miss two of the three things that matter most for this pattern.

---

## The Thing That Changes

Running the same five agents sequentially and then in parallel is one of those moments where the architecture becomes legible in a way that documentation does not fully convey.

The snapshot moves setup cost from inside the loop to outside it. The agents still do the same work on the same hardware. The savings come from not rebuilding an environment five times when it only needed to be built once.

Most multi-agent optimization advice focuses on LLM calls: batching, caching, cheaper models. That advice is right. But if you have five agents each spending 90 seconds on pip installs before making a single inference call, no amount of LLM optimization helps until you address setup time first.

The bottleneck was never the agents. It was rebuilding the same environment on every run. Snapshot it once, fork cheaply, and parallel execution finally delivers what you expected when you first wrote `asyncio.gather`.

---
