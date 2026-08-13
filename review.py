"""Reviewer and Security passes: single (non-tool-calling) LLM calls over the
implementer's diff, run before the human ever sees it. Deliberately different
models from the implementer — a second/third pair of eyes catches things the
implementer's own model is systematically blind to.
"""

from langchain_ollama import ChatOllama

from config import OLLAMA_BASE_URL, REVIEWER_MODEL, SECURITY_MODEL
import git_ops
import tools

REVIEWER_PROMPT = """You are a senior code reviewer for an Astro-based photo-archive site.
Review this diff for bugs, regressions, broken schema/frontmatter fields, and
bad practices. Be concise (max ~10 lines). If there is nothing wrong, say so
in one line — do not invent problems. Answer in Ukrainian.

Diff:
{diff}
"""

SECURITY_PROMPT = """You are a security reviewer. Look ONLY for security-relevant
issues in this diff: path traversal, injected/unsafe shell commands, secrets
or API keys committed, unsafe external links or scripts, XSS-prone content.
Ignore style/quality issues — that is someone else's job. Be concise. If
nothing security-relevant is present, say so in one line. Answer in Ukrainian.

Diff:
{diff}
"""


def run_reviewer() -> str:
    diff = git_ops.full_diff(tools.get_worktree())
    llm = ChatOllama(model=REVIEWER_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.1)
    response = llm.invoke(REVIEWER_PROMPT.format(diff=diff))
    return response.content or "(reviewer returned no output)"


def run_security() -> str:
    diff = git_ops.full_diff(tools.get_worktree())
    llm = ChatOllama(model=SECURITY_MODEL, base_url=OLLAMA_BASE_URL, temperature=0.1)
    response = llm.invoke(SECURITY_PROMPT.format(diff=diff))
    return response.content or "(security pass returned no output)"
