"""CrewAI tool-call hooks that sign tool:start, tool:end, and tool:error
events via the Asqav API. Signing is fail-open by default; an optional
fail-closed mode blocks the tool when a tool:start signature is refused.
See README for usage."""

from __future__ import annotations

import logging

from asqav.extras._base import AsqavAdapter

try:
    from crewai.hooks import (
        ToolCallHookContext,
        register_after_tool_call_hook,
        register_before_tool_call_hook,
    )
except ImportError as err:
    raise ImportError(
        "asqav-crewai requires crewai. Install with: pip install 'crewai>=1.9.1'"
    ) from err

logger = logging.getLogger("asqav")

_MAX_LEN = 200


class AsqavHooks(AsqavAdapter):
    """Sign CrewAI tool call events (tool:start, tool:end) via the Asqav API.

    Fail-open by default: signing errors are logged, not raised, so the agent
    pipeline never breaks because of governance. Pass ``fail_closed=True`` to
    block a tool when its tool:start signature is refused (a rogue agent is
    stopped before it acts, and the attempt is still recorded).

    Args:
        api_key: Optional API key override (uses ``asqav.init()`` default).
        agent_name: Name for an Asqav agent (calls ``Agent.create``).
        agent_id: ID of an existing Asqav agent (calls ``Agent.get``).
        fail_closed: When True, block a tool if its tool:start sign is refused.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        agent_name: str | None = None,
        agent_id: str | None = None,
        fail_closed: bool = False,
    ) -> None:
        super().__init__(api_key=api_key, agent_name=agent_name, agent_id=agent_id)
        self._fail_closed = fail_closed

    def _before_tool(self, ctx: ToolCallHookContext) -> bool | None:
        """Sign tool:start; return False to block when fail_closed and sign refused."""
        input_preview = str(ctx.tool_input)[:_MAX_LEN] if ctx.tool_input else ""
        try:
            sig = self._sign_action(
                "tool:start",
                {
                    "tool": ctx.tool_name,
                    "input": input_preview,
                },
            )
        except Exception as exc:
            logger.warning("asqav tool:start signing failed (fail-open): %s", exc)
            sig = None
        # fail-closed: a refused signature means the action is not authorized to run
        if self._fail_closed and sig is None:
            logger.warning("asqav blocked tool %s (fail-closed, sign refused)", ctx.tool_name)
            return False
        return None

    def _after_tool(self, ctx: ToolCallHookContext) -> str | None:
        """Sign tool:end with output metadata; never alters the result."""
        result = ctx.tool_result
        try:
            self._sign_action(
                "tool:end",
                {
                    "tool": ctx.tool_name,
                    "output_type": type(result).__name__,
                    "output_length": len(str(result)) if result is not None else 0,
                },
            )
        except Exception as exc:
            logger.warning("asqav tool:end signing failed (fail-open): %s", exc)
        return None

    def register(self) -> None:
        """Register the Asqav before/after tool-call hooks globally with CrewAI.

        Hooks apply to every tool call across all agents and crews in-process.
        """
        register_before_tool_call_hook(self._before_tool)
        register_after_tool_call_hook(self._after_tool)
