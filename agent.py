"""The agent graph:

  worker (LLM + tools loop)
    -> reviewer (single-shot critique, different model)
    -> security (single-shot security scan, different model again)
    -> human_review (interrupt, shows all three reports + real diff)
    -> resumes with the human's decision

Same worker shape as the workshop's Day 1 agent; reviewer/security is the
Day 3 "multi-agent team with distinct roles" idea applied here, each role
deliberately backed by a different model so no single model reviews its
own work.
"""

from typing import Annotated, TypedDict

from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from config import MAX_AGENT_STEPS, OLLAMA_BASE_URL, OLLAMA_MODEL
from tools import all_tools
import review


class State(TypedDict):
    messages: Annotated[list, add_messages]
    steps: int
    decision: str
    review_notes: str
    security_notes: str


llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.2)
llm_with_tools = llm.bind_tools(all_tools)


def worker(state: State) -> dict:
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response], "steps": state.get("steps", 0) + 1}


def _extract_summary(messages: list) -> str:
    last = messages[-1]
    for tc in getattr(last, "tool_calls", None) or []:
        if tc["name"] == "finish":
            return tc["args"].get("summary", "(finish called without a summary)")
    return getattr(last, "content", None) or "(agent stopped without calling finish)"


def reviewer_node(state: State) -> dict:
    return {"review_notes": review.run_reviewer()}


def security_node(state: State) -> dict:
    return {"security_notes": review.run_security()}


def human_review(state: State) -> dict:
    payload = {
        "summary": _extract_summary(state["messages"]),
        "review_notes": state.get("review_notes", ""),
        "security_notes": state.get("security_notes", ""),
    }
    decision = interrupt(payload)
    return {"decision": decision}


def route_after_worker(state: State) -> str:
    if state.get("steps", 0) >= MAX_AGENT_STEPS:
        return "reviewer"

    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    if any(tc["name"] == "finish" for tc in tool_calls):
        return "reviewer"
    if tool_calls:
        return "tools"
    return "reviewer"


graph_builder = StateGraph(State)
graph_builder.add_node("worker", worker)
graph_builder.add_node("tools", ToolNode(tools=all_tools))
graph_builder.add_node("reviewer", reviewer_node)
graph_builder.add_node("security", security_node)
graph_builder.add_node("human_review", human_review)

graph_builder.add_edge(START, "worker")
graph_builder.add_conditional_edges(
    "worker", route_after_worker, {"tools": "tools", "reviewer": "reviewer"}
)
graph_builder.add_edge("tools", "worker")
graph_builder.add_edge("reviewer", "security")
graph_builder.add_edge("security", "human_review")

memory = MemorySaver()
graph = graph_builder.compile(checkpointer=memory)
