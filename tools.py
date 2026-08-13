"""Tools the agent can call. Scoped to whatever worktree `set_worktree()`
points at — set once per run by cli.py before the graph starts.
"""

import os
import subprocess
from pathlib import Path

from langchain_core.tools import tool

from config import NODE_BIN_DIR

_worktree_dir: Path | None = None


def set_worktree(path: Path) -> None:
    global _worktree_dir
    _worktree_dir = path


def get_worktree() -> Path:
    return _worktree_dir


def _node_env() -> dict:
    env = os.environ.copy()
    env["PATH"] = f"{NODE_BIN_DIR}:{env.get('PATH', '')}"
    return env


def _resolve(rel_path: str) -> Path:
    root = _worktree_dir.resolve()
    resolved = (root / rel_path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"Refusing to access path outside the worktree: {rel_path}")
    return resolved


@tool
def list_files(pattern: str = "**/*") -> str:
    """List files in the repository matching a glob pattern (e.g. 'src/content/photos/*.md').
    Use this first to see what already exists before reading or writing.
    """
    root = _worktree_dir
    matches = sorted(
        str(p.relative_to(root))
        for p in root.glob(pattern)
        if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts
    )
    return "\n".join(matches) if matches else "No files matched that pattern."


@tool
def read_file(path: str) -> str:
    """Read a file from the repository. Returns the full content as a string."""
    p = _resolve(path)
    if not p.exists():
        return f"Error: '{path}' does not exist."
    return p.read_text(encoding="utf-8", errors="replace")


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file. Always pass the COMPLETE new content of the
    file, never a diff or partial snippet — this call replaces the whole file.
    """
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path}"


@tool
def delete_file(path: str) -> str:
    """Delete a file from the repository. Use this to remove dead code/unused
    files — do not try to "delete" a file by overwriting it with write_file.
    """
    p = _resolve(path)
    if not p.exists():
        return f"Error: '{path}' does not exist (nothing to delete)."
    if not p.is_file():
        return f"Error: '{path}' is not a regular file — refusing to delete."
    p.unlink()
    return f"Deleted {path}"


@tool
def run_check() -> str:
    """Run the project's `npm run check` (schema/type validation) in the
    worktree and return its output. Call this before finishing.
    """
    result = subprocess.run(
        ["npm", "run", "check"],
        cwd=str(_worktree_dir),
        capture_output=True,
        text=True,
        timeout=180,
        env=_node_env(),
    )
    return f"exit={result.returncode}\n{result.stdout}\n{result.stderr}"[-4000:]


@tool
def run_build() -> str:
    """Run the project's `npm run build` in the worktree and return its output.
    Call this before finishing.
    """
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=str(_worktree_dir),
        capture_output=True,
        text=True,
        timeout=180,
        env=_node_env(),
    )
    return f"exit={result.returncode}\n{result.stdout}\n{result.stderr}"[-4000:]


@tool
def finish(summary: str) -> str:
    """Call this ONLY when you are fully done making changes and validation
    (run_check/run_build) has passed. `summary` must describe exactly what
    files changed and why, for a human reviewer who has not seen your work.
    """
    return summary


all_tools = [list_files, read_file, write_file, delete_file, run_check, run_build, finish]
