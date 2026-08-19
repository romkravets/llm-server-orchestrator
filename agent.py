"""The agent graph:

  planner (one-shot: sketch a short plan before acting — helps on
           structured tasks, e.g. "fix this CSS rule", where pure ReAct
           tends to wander; skipped implicitly for tasks simple enough
           that the plan is just "look, then write")
    -> worker (ReAct: LLM + tools loop)
    -> reviewer (single-shot critique, different model)
       -> if VERDICT: BLOCKING and under the revise budget: revise -> worker
          (Supervisor-style loop-back — reviewer's specific complaint goes
          back to the implementer instead of forcing a full human reject)
       -> otherwise: security (single-shot security scan, different model again)
    -> human_review (interrupt, shows all reports + real diff + whether a
       revise round happened)
    -> resumes with the human's decision

Same worker shape as the workshop's Day 1 agent; reviewer/security is the
Day 3 "multi-agent team with distinct roles" idea applied here, each role
deliberately backed by a different model so no single model reviews its
own work.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import ToolMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from config import (
    HERMES_PROXY_URL,
    IMPLEMENTER_MODEL,
    IMPLEMENTER_PROVIDER,
    MAX_AGENT_STEPS,
    OLLAMA_BASE_URL,
)
from tools import all_tools
import review

NUDGE_MESSAGE = (
    "You have not made any actual change yet — neither write_file nor "
    "delete_file has been called. Looking at files is not enough. You MUST "
    "now call write_file (with the complete new content) or delete_file, "
    "whichever the task requires. Do not describe the fix, do not ask for "
    "clarification — make the change now based on what you found. If you "
    "are genuinely blocked (e.g. the file/section you'd need to edit does "
    "not exist), say so explicitly in your next message instead of a "
    "generic offer to help."
)


class State(TypedDict):
    messages: Annotated[list, add_messages]
    steps: int
    decision: str
    review_notes: str
    security_notes: str
    revise_count: int


REVISE_LIMIT = 1


if IMPLEMENTER_PROVIDER == "hermes":
    # Cloud model via `hermes proxy start --provider nous` (OpenAI-compatible
    # endpoint on localhost — must already be running). Bearer token content
    # is irrelevant; the proxy attaches real credentials itself.
    llm = ChatOpenAI(
        base_url=HERMES_PROXY_URL,
        api_key="unused",
        model=IMPLEMENTER_MODEL,
        temperature=0.2,
        timeout=90,
        max_retries=3,
    )
else:
    # client_kwargs -> merged into the underlying httpx client. Without an
    # explicit timeout, a dropped/stalled connection to Ollama (observed
    # live: process sat idle for 16+ minutes, no model loaded, no GPU
    # activity, plain `ollama serve` still answered other requests fine)
    # hangs the whole run forever instead of surfacing as an error.
    llm = ChatOllama(
        model=IMPLEMENTER_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.2,
        client_kwargs={"timeout": 180},
    )

llm_with_tools = llm.bind_tools(all_tools)

PLAN_REQUEST = (
    "Before touching anything, write a short plan (3-6 numbered steps) for "
    "how you will accomplish this task with the available tools "
    "(list_files, read_file, write_file, delete_file, run_check, run_build). "
    "Plain text only — do not call any tool yet, just the plan."
)


def planner(state: State) -> dict:
    # Plan & Execute pattern for the part ReAct is weak at ("structured
    # problems, multi-step tasks" per the taught framework) — one sketch
    # up front so the ReAct loop that follows has a checklist instead of
    # wandering. The plan is advisory only: the worker can deviate from it
    # once it actually sees the files.
    response = llm.invoke(state["messages"] + [("user", PLAN_REQUEST)])
    plan = response.content or "(no plan produced — proceeding directly)"
    print(f"[office] plan:\n{plan}\n")
    return {"messages": [("user", f"(your plan, for your own reference)\n{plan}\n\nNow execute it using your tools.")]}


def worker(state: State) -> dict:
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response], "steps": state.get("steps", 0) + 1}


def _extract_summary(messages: list) -> str:
    last = messages[-1]
    for tc in getattr(last, "tool_calls", None) or []:
        if tc["name"] == "finish":
            return tc["args"].get("summary", "(finish called without a summary)")
    return getattr(last, "content", None) or "(agent stopped without calling finish)"


_CHANGE_TOOLS = {"write_file", "delete_file"}


def _has_written_files(messages: list) -> bool:
    # Exploring (list_files/read_file) is not enough — require an actual
    # write_file/delete_file call before "finish" (or giving up) is accepted.
    # "finish" itself is intercepted in route_after_worker before ToolNode
    # ever runs it, so this only ever sees genuine tool executions.
    return any(isinstance(m, ToolMessage) and m.name in _CHANGE_TOOLS for m in messages)


def nudge(state: State) -> dict:
    print(f"[office] nudge: agent explored but did not write anything yet (step {state.get('steps', 0)})")
    return {"messages": [("user", NUDGE_MESSAGE)]}


def reviewer_node(state: State) -> dict:
    notes = review.run_reviewer()
    print(f"[office] reviewer:\n{notes}\n")
    return {"review_notes": notes}


def security_node(state: State) -> dict:
    return {"security_notes": review.run_security()}


def _is_blocking(review_notes: str) -> bool:
    return review_notes.strip().upper().startswith("VERDICT: BLOCKING")


def revise(state: State) -> dict:
    # Supervisor-style loop-back (the PR-Review-Team pattern): instead of
    # forcing the human to reject the whole run over one fixable complaint,
    # send the reviewer's specific finding back to the implementer once.
    count = state.get("revise_count", 0) + 1
    print(f"[office] revise: reviewer flagged a blocking issue, sending back to implementer ({count}/{REVISE_LIMIT})\n")
    feedback = (
        "The reviewer found a blocking issue with your change:\n\n"
        f"{state.get('review_notes', '')}\n\n"
        "Fix this specific issue (write_file/delete_file as needed), run "
        "run_check/run_build again, then call finish again."
    )
    return {"messages": [("user", feedback)], "revise_count": count}


def human_review(state: State) -> dict:
    payload = {
        "summary": _extract_summary(state["messages"]),
        "review_notes": state.get("review_notes", ""),
        "security_notes": state.get("security_notes", ""),
        "revised": state.get("revise_count", 0) > 0,
    }
    decision = interrupt(payload)
    return {"decision": decision}


def route_after_worker(state: State) -> str:
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []

    if any(tc["name"] == "finish" for tc in tool_calls):
        return "reviewer"
    if tool_calls:
        return "tools"

    # Model answered in plain text without calling anything this turn.
    if state.get("steps", 0) >= MAX_AGENT_STEPS:
        return "reviewer"  # give up — let the human see what happened
    if not _has_written_files(state["messages"]):
        # Explored, maybe, but never actually wrote a file — refuse to
        # accept this as "done" and push it back to do real work.
        return "nudge"
    return "reviewer"


def route_after_reviewer(state: State) -> str:
    notes = state.get("review_notes", "") or ""
    if _is_blocking(notes) and state.get("revise_count", 0) < REVISE_LIMIT:
        return "revise"
    return "security"


graph_builder = StateGraph(State)
graph_builder.add_node("planner", planner)
graph_builder.add_node("worker", worker)
graph_builder.add_node("tools", ToolNode(tools=all_tools))
graph_builder.add_node("nudge", nudge)
graph_builder.add_node("reviewer", reviewer_node)
graph_builder.add_node("revise", revise)
graph_builder.add_node("security", security_node)
graph_builder.add_node("human_review", human_review)

graph_builder.add_edge(START, "planner")
graph_builder.add_edge("planner", "worker")
graph_builder.add_conditional_edges(
    "worker",
    route_after_worker,
    {"tools": "tools", "nudge": "nudge", "reviewer": "reviewer"},
)
graph_builder.add_edge("tools", "worker")
graph_builder.add_edge("nudge", "worker")
graph_builder.add_conditional_edges(
    "reviewer",
    route_after_reviewer,
    {"revise": "revise", "security": "security"},
)
graph_builder.add_edge("revise", "worker")
graph_builder.add_edge("security", "human_review")

memory = MemorySaver()
graph = graph_builder.compile(checkpointer=memory)
