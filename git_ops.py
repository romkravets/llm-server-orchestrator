"""Git worktree lifecycle: create an isolated worktree, land it (commit +
merge + push + cleanup) once a human approves, or reject it (discard).

Mirrors the same commands proven out in llm-orchestrator's apply.ts —
same shape, just in Python so the agent loop can drive it directly.
"""

import subprocess
import time
from pathlib import Path

from config import REPO_DIR, WORKTREES_DIR


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def create_worktree() -> tuple[Path, str]:
    label = str(int(time.time() * 1000))
    branch = f"agent/{label}"
    worktree_dir = WORKTREES_DIR / label

    WORKTREES_DIR.mkdir(parents=True, exist_ok=True)
    result = _run(["git", "worktree", "add", "-b", branch, str(worktree_dir), "HEAD"], REPO_DIR)
    if result.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {result.stderr.strip()}")

    return worktree_dir, branch


def diff_summary(worktree_dir: Path) -> str:
    """Ground-truth summary of what changed, independent of whether the model
    self-reported anything useful via `finish`. Always shown alongside (or
    instead of) the model's own summary during review.
    """
    status = _run(["git", "status", "--porcelain"], worktree_dir)
    if not status.stdout.strip():
        return "(worktree has no changes on disk)"

    stat = _run(["git", "diff", "--stat", "HEAD"], worktree_dir)
    lines = [f"Файли зі змінами:\n{status.stdout.strip()}"]
    if stat.stdout.strip():
        lines.append(f"\nDiff stat:\n{stat.stdout.strip()}")
    return "\n".join(lines)


def land(worktree_dir: Path, branch: str, message: str, push: bool = True, remove: bool = True) -> dict:
    out: dict = {}

    status = _run(["git", "status", "--porcelain"], worktree_dir)
    if status.stdout.strip():
        _run(["git", "add", "-A"], worktree_dir)
        commit = _run(["git", "commit", "-m", message], worktree_dir)
        if commit.returncode != 0:
            raise RuntimeError(f"git commit failed: {commit.stderr.strip()}")
        out["committed"] = True
    else:
        out["committed"] = False

    merge = _run(["git", "merge", branch, "--no-edit"], REPO_DIR)
    if merge.returncode != 0:
        raise RuntimeError(f"git merge failed: {merge.stderr.strip()}")
    out["merged"] = True
    out["merge_output"] = merge.stdout.strip()

    if push:
        p = _run(["git", "push", "origin", "HEAD"], REPO_DIR)
        if p.returncode != 0:
            raise RuntimeError(f"git push failed: {(p.stderr or p.stdout).strip()}")
        out["pushed"] = True
    else:
        out["pushed"] = False

    if remove:
        r = _run(["git", "worktree", "remove", str(worktree_dir)], REPO_DIR)
        out["worktree_removed"] = r.returncode == 0
        _run(["git", "branch", "-d", branch], REPO_DIR)
    else:
        out["worktree_removed"] = False

    return out


def reject(worktree_dir: Path, branch: str, remove: bool = True) -> dict:
    if not remove:
        return {"worktree_removed": False}
    _run(["git", "worktree", "remove", "--force", str(worktree_dir)], REPO_DIR)
    _run(["git", "branch", "-D", branch], REPO_DIR)
    return {"worktree_removed": True}
