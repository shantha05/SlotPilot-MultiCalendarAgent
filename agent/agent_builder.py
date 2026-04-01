"""Factory for building the SlotPilot ChatCompletionAgent.

Builds a fresh agent each turn so that CalendarPlugin always holds
current tokens from the Streamlit session.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

from agent.calendar_plugin import CalendarPlugin
from agent.prompts import get_system_prompt
from observability.logger import get_logger

log = get_logger(__name__)


def build_agent(
    get_token_fn: Callable[[str], Optional[str]],
    accounts_map: dict,
    session_id: str = "",
    user_timezone: str = "UTC",
) -> ChatCompletionAgent:
    """Create a ChatCompletionAgent with the CalendarPlugin attached.

    Args:
        get_token_fn:  Callable(account_label) -> access_token str | None.
        accounts_map:  Dict of {label: {account: msal_account, email: str}}.
        session_id:    Streamlit session UUID passed through to audit records.
        user_timezone: IANA timezone name for the user (e.g. 'America/New_York').

    Returns:
        A ready-to-use ChatCompletionAgent.  Auto function calling is enabled
        by default (FunctionChoiceBehavior.Auto()).
    """
    service = AzureChatCompletion(
        deployment_name=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )

    plugin = CalendarPlugin(
        get_token_fn=get_token_fn,
        accounts_map=accounts_map,
        session_id=session_id,
    )

    agent = ChatCompletionAgent(
        service=service,
        name="SlotPilot",
        instructions=get_system_prompt(user_timezone),
        plugins=[plugin],
    )

    log.debug(
        "ChatCompletionAgent built",
        extra={"accounts": list(accounts_map.keys())},
    )
    return agent


def extract_token_usage(response_message) -> dict[str, int]:
    """Extract prompt/completion/total token counts from an SK response message.

    Semantic Kernel surfaces usage in ChatMessageContent.metadata["usage"].
    The object stores counts as attributes; we handle missing attributes
    gracefully in case a future SK version changes the structure.

    Returns:
        Dict with keys: prompt_tokens, completion_tokens, total_tokens (all int).
    """
    usage = {}
    try:
        meta = getattr(response_message, "metadata", {}) or {}
        u = meta.get("usage")
        if u is not None:
            usage = {
                "prompt_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(u, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(u, "total_tokens", 0) or 0),
            }
    except Exception as exc:
        log.debug("Token usage extraction failed", extra={"error": str(exc)})

    # Normalise missing keys to 0
    usage.setdefault("prompt_tokens", 0)
    usage.setdefault("completion_tokens", 0)
    usage.setdefault("total_tokens", 0)

    log.info(
        "[TOKEN_USAGE] prompt=%d completion=%d total=%d",
        usage["prompt_tokens"],
        usage["completion_tokens"],
        usage["total_tokens"],
    )
    return usage
