"""Data-minimising categories for coarse operational telemetry."""

from __future__ import annotations

from typing import Any


CLIENT_CATEGORIES = {
    "ChatGPT-Action",
    "Claude-Client",
    "Cursor-IDE",
    "Codex-Client",
    "Grok-Client",
    "Gemini-Client",
    "Python-Agent",
    "CLI-Curl",
    "Web-Browser",
    "Unknown-Agent",
    "Other-Agent",
}
SOURCE_CATEGORIES = {"mcp_call", "api_search", "discovery", "web_view", "other"}
ACTION_CATEGORIES = {
    "server_discover",
    "initialize",
    "tools_list",
    "find_solution",
    "submit_solution",
    "mcp_info",
    "other",
}


def summarize_user_agent(value: Any) -> str:
    """Return only a broad client class; never return the supplied string."""
    if not isinstance(value, str) or not value:
        return "Unknown-Agent"
    if value in CLIENT_CATEGORIES:
        return value
    lowered = value.lower()
    if "chatgpt" in lowered or "openai" in lowered:
        return "ChatGPT-Action"
    if "claude" in lowered:
        return "Claude-Client"
    if "cursor" in lowered:
        return "Cursor-IDE"
    if "codex" in lowered:
        return "Codex-Client"
    if "grok" in lowered:
        return "Grok-Client"
    if "gemini" in lowered or "antigravity" in lowered:
        return "Gemini-Client"
    if "python" in lowered or "httpx" in lowered or "requests" in lowered:
        return "Python-Agent"
    if "curl" in lowered:
        return "CLI-Curl"
    if "mozilla" in lowered or "chrome" in lowered or "safari" in lowered:
        return "Web-Browser"
    return "Other-Agent"


def summarize_source(value: Any) -> str:
    return value if isinstance(value, str) and value in SOURCE_CATEGORIES else "other"


def summarize_action(value: Any) -> str:
    return value if isinstance(value, str) and value in ACTION_CATEGORIES else "other"
