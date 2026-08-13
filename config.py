"""Configuration for the history repo implementation agent."""

import os
from pathlib import Path

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
    "tencent/hy3:free" if IMPLEMENTER_PROVIDER == "hermes" else "gpt-oss:20b",
)
HERMES_PROXY_URL = os.environ.get("HERMES_PROXY_URL", "http://127.0.0.1:8645/v1")

# node/npm live under nvm, not on PATH for non-login subprocess calls.
NODE_BIN_DIR = os.environ.get("NODE_BIN_DIR", "/home/hermes-agent/.nvm/versions/node/v24.18.1/bin")

MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "20"))
