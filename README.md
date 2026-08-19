# llm-server-orchestrator

A self-hosted, multi-agent coding pipeline: an implementer agent that
explores your repo and makes real changes, a reviewer and a security
checker (each a **different** local model, so nothing reviews its own
work), and a human approval gate before anything gets merged or pushed.
Runs entirely on your own hardware against your own [Ollama](https://ollama.com)
models — no API keys, no per-token cost, no code leaving your network
unless you opt into a cloud model.

Built with [LangGraph](https://github.com/langchain-ai/langgraph). One
`uv run` command in, one `y/N` approval out.

## Why this exists

Most "AI coding agent" setups either run on someone else's cloud, or
they're a single model that writes code, marks its own homework, and
expects you to trust it. This project is a small, readable reference for
doing better on hardware you already own:

- **Real tool-calling loop, not single-shot generation.** The implementer
  explores (`list_files`, `read_file`) before it writes, runs your
  project's own `check`/`build` commands, and self-corrects on failure —
  instead of guessing once and hoping.
- **Separation of duties.** Implementer, reviewer, and security checker
  are three different models. A model that wrote a bug is not the model
  vouching that there isn't one.
- **Isolation by default.** Every run happens in its own `git worktree`
  on a throwaway branch. Your working tree is never touched until you
  explicitly approve.
- **A human is always the last gate.** The pipeline stops and shows you
  the real `git diff` — not the model's self-report, which is shown too,
  but never trusted alone — before anything is committed anywhere.
- **Free by default.** The reference config runs entirely on local Ollama
  models. Point `IMPLEMENTER_PROVIDER` at a cloud model if you want to
  trade cost/privacy for more capability on harder tasks.

## Architecture

```
                    ┌──────────────┐
   your task  ───▶  │  Implementer │  qwen2.5-coder:14b (local, tool-calling)
                    │  list_files / read_file / write_file / delete_file
                    │  run_check / run_build
                    └──────┬───────┘
                           │ "finish" only accepted after
                           │ a real write_file/delete_file call —
                           │ otherwise looped back via `nudge`
                           ▼
                    ┌──────────────┐
                    │   Reviewer   │  deepseek-r1:14b (local)
                    │  critiques the diff: bugs, regressions, schema issues
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │   Security   │  qwen2.5-coder:7b (local)
                    │  scans for security-relevant issues only
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │     You      │  sees Implementer + Reviewer + Security
                    │              │  reports AND the real `git diff`,
                    │              │  approves or rejects in the terminal
                    └──────┬───────┘
                    y ─────┴───── anything else
                    ▼                  ▼
        commit → merge → push    worktree + branch
        → worktree removed          discarded
```

Every stage runs against an isolated `.agent-worktrees/<id>` git worktree
on its own branch (`agent/<id>`) — `main` is untouched until you approve.

## Quick start

```bash
git clone https://github.com/romkravets/llm-server-orchestrator.git
cd llm-server-orchestrator
uv sync

export HISTORY_REPO_DIR=/path/to/your/repo   # any git repo with npm check/build scripts
uv run python cli.py "Add a new photo story for Kremenets"
```

The agent explores the repo, makes the change on an isolated worktree,
runs your project's validation, then stops and prints a review block:

```
Схвалити? [y/N]:
```

- `y` — commits, merges into your default branch, pushes to `origin`,
  removes the worktree.
- anything else — discards the worktree and branch. Nothing is kept.

> The tool names, prompts, and terminal messages are currently in a mix
> of English and Ukrainian (the repo this was built for) — functionally
> everything works the same regardless of your own repo's language.

## Configuration

All env vars, all optional:

| Variable | Default | Meaning |
|---|---|---|
| `HISTORY_REPO_DIR` | `/home/hermes-agent/projects/history` | Path to the target git repo |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama server |
| `REVIEWER_MODEL` | `deepseek-r1:14b` | Model for the review pass |
| `SECURITY_MODEL` | `qwen2.5-coder:7b` | Model for the security pass |
| `MAX_AGENT_STEPS` | `20` | Safety cap on the implementer's tool-call loop |
| `IMPLEMENTER_PROVIDER` | `ollama` | `ollama` or `hermes` (see warning below) |
| `IMPLEMENTER_MODEL` | `qwen2.5-coder:14b` (ollama) / `tencent/hy3:free` (hermes) | Implementer model — needs tool-calling support. `gpt-oss:20b` was the original default but doesn't fully fit this server's 12GB 3080 Ti — see note below. |
| `AUTO_APPROVE_SAFE` | `1` | Land safe changes with no human at all — see gate section below |
| `SAFE_PATH_PREFIXES` | `src/content/photos/,public/photos/` | Comma-separated paths eligible for no-human auto-land |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | *(unset)* | Approve/reject risky runs from Telegram instead of the terminal |
| `APPROVAL_TIMEOUT_SEC` | `1800` | How long to wait for a Telegram reply before auto-rejecting |

Reviewer and security stay on local Ollama regardless of
`IMPLEMENTER_PROVIDER` — they're cheap, fast, single-shot critiques; no
reason to spend a cloud call on them.

## Approval gate — unattended by default, Telegram for anything risky

The `y/N` prompt above is only one of three gates now, tried in this order:

1. **Auto-land, no human.** Only when the reviewer didn't come back
   `BLOCKING`, no `revise` round happened, the security pass came back
   short/clean, and every changed file is under `SAFE_PATH_PREFIXES`
   (default: `src/content/photos/`, `public/photos/`). Commits, merges,
   pushes, and cleans up the worktree immediately.
2. **Telegram**, if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are set (put
   them in `.env`, see `.env.example`). Sends the summary + reviewer +
   security + real diff to your chat and polls for a reply. Reply
   `так <id>` / `ні <id>` (the `[id]` shown in the message) — anything
   else is ignored so stray chat messages can't misfire an approval.
   Auto-rejects after `APPROVAL_TIMEOUT_SEC` (default 30 min) if you never
   answer.
3. **Terminal `y/N`**, as before — used whenever Telegram isn't
   configured, or a network error makes polling impossible.

Turn off the no-human path entirely with `AUTO_APPROVE_SAFE=0` (every run
then needs Telegram or the terminal, regardless of how small the change).
The implementer never gets closer to `main` than a disposable worktree
either way — worst case of a wrong auto-approval is a bad commit on `main`
that's still a normal `git revert` away, never a leaked secret or an
untracked change to `SAFE_PATH_PREFIXES` itself (that file lives outside
any path the agent is allowed to touch unattended).

### Setting up the Telegram bot

```
1. Telegram -> @BotFather -> /newbot -> copy the token it gives you.
2. Message your new bot anything (so Telegram knows your chat).
3. curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
   -> copy the message.chat.id you sent in step 2.
4. cp .env.example .env, fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
```

This talks to the Telegram Bot HTTP API directly (`notify.py`, stdlib
only) — it does not depend on the `hermes` gateway service running.

## Known limitation: `IMPLEMENTER_PROVIDER=hermes` is currently broken

Routes the implementer through [Hermes](https://github.com/NousResearch/hermes-agent)'s
local OpenAI-compatible proxy (`hermes proxy start --provider nous`)
instead of local Ollama, to try a stronger cloud model on tasks the local
model struggles with (open-ended review/CSS-layout fixes tend to make
`gpt-oss:20b` loop without ever committing to a change).

The proxy itself works — a direct `ChatOpenAI(...).invoke(messages)` call
with the exact same system prompt, tools, and task returns correctly in
~4 seconds. But routed through `graph.invoke()` (the actual `cli.py`
path), the identical call reliably times out (`openai.APITimeoutError`),
100% reproducible, even with a 90s client timeout and 3 retries. Root
cause not yet found — suspected interaction between how LangGraph
executes node functions and this httpx-based client. Not proxy flakiness.

Leave `IMPLEMENTER_PROVIDER` unset until this is root-caused. Local Ollama
works reliably end-to-end; it just sometimes needs a few `nudge` rounds
to commit to writing a file on ambiguous or highly visual tasks.

## Design notes worth knowing before you extend this

- **`finish` is not trusted blindly.** The implementer's own "I'm done"
  summary is shown, but the review screen always also shows the real
  `git diff` of the worktree — if the model's self-report says it did
  something but the diff is empty, that's shown as a loud warning, not
  silently accepted.
- **`nudge` requires a real mutation, not just tool use.** Early versions
  accepted "the model called *some* tool" as evidence of progress; that
  let it explore forever and then answer in prose without ever writing
  anything. It now specifically requires a `write_file` or `delete_file`
  call before `finish` is accepted.
- **Reviewer/security are single-shot, not agentic.** They read the diff
  once and critique it — no tool-calling loop, no chance to "argue" with
  the implementer. Keeps them fast and makes their job strictly narrower
  than the implementer's.

## License

MIT — see [LICENSE](LICENSE).
