"""Configuration for the history repo implementation agent."""

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Minimal .env loader (stdlib only) — real env vars always win. Lets
    secrets like TELEGRAM_BOT_TOKEN live in a gitignored .env next to this
    file instead of being exported by hand every session."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

REPO_DIR = Path(os.environ.get("HISTORY_REPO_DIR", "/home/hermes-agent/projects/history"))
WORKTREES_DIR = REPO_DIR / ".agent-worktrees"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

# Reviewer/security always stay on local Ollama — cheap, fast, free single
# critique passes, no reason to spend cloud calls on them.
REVIEWER_MODEL = os.environ.get("REVIEWER_MODEL", "deepseek-r1:14b")
SECURITY_MODEL = os.environ.get("SECURITY_MODEL", "qwen2.5-coder:7b")

# Implementer backend: "ollama" (default — free, local GPU, good for
# content-generation tasks) or "hermes" (cloud via `hermes proxy`, stronger
# reasoning — better for trickier tasks like CSS/layout fixes where the
# local model tends to get stuck exploring and never commits to a change).
# Start the proxy once per server boot: hermes proxy start --provider nous
IMPLEMENTER_PROVIDER = os.environ.get("IMPLEMENTER_PROVIDER", "ollama")
IMPLEMENTER_MODEL = os.environ.get(
    "IMPLEMENTER_MODEL",
    # Verified live on this server's Ollama 0.32.14 with a direct
    # bind_tools() smoke test before picking this:
    #  - qwen2.5-coder (7b AND 14b): never emits real tool_calls — writes
    #    the call as plain-text JSON in `content` instead, so the worker
    #    loop never sees a write_file call and nudges forever.
    #  - qwen3.8:27b (a non-standard local tag, likely a custom build):
    #    tool_calls parse fine standalone, but the graph's longer message
    #    history trips its chat template — Ollama 500s with "no user query
    #    found in messages" partway through a real run.
    #  - gpt-oss:20b: not pulled, and wouldn't fully fit this server's
    #    12GB 3080 Ti anyway.
    # hermes3:8b (NousResearch, purpose-built for reliable function
    # calling) passed the same smoke test cleanly — smaller too (~4.7GB),
    # leaving VRAM headroom for reviewer/security.
    "tencent/hy3:free" if IMPLEMENTER_PROVIDER == "hermes" else "hermes3:8b",
)
HERMES_PROXY_URL = os.environ.get("HERMES_PROXY_URL", "http://127.0.0.1:8645/v1")

# node/npm live under nvm, not on PATH for non-login subprocess calls.
NODE_BIN_DIR = os.environ.get("NODE_BIN_DIR", "/home/hermes-agent/.nvm/versions/node/v24.18.1/bin")

MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "20"))

# --- Approval gate ------------------------------------------------------
# Landing (commit+merge+push to main) is auto-approved with no human in the
# loop ONLY when: the review pass didn't come back BLOCKING, no revise round
# was needed, the security pass came back short/clean, and every changed
# file falls under SAFE_PATH_PREFIXES. Anything else needs a human — via
# Telegram if configured (see notify.py), else the terminal y/N prompt.
AUTO_APPROVE_SAFE = os.environ.get("AUTO_APPROVE_SAFE", "1") == "1"
SAFE_PATH_PREFIXES = tuple(
    p.strip()
    for p in os.environ.get(
        "SAFE_PATH_PREFIXES", "src/content/photos/,public/photos/"
    ).split(",")
    if p.strip()
)

# --- Telegram approval gate ---------------------------------------------
# Create a bot via @BotFather, put its token + your personal chat id here
# (in .env, not exported by hand). Leave blank to keep the terminal y/N
# prompt as the only gate.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
APPROVAL_TIMEOUT_SEC = int(os.environ.get("APPROVAL_TIMEOUT_SEC", "1800"))  # 30 min
