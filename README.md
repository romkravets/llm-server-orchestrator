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

## Config (env vars, all optional)

- `HISTORY_REPO_DIR` — default `/home/hermes-agent/projects/history`
- `OLLAMA_BASE_URL` — default `http://127.0.0.1:11434`
- `OLLAMA_MODEL` — default `gpt-oss:20b`
- `MAX_AGENT_STEPS` — default `20` (safety cap on tool-call loops)
