"""Tests for asqav-crewai hook integration. No network, no real crewai."""

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
    with (
        patch("asqav.client._api_key", "sk_test_key"),
        patch("asqav.client.Agent.create", return_value=mock_agent),
        patch("asqav.client.Agent.get", return_value=mock_agent),
    ):
        yield mock_agent


class TestAsqavHooks:
    def test_before_tool_signs_start(self, mock_asqav: MagicMock):
        from crewai.hooks import ToolCallHookContext

        from asqav_crewai import AsqavHooks

        hooks = AsqavHooks(agent_name="test-crew")
        ctx = ToolCallHookContext(tool_name="search", tool_input={"q": "hi"})
        result = hooks._before_tool(ctx)

        assert result is None  # fail-open allows execution
        mock_asqav.sign.assert_called_once()
        action_type, context = mock_asqav.sign.call_args[0][:2]
        assert action_type == "tool:start"
        assert context["tool"] == "search"

    def test_after_tool_signs_end(self, mock_asqav: MagicMock):
        from crewai.hooks import ToolCallHookContext

        from asqav_crewai import AsqavHooks

        hooks = AsqavHooks(agent_name="test-crew")
        ctx = ToolCallHookContext(tool_name="search", tool_result="some output")
        result = hooks._after_tool(ctx)

        assert result is None
        assert mock_asqav.sign.call_args[0][0] == "tool:end"

    def test_register_wires_both_hooks(self, mock_asqav: MagicMock):
        from crewai import hooks as crewai_hooks

        from asqav_crewai import AsqavHooks

        crewai_hooks.register_before_tool_call_hook.reset_mock()
        crewai_hooks.register_after_tool_call_hook.reset_mock()

        AsqavHooks(agent_name="test-crew").register()

        crewai_hooks.register_before_tool_call_hook.assert_called_once()
        crewai_hooks.register_after_tool_call_hook.assert_called_once()

    def test_fail_closed_blocks_when_sign_refused(self, mock_asqav: MagicMock):
        from asqav.client import AsqavError
        from crewai.hooks import ToolCallHookContext

        from asqav_crewai import AsqavHooks

        hooks = AsqavHooks(agent_name="test-crew", fail_closed=True)
        mock_asqav.sign.side_effect = AsqavError("network error")
        ctx = ToolCallHookContext(tool_name="delete_file", tool_input={})

        # refused sign -> _sign_action returns None -> hook returns False (block)
        assert hooks._before_tool(ctx) is False

    def test_fail_open_allows_when_sign_refused(self, mock_asqav: MagicMock):
        from asqav.client import AsqavError
        from crewai.hooks import ToolCallHookContext

        from asqav_crewai import AsqavHooks

        hooks = AsqavHooks(agent_name="test-crew")
        mock_asqav.sign.side_effect = AsqavError("network error")
        ctx = ToolCallHookContext(tool_name="delete_file", tool_input={})

        assert hooks._before_tool(ctx) is None  # fail-open never blocks
