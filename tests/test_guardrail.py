"""Tests for AsqavGuardrailProvider and enable_guardrail. No network, no real crewai."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _install_fake_crewai() -> None:
    """Stub crewai.hooks so the package imports without the real framework."""
    if "crewai.hooks" in sys.modules:
        return
    crewai_pkg = types.ModuleType("crewai")
    hooks_mod = types.ModuleType("crewai.hooks")

    class ToolCallHookContext:
        def __init__(self, tool_name="search", tool_input=None, tool_result=None):
            self.tool_name = tool_name
            self.tool_input = tool_input if tool_input is not None else {}
            self.tool = MagicMock()
            self.agent = None
            self.task = None
            self.crew = None
            self.tool_result = tool_result

    hooks_mod.ToolCallHookContext = ToolCallHookContext
    hooks_mod.register_before_tool_call_hook = MagicMock()
    hooks_mod.register_after_tool_call_hook = MagicMock()
    crewai_pkg.hooks = hooks_mod
    sys.modules["crewai"] = crewai_pkg
    sys.modules["crewai.hooks"] = hooks_mod


_install_fake_crewai()


@pytest.fixture()
def mock_asqav():
    """Mock asqav so no real API calls are made."""
    mock_agent = MagicMock()
    mock_agent.sign.return_value = MagicMock(signature="mock-sig", timestamp=1.0)
    # Remove preflight so tests hit the sign path by default.
    del mock_agent.preflight
    with (
        patch("asqav.client._api_key", "sk_test_key"),
        patch("asqav.client.Agent.create", return_value=mock_agent),
        patch("asqav.client.Agent.get", return_value=mock_agent),
    ):
        yield mock_agent


class TestAsqavGuardrailProviderEvaluate:
    def test_evaluate_allow_when_sign_succeeds(self, mock_asqav: MagicMock):
        from asqav_crewai import AsqavGuardrailProvider, GuardrailRequest

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        req = GuardrailRequest(tool_name="search", tool_input={"q": "hello"})
        decision = provider.evaluate(req)

        assert decision.allow is True
        mock_asqav.sign.assert_called_once()
        action_type, context = mock_asqav.sign.call_args[0][:2]
        assert action_type == "tool:start"
        assert context["tool"] == "search"

    def test_evaluate_deny_when_sign_returns_none(self, mock_asqav: MagicMock):
        from asqav.client import AsqavError

        from asqav_crewai import AsqavGuardrailProvider, GuardrailRequest

        mock_asqav.sign.side_effect = AsqavError("network error")
        provider = AsqavGuardrailProvider(agent_name="test-guard")
        req = GuardrailRequest(tool_name="delete_file", tool_input={})
        decision = provider.evaluate(req)

        assert decision.allow is False
        assert decision.reason  # non-empty
        assert "delete_file" in decision.reason

    def test_evaluate_deny_reason_names_tool(self, mock_asqav: MagicMock):
        # Ensures the deny reason includes the tool name for auditability.
        from asqav.client import AsqavError

        from asqav_crewai import AsqavGuardrailProvider, GuardrailRequest

        mock_asqav.sign.side_effect = AsqavError("refused")
        provider = AsqavGuardrailProvider(agent_name="test-guard")
        req = GuardrailRequest(tool_name="rm_rf", tool_input={})
        decision = provider.evaluate(req)

        assert "rm_rf" in decision.reason

    def test_evaluate_context_includes_agent_role_task_crew(self, mock_asqav: MagicMock):
        from asqav_crewai import AsqavGuardrailProvider, GuardrailRequest

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        req = GuardrailRequest(
            tool_name="web_search",
            tool_input={"q": "test"},
            agent_role="researcher",
            task_description="gather data",
            crew_id="crew-42",
        )
        provider.evaluate(req)

        _, context = mock_asqav.sign.call_args[0][:2]
        assert context["agent_role"] == "researcher"
        assert context["task"] == "gather data"
        assert context["crew"] == "crew-42"

    def test_evaluate_truncates_input(self, mock_asqav: MagicMock):
        # Input longer than 200 chars must be truncated in the signed context.
        from asqav_crewai import AsqavGuardrailProvider, GuardrailRequest

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        long_input = {"data": "x" * 300}
        req = GuardrailRequest(tool_name="tool", tool_input=long_input)
        provider.evaluate(req)

        _, context = mock_asqav.sign.call_args[0][:2]
        assert len(context["input"]) <= 200


class TestEnableGuardrailHookFromContext:
    def test_timestamp_populated_in_request(self, mock_asqav: MagicMock):
        from crewai.hooks import ToolCallHookContext, register_before_tool_call_hook

        from asqav_crewai import AsqavGuardrailProvider, enable_guardrail

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        captured = []
        original_evaluate = provider.evaluate

        def capturing_evaluate(req):
            captured.append(req)
            return original_evaluate(req)

        provider.evaluate = capturing_evaluate

        register_before_tool_call_hook.reset_mock()
        enable_guardrail(provider)
        hook = register_before_tool_call_hook.call_args[0][0]

        ctx = ToolCallHookContext(tool_name="search", tool_input={})
        hook(ctx)

        assert captured, "evaluate was never called"
        assert captured[0].timestamp != "", "timestamp must be populated"

    def test_agent_role_task_crew_extracted_from_ctx(self, mock_asqav: MagicMock):
        from crewai.hooks import ToolCallHookContext, register_before_tool_call_hook

        from asqav_crewai import AsqavGuardrailProvider, enable_guardrail

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        captured = []
        original_evaluate = provider.evaluate

        def capturing_evaluate(req):
            captured.append(req)
            return original_evaluate(req)

        provider.evaluate = capturing_evaluate

        register_before_tool_call_hook.reset_mock()
        enable_guardrail(provider)
        hook = register_before_tool_call_hook.call_args[0][0]

        ctx = ToolCallHookContext(tool_name="search", tool_input={})
        agent = MagicMock()
        agent.role = "analyst"
        task = MagicMock()
        task.description = "analyse data"
        crew = MagicMock()
        crew.id = "crew-7"
        ctx.agent = agent
        ctx.task = task
        ctx.crew = crew
        hook(ctx)

        assert captured[0].agent_role == "analyst"
        assert captured[0].task_description == "analyse data"
        assert captured[0].crew_id == "crew-7"


class TestEnableGuardrailDecisions:
    def _register_and_get_hook(self, provider, **kwargs):
        from crewai.hooks import register_before_tool_call_hook

        register_before_tool_call_hook.reset_mock()
        from asqav_crewai import enable_guardrail

        enable_guardrail(provider, **kwargs)
        return register_before_tool_call_hook.call_args[0][0]

    def test_allow_true_returns_none(self, mock_asqav: MagicMock):
        from crewai.hooks import ToolCallHookContext

        from asqav_crewai import AsqavGuardrailProvider

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        hook = self._register_and_get_hook(provider, fail_closed=True)
        ctx = ToolCallHookContext(tool_name="safe_tool", tool_input={})

        assert hook(ctx) is None

    def test_allow_false_returns_false(self, mock_asqav: MagicMock):
        from crewai.hooks import ToolCallHookContext

        from asqav_crewai import GuardrailDecision

        provider = MagicMock()
        provider.evaluate.return_value = GuardrailDecision(allow=False, reason="denied")
        hook = self._register_and_get_hook(provider, fail_closed=True)
        ctx = ToolCallHookContext(tool_name="blocked_tool", tool_input={})

        assert hook(ctx) is False

    def test_fail_closed_true_blocks_on_exception(self, mock_asqav: MagicMock):
        from crewai.hooks import ToolCallHookContext

        provider = MagicMock()
        provider.evaluate.side_effect = RuntimeError("boom")
        hook = self._register_and_get_hook(provider, fail_closed=True)
        ctx = ToolCallHookContext(tool_name="risky_tool", tool_input={})

        assert hook(ctx) is False

    def test_fail_closed_false_allows_on_exception(self, mock_asqav: MagicMock):
        from crewai.hooks import ToolCallHookContext

        provider = MagicMock()
        provider.evaluate.side_effect = RuntimeError("boom")
        hook = self._register_and_get_hook(provider, fail_closed=False)
        ctx = ToolCallHookContext(tool_name="risky_tool", tool_input={})

        assert hook(ctx) is None


class TestHealthCheck:
    def test_health_check_true_with_live_agent(self, mock_asqav: MagicMock):
        from asqav_crewai import AsqavGuardrailProvider

        # mock_asqav.agent_id is a MagicMock (truthy) -> health_check returns True
        provider = AsqavGuardrailProvider(agent_name="test-guard")
        assert provider.health_check() is True

    def test_health_check_false_on_broken_agent(self, mock_asqav: MagicMock):
        from asqav_crewai import AsqavGuardrailProvider

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        # Simulate a broken agent by setting _agent to None
        provider._agent = None
        assert provider.health_check() is False

    def test_health_check_never_raises(self, mock_asqav: MagicMock):
        from asqav_crewai import AsqavGuardrailProvider

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        # Make agent_id raise to verify health_check absorbs exceptions
        mock_asqav.agent_id = property(lambda self: (_ for _ in ()).throw(RuntimeError("oops")))
        # Reset _agent to the mock directly to use the property
        provider._agent = mock_asqav
        # health_check must not raise regardless
        result = provider.health_check()
        assert isinstance(result, bool)


class TestProtocolStructure:
    def test_isinstance_guardrail_provider(self, mock_asqav: MagicMock):
        from asqav_crewai import AsqavGuardrailProvider, GuardrailProvider

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        assert isinstance(provider, GuardrailProvider)

    def test_name_attribute(self, mock_asqav: MagicMock):
        from asqav_crewai import AsqavGuardrailProvider

        provider = AsqavGuardrailProvider(agent_name="test-guard")
        assert isinstance(provider.name, str)
        assert provider.name == "asqav"
