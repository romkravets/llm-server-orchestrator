"""Entry point: uv run python cli.py "Add a new photo story for Kremenets"

Creates an isolated worktree, runs the agent loop until it calls `finish`
(or hits the step cap), shows the summary for approval, then lands
(commit+merge+push+cleanup) or rejects (discard) based on the answer.
"""

import sys

from langgraph.types import Command

import git_ops
import tools as tools_mod
from agent import graph

SYSTEM_PROMPT = (
    "You are an implementation agent working in an Astro-based photo-archive "
    "repository. Use list_files/read_file to explore before writing anything. "
    "Use write_file to create or modify files — always pass the complete file "
    "content. Follow the existing frontmatter shape used by other files in "
    "src/content/photos/ if the task touches that collection. Run run_check "
    "and run_build to validate your change. Only call finish once validation "
    "passes, with a summary (in Ukrainian) of exactly what changed and why."
)


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: uv run python cli.py "<task description>"')
        sys.exit(1)
    task = sys.argv[1]

    worktree_dir, branch = git_ops.create_worktree()
    print(f"[office] worktree: {worktree_dir}")
    print(f"[office] branch:   {branch}")

    tools_mod.set_worktree(worktree_dir)

    config = {"configurable": {"thread_id": branch}}
    state = {
        "messages": [("system", SYSTEM_PROMPT), ("user", task)],
        "steps": 0,
    }

    print("[office] running agent...")
    result = graph.invoke(state, config)

    interrupts = result.get("__interrupt__")
    model_summary = interrupts[0].value["summary"] if interrupts else None
    ground_truth = git_ops.diff_summary(worktree_dir)

    print("\n" + "=" * 60)
    print("REVIEW")
    print("=" * 60)
    if model_summary and "did not call finish" not in model_summary and "stopped without calling finish" not in model_summary:
        print(model_summary)
        print("-" * 60)
    else:
        print("(модель не дала власного summary — показую реальний diff)")
        print("-" * 60)
    print(ground_truth)
    print("=" * 60)

    answer = input("\nСхвалити? [y/N]: ").strip().lower()

    if answer == "y":
        message = input("Commit message [Enter = task text]: ").strip() or task
        land_result = git_ops.land(worktree_dir, branch, message=message)
        graph.invoke(Command(resume="approved"), config)
        print("[office] landed:")
        for k, v in land_result.items():
            print(f"  {k}: {v}")
    else:
        git_ops.reject(worktree_dir, branch)
        graph.invoke(Command(resume="rejected"), config)
        print("[office] rejected — worktree discarded")


if __name__ == "__main__":
    main()
