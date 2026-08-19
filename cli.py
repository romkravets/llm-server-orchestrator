"""Entry point: uv run python cli.py "Add a new photo story for Kremenets"

Creates an isolated worktree, runs the agent loop until it calls `finish`
(or hits the step cap), shows the summary for approval, then lands
(commit+merge+push+cleanup) or rejects (discard) based on the answer.
"""

import sys

from langchain_core.messages import ToolMessage
from langgraph.types import Command

import git_ops
import notify
import tools as tools_mod
from agent import graph
from config import (
    AUTO_APPROVE_SAFE,
    IMPLEMENTER_MODEL,
    IMPLEMENTER_PROVIDER,
    SAFE_PATH_PREFIXES,
)

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


def _validation_passed(messages: list) -> bool:
    """True only if run_check AND run_build were actually invoked and their
    *last* result each starts with exit=0. The system prompt tells the
    implementer to run both before calling finish, but a prompt is not a
    guarantee — for a change about to land with zero human review, we
    verify the real tool output instead of trusting the model followed
    instructions."""
    last_exit_ok: dict[str, bool] = {}
    for m in messages:
        if isinstance(m, ToolMessage) and m.name in ("run_check", "run_build"):
            content = m.content if isinstance(m.content, str) else str(m.content)
            last_exit_ok[m.name] = content.startswith("exit=0")
    return last_exit_ok.get("run_check") is True and last_exit_ok.get("run_build") is True


def _risk_reason(worktree_dir, messages: list, review_notes: str, security_notes: str, revised: bool) -> str | None:
    """None means "safe to land with no human" — every other return value is
    the human-readable reason a human (via Telegram, or the terminal as a
    fallback) has to look at this one. Deliberately conservative: any
    ambiguity (can't tell what changed, security pass had something to say)
    routes to a human rather than guessing.
    """
    if not AUTO_APPROVE_SAFE:
        return "AUTO_APPROVE_SAFE вимкнено — усе йде через апрув"
    if not _validation_passed(messages):
        return "run_check/run_build не підтверджені як успішні (exit=0) у логах агента"
    if review_notes.strip().upper().startswith("VERDICT: BLOCKING"):
        return "reviewer позначив BLOCKING"
    if revised:
        return "було revise-коло (reviewer раніше знайшов проблему)"
    if len(security_notes.strip()) > 150:
        return "security-пас має суттєві нотатки"

    paths = git_ops.changed_paths(worktree_dir)
    if not paths:
        return "не вдалося визначити змінені файли"
    unsafe = [p for p in paths if not any(p.startswith(pre) for pre in SAFE_PATH_PREFIXES)]
    if unsafe:
        return f"зміни поза safe-шляхами ({', '.join(unsafe[:5])})"
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: uv run python cli.py "<task description>"')
        sys.exit(1)
    task = sys.argv[1]

    worktree_dir, branch = git_ops.create_worktree()
    print(f"[office] worktree:    {worktree_dir}")
    print(f"[office] branch:      {branch}")
    print(f"[office] implementer: {IMPLEMENTER_PROVIDER}/{IMPLEMENTER_MODEL}")

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
    revised = payload.get("revised")
    ground_truth = git_ops.diff_summary(worktree_dir)

    if revised:
        print("\n[office] Reviewer flagged a blocking issue earlier — implementer revised once before this review.")

    no_real_changes = ground_truth.startswith("(worktree has no changes")
    if no_real_changes:
        print("\n" + "!" * 60)
        print("УВАГА: агент не зробив ЖОДНОЇ реальної зміни на диску.")
        print("Нижче — лише те, що модель написала текстом. Авто-відхилення.")
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

    branch_sid = notify.short_id(branch)

    if no_real_changes:
        risk_reason, decision = "агент нічого не змінив на диску", False
    else:
        risk_reason = _risk_reason(
            worktree_dir, result.get("messages", []), review_notes or "", security_notes or "", bool(revised)
        )
        decision = None

    if risk_reason is None:
        print(f"\n[office] авто-затвердження [{branch_sid}]: зміни лише в safe-шляхах, review/security чисті.")
        decision = True
        notify.send(f"✅ auto-approved [{branch_sid}]\nтаск: {task}\n{model_summary or ''}".strip())
    elif decision is None:  # needs a human — try Telegram first, terminal as fallback
        print(f"\n[office] потрібне затвердження ({risk_reason}).")
        if notify.configured():
            print(f"[office] надсилаю запит у Telegram, чекаю на відповідь...")
            body = (
                f"таск: {task}\nпричина гейту: {risk_reason}\n\n"
                f"IMPLEMENTER:\n{model_summary}\n\nREVIEWER:\n{review_notes}\n\n"
                f"SECURITY:\n{security_notes}\n\nDIFF:\n{ground_truth}"
            )
            decision = notify.request_approval(branch, body)
        if decision is None:  # Telegram not configured, or unreachable
            answer = input("\nСхвалити? [y/N]: ").strip().lower()
            decision = answer == "y"

    if decision:
        land_result = git_ops.land(worktree_dir, branch, message=task)
        graph.invoke(Command(resume="approved"), config)
        print("[office] landed:")
        for k, v in land_result.items():
            print(f"  {k}: {v}")
        if risk_reason is not None:
            notify.send(f"✅ landed [{branch_sid}]")
    else:
        git_ops.reject(worktree_dir, branch)
        graph.invoke(Command(resume="rejected"), config)
        print("[office] rejected — worktree discarded")
        if risk_reason is not None and risk_reason != "агент нічого не змінив на диску":
            notify.send(f"❌ rejected [{branch_sid}]")


if __name__ == "__main__":
    main()
