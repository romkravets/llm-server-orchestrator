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
    "You are an implementation agent working in the `history` repository "
    "(an Astro-based photo-archive site). You have real tools — use them, "
    "do not just describe what you would do.\n\n"
    "ALWAYS start by calling list_files (e.g. pattern 'src/**/*.astro' or "
    "'src/**/*.css' depending on the task) and read_file on anything "
    "relevant, BEFORE writing or answering anything. If the task is about a "
    "UI/layout bug, find the actual component/CSS responsible — do not "
    "guess or write unrelated documentation.\n\n"
    "Use write_file to make every change — always pass the complete file "
    "content, never a diff or a description. A task is not done until "
    "write_file has actually been called. Follow the existing frontmatter "
    "shape used by other files in src/content/photos/ if the task touches "
    "that collection.\n\n"
    "Run run_check and run_build to validate your change before finishing. "
    "Only call finish once you have made a real change and validation "
    "passes, with a summary (in Ukrainian) of exactly which files changed "
    "and why. Never call finish without having called write_file at least "
    "once."
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
    payload = interrupts[0].value if interrupts else {}
    model_summary = payload.get("summary")
    review_notes = payload.get("review_notes")
    security_notes = payload.get("security_notes")
    ground_truth = git_ops.diff_summary(worktree_dir)

    if ground_truth.startswith("(worktree has no changes"):
        print("\n" + "!" * 60)
        print("УВАГА: агент не зробив ЖОДНОЇ реальної зміни на диску.")
        print("Нижче — лише те, що модель написала текстом. Майже напевно")
        print("варто відхилити ('n') і спробувати переформулювати задачу.")
        print("!" * 60)

    print("\n" + "=" * 60)
    print("IMPLEMENTER")
    print("=" * 60)
    if model_summary and "stopped without calling finish" not in model_summary:
        print(model_summary)
    else:
        print("(модель не дала власного summary — див. реальний diff нижче)")

    print("\n" + "=" * 60)
    print("REVIEWER (deepseek-r1:14b)")
    print("=" * 60)
    print(review_notes or "(немає)")

    print("\n" + "=" * 60)
    print("SECURITY (qwen2.5-coder:7b)")
    print("=" * 60)
    print(security_notes or "(немає)")

    print("\n" + "=" * 60)
    print("РЕАЛЬНИЙ DIFF")
    print("=" * 60)
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
