"""Pre-tool-call authorization provider for CrewAI (crewAI issue #4877).

Layered on BeforeToolCallHook; use AsqavGuardrailProvider with enable_guardrail.
AsqavHooks is unchanged and remains fail-open by default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from asqav.extras._base import AsqavAdapter

try:
    from crewai.hooks import (
        ToolCallHookContext,
        register_before_tool_call_hook,
    )
except ImportError as err:
    raise ImportError(
        "asqav-crewai requires crewai. Install with: pip install 'crewai>=1.9.1'"
    ) from err

logger = logging.getLogger("asqav")

_MAX_LEN = 200


@dataclass
class GuardrailRequest:
    """Authorization request built from a ToolCallHookContext before a tool runs."""

    tool_name: str
    tool_input: dict
    agent_role: str | None = None
    task_description: str | None = None
    crew_id: str | None = None
    timestamp: str = ""


@dataclass
class GuardrailDecision:
    """Authorization decision returned by a GuardrailProvider."""

    allow: bool
    reason: str | None = None
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class GuardrailProvider(Protocol):
    """Protocol for pre-tool-call authorization providers (crewAI #4877)."""

    name: str

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """Evaluate a tool call request; return allow/deny decision."""
        ...

    def health_check(self) -> bool:
        """Return True if the provider is ready, False otherwise. Never raises."""
        ...


class AsqavGuardrailProvider(AsqavAdapter):
    """Pre-tool-call authorization via Asqav cryptographic signing.

    A refused or failed signature maps to allow=False (deny). Pair with
    enable_guardrail(fail_closed=True) to block on provider errors; this is
    the recommended posture and differs from AsqavHooks.fail_closed=False.

    Args:
        api_key: Optional API key override (uses asqav.init() default).
        agent_name: Name for an Asqav agent (calls Agent.create).
        agent_id: ID of an existing Asqav agent (calls Agent.get).
    """

    name = "asqav"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        agent_name: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        super().__init__(api_key=api_key, agent_name=agent_name, agent_id=agent_id)

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        """Sign the tool call; return allow=True on success, allow=False on refusal."""
        context = {
            "tool": request.tool_name,
            "input": str(request.tool_input)[:_MAX_LEN],
            "agent_role": request.agent_role,
            "task": request.task_description,
            "crew": request.crew_id,
        }
        # Use preflight if the agent exposes it; otherwise sign is the deny signal.
        preflight = getattr(self._agent, "preflight", None)
        if preflight is not None:
            try:
                pf_result = preflight("tool:start", context)
                if pf_result is not None and not pf_result:
                    return GuardrailDecision(
                        allow=False,
                        reason=f"asqav preflight denied tool '{request.tool_name}'",
                        metadata={"tool_name": request.tool_name},
                    )
            except Exception as exc:
                logger.warning("asqav preflight check failed: %s", exc)

        sig = self._sign_action("tool:start", context)
        if sig is None:
            return GuardrailDecision(
                allow=False,
                reason=f"asqav refused to sign tool '{request.tool_name}' (not authorized)",
                metadata={"tool_name": request.tool_name},
            )
        return GuardrailDecision(allow=True)

    def health_check(self) -> bool:
        """Return True when the asqav agent is initialized and has a valid id."""
        try:
            return self._agent is not None and getattr(self._agent, "agent_id", None) is not None
        except Exception:
            return False


def enable_guardrail(provider: GuardrailProvider, *, fail_closed: bool = True) -> None:
    """Register a before_tool_call hook that enforces the provider's decisions.

    fail_closed=True (default): block the tool on provider errors (return False).
    fail_closed=False: allow the tool on provider errors (return None).
    The default differs from AsqavHooks (fail_closed=False) for backward compat;
    the guardrail posture is deny-by-default on ambiguity per the #4877 proposal.

    Args:
        provider: A GuardrailProvider to evaluate each tool call.
        fail_closed: When True, block on evaluation errors (safe default).
    """

    def _hook(ctx: ToolCallHookContext) -> bool | None:
        agent = getattr(ctx, "agent", None)
        task = getattr(ctx, "task", None)
        crew = getattr(ctx, "crew", None)
        request = GuardrailRequest(
            tool_name=ctx.tool_name,
            tool_input=ctx.tool_input if ctx.tool_input else {},
            agent_role=getattr(agent, "role", None),
            task_description=getattr(task, "description", None),
            crew_id=getattr(crew, "id", None),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        try:
            decision = provider.evaluate(request)
        except Exception as exc:
            logger.warning("guardrail evaluation failed: %s", exc)
            return False if fail_closed else None
        if not decision.allow:
            logger.warning(
                "guardrail blocked tool %s: %s",
                request.tool_name,
                decision.reason,
            )
            return False
        return None

    register_before_tool_call_hook(_hook)
