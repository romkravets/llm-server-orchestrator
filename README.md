# history-agent

LangGraph implementation agent for the `history` repo. Same idea as
`llm-orchestrator execute-task` + `land-task`, but as a real tool-calling
agent loop (explores, writes, validates, self-corrects) instead of a
single-shot generation, with a built-in terminal approval gate instead of
an external UI.

Runs against the server's local Ollama (`gpt-oss:20b` by default — it
explicitly supports tool calling), so it's free and uses the server's own
GPU.

## Setup (on the server, once)

```bash
cd /home/hermes-agent/projects/history-agent
uv sync
```

## Run

```bash
uv run python cli.py "Add a new photo story for Kremenets"
```

The agent explores the repo, writes files into an isolated git worktree
(`.agent-worktrees/<id>`, gitignored), runs `npm run check`/`build`, then
stops and prints a summary for you to approve:

```
Схвалити? [y/N]:
```

- `y` — commits, merges into `main`, pushes to GitHub, removes the worktree.
- anything else — discards the worktree and branch, nothing is kept.

The implementer's work goes through a small dev cycle before you ever see
it: **worker** (writes the change) → **reviewer** (`deepseek-r1:14b`,
critiques the diff) → **security** (`qwen2.5-coder:7b`, scans for
security-relevant issues) → you. Each role is a different model so none of
them reviews its own work. If the model never actually calls `write_file`
(just talks instead of acting), a `nudge` step pushes it back to do real
work instead of silently accepting an empty "finish" — this is loud in the
terminal and shown as a warning if the real diff still ends up empty.

## Config (env vars, all optional)

- `HISTORY_REPO_DIR` — default `/home/hermes-agent/projects/history`
- `OLLAMA_BASE_URL` — default `http://127.0.0.1:11434`
- `REVIEWER_MODEL` — default `deepseek-r1:14b`
- `SECURITY_MODEL` — default `qwen2.5-coder:7b`
- `MAX_AGENT_STEPS` — default `20` (safety cap on tool-call loops)
- `IMPLEMENTER_PROVIDER` — `ollama` (default) or `hermes`
- `IMPLEMENTER_MODEL` — default `gpt-oss:20b` (ollama) or `tencent/hy3:free` (hermes)

### ⚠️ `IMPLEMENTER_PROVIDER=hermes` is currently broken — do not use

Routes the implementer through `hermes proxy start --provider nous`
(OpenAI-compatible endpoint) instead of local Ollama, to try a stronger
cloud model on tasks the local model struggles with (e.g. CSS/layout
fixes). The idea is sound and the proxy itself works — a direct
`ChatOpenAI(...).invoke(messages)` call with the exact same system prompt,
tools, and task returns correctly in ~4 seconds.

**But run through `graph.invoke()` (i.e. the real `cli.py` path), the same
call reliably times out** (`openai.APITimeoutError`), even with
`timeout=90` and `max_retries=3` on the client. Root cause not found yet —
most likely something about how LangGraph executes node functions (thread
pool? contextvars?) interacts badly with this httpx-based client; it is
not proxy flakiness (retries don't help, and it's 100% reproducible, not
intermittent). `gpt-oss:20b` via `ChatOllama` does not have this problem.

Until this is root-caused, leave `IMPLEMENTER_PROVIDER` unset (defaults to
`ollama`) — it works reliably end-to-end, just sometimes needs a few
`nudge` rounds to commit to writing a file for ambiguous/visual tasks.
