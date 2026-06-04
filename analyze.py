"""
Runs INSIDE each forked TensorLake sandbox.
Receives PERSPECTIVE via env var, prints one JSON line to stdout.
All analysis is offline — no network calls required.
"""

import ast
import json
import os
import pathlib
import subprocess
import sys

PERSPECTIVE = os.environ.get("PERSPECTIVE", "")
TARGET = "/workspace/target"


def run_security() -> dict:
    """bandit: hardcoded secrets, unsafe eval, shell injection."""
    r = subprocess.run(
        ["python3", "-m", "bandit", "-r", TARGET, "-f", "json", "-q"],
        capture_output=True,
        text=True,
    )
    # bandit exits 1 when issues are found — that is expected, not an error.
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"score": 0, "finding": "bandit parse error", "issues": 0, "high": 0}

    issues = data.get("results", [])
    high = [i for i in issues if i.get("issue_severity") == "HIGH"]
    return {
        "issues": len(issues),
        "high": len(high),
        "score": max(0, 100 - len(issues) * 10),
        "finding": (
            high[0]["issue_text"] if high
            else ("Minor issues found" if issues else "Clean")
        ),
    }


def run_complexity() -> dict:
    """radon: cyclomatic complexity per function, flag anything above 5."""
    r = subprocess.run(
        ["python3", "-m", "radon", "cc", TARGET, "-j"],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"score": 0, "finding": "radon parse error", "functions": 0, "complex_count": 0}

    blocks = [b for file_blocks in data.values() for b in file_blocks]
    complex_blocks = [b for b in blocks if b.get("complexity", 0) > 5]
    avg = sum(b["complexity"] for b in blocks) / len(blocks) if blocks else 0
    top = (
        f"{complex_blocks[0]['name']} (cc={complex_blocks[0]['complexity']})"
        if complex_blocks else "All within threshold"
    )
    return {
        "functions": len(blocks),
        "complex_count": len(complex_blocks),
        "avg_cc": round(avg, 2),
        "score": max(0, 100 - len(complex_blocks) * 15),
        "finding": top,
    }


def run_docstrings() -> dict:
    """ast: ratio of functions and classes that have docstrings."""
    total, documented = 0, 0
    for path in pathlib.Path(TARGET).rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                total += 1
                if ast.get_docstring(node):
                    documented += 1
    pct = int(documented / total * 100) if total else 100
    return {
        "total": total,
        "documented": documented,
        "score": pct,
        "finding": f"{documented}/{total} documented ({pct}%)",
    }


def run_tests() -> dict:
    """Count test files relative to total source files."""
    all_py = list(pathlib.Path(TARGET).rglob("*.py"))
    test_files = [f for f in all_py if f.stem.startswith("test_") or f.stem.endswith("_test")]
    ratio = len(test_files) / len(all_py) * 100 if all_py else 0
    return {
        "source_files": len(all_py),
        "test_files": len(test_files),
        "score": min(100, int(ratio * 2)),
        "finding": f"{len(test_files)}/{len(all_py)} files are tests ({ratio:.0f}%)",
    }


def run_structure() -> dict:
    """ast: function, class, and import counts across the codebase."""
    stats = {"functions": 0, "classes": 0, "imports": 0, "files": 0}
    for path in pathlib.Path(TARGET).rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        stats["files"] += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                stats["functions"] += 1
            elif isinstance(node, ast.ClassDef):
                stats["classes"] += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                stats["imports"] += 1
    fpr = stats["functions"] / stats["files"] if stats["files"] else 0
    return {
        **stats,
        "functions_per_file": round(fpr, 1),
        "score": min(100, int(fpr * 20)),
        "finding": f"{stats['functions']} functions across {stats['files']} files",
    }


dispatch = {
    "Security":   run_security,
    "Complexity": run_complexity,
    "Docstrings": run_docstrings,
    "Tests":      run_tests,
    "Structure":  run_structure,
}

fn = dispatch.get(PERSPECTIVE)
if fn is None:
    print(json.dumps({"error": f"Unknown perspective: {PERSPECTIVE!r}"}))
    sys.exit(1)

result = fn()
result["perspective"] = PERSPECTIVE
print(json.dumps(result))
