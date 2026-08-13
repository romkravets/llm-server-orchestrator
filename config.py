"""Configuration for the history repo implementation agent."""

import os
from pathlib import Path

REPO_DIR = Path(os.environ.get("HISTORY_REPO_DIR", "/home/hermes-agent/projects/history"))
WORKTREES_DIR = REPO_DIR / ".agent-worktrees"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b")

# node/npm live under nvm, not on PATH for non-login subprocess calls.
NODE_BIN_DIR = os.environ.get("NODE_BIN_DIR", "/home/hermes-agent/.nvm/versions/node/v24.18.1/bin")

MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "20"))
