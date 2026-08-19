"""Telegram notifications + a remote approval gate for unattended runs.

Talks to the Telegram Bot HTTP API directly (stdlib only, no new
dependency) rather than shelling out to `hermes send` — that keeps this
working even when the hermes gateway service itself is down (it often is;
see the WhatsApp-pairing failure mode in the ops notes), and means we can
both send *and* poll for the reply, which `hermes send` alone can't do.

Falls back to doing nothing (send) or returning None (request_approval)
whenever TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID aren't set, so cli.py can
fall back to the original terminal y/N prompt — a human always has a way
to approve, never a silent stall.
"""

import json
import time
import urllib.error
import urllib.request

from config import APPROVAL_TIMEOUT_SEC, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def short_id(branch: str) -> str:
    """Short, easy-to-type token for a branch (e.g. agent/1755..789 -> a1b789)
    used both in the Telegram prompt and to match the reply."""
    return branch.rsplit("/", 1)[-1][-6:]


def _call(method: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{_API}/{method}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def send(text: str) -> None:
    """Fire-and-forget notification. Never raises — a failed notify must not
    take down a run that otherwise succeeded."""
    if not configured():
        return
    try:
        _call("sendMessage", {"chat_id": TELEGRAM_CHAT_ID, "text": text[:4000]})
    except Exception as e:
        print(f"[office] telegram send failed (non-fatal): {e!r}")


def request_approval(branch: str, body: str, timeout: int = APPROVAL_TIMEOUT_SEC) -> bool | None:
    """Send an approval request, then poll for a matching y/n reply from
    TELEGRAM_CHAT_ID. Returns True/False, or None if Telegram isn't
    configured or a network error makes polling impossible (caller should
    fall back to the terminal prompt in that case, not treat None as reject).
    """
    if not configured():
        return None

    sid = short_id(branch)
    send(
        f"🛠 history-agent: потрібне ЗАТВЕРДЖЕННЯ [{sid}]\n\n"
        f"{body}\n\n"
        f"Відповідай у цьому чаті: `так {sid}` — змерджити й запушити в main, "
        f"`ні {sid}` — відхилити. Таймаут {timeout // 60} хв (авто-відхилення)."
    )

    try:
        primer = _call("getUpdates", {"timeout": 1, "limit": 1})
        offset = (primer["result"][-1]["update_id"] + 1) if primer.get("result") else None
    except Exception as e:
        print(f"[office] telegram polling unavailable ({e!r}) — falling back to terminal")
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            params = {"timeout": 25, "limit": 10}
            if offset is not None:
                params["offset"] = offset
            resp = _call("getUpdates", params, timeout=35)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[office] telegram poll error (retrying): {e!r}")
            time.sleep(5)
            continue

        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID):
                continue
            text = (msg.get("text") or "").strip()
            if sid not in text:
                continue  # unrelated chatter while this branch is pending — ignore
            low = text.lower()
            if low.startswith(("так", "yes", "y", "approve", "+")):
                send(f"✅ Затверджено: {sid}")
                return True
            if low.startswith(("ні", "no", "n", "reject", "-")):
                send(f"❌ Відхилено: {sid}")
                return False

    send(f"⏱ Таймаут ({timeout // 60} хв) — {sid} відхилено автоматично.")
    return False
