"""Exercise real CrewAI dispatch in a process isolated from the stub unit tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("case", ["success", "refused_open", "refused_closed", "end_failed"])
def test_readme_with_real_crewai(native, case, tmp_path):
    env = dict(os.environ, CREWAI_STORAGE_DIR=str(tmp_path))
    result = subprocess.run(
        [sys.executable, __file__, str(native), case],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS real CrewAI" in result.stdout


def run_probe(native: bool, case: str) -> None:
    """Keep the framework, adapter, and SDK real; replace model and HTTP only."""
    import functools
    import hashlib
    import json
    import re
    import socket
    from importlib.metadata import version
    from unittest.mock import patch

    os.environ.update(
        ASQAV_API_KEY="sk_test_no_network",
        CREWAI_MODEL="test/local",
        CREWAI_DISABLE_TELEMETRY="true",
        CREWAI_TRACING_ENABLED="false",
        OTEL_SDK_DISABLED="true",
    )

    import crewai
    import crewai.tools
    import httpx
    from asqav.canonicalize import canonicalize_action
    from crewai.hooks import clear_all_tool_call_hooks
    from crewai.llms.base_llm import BaseLLM

    from asqav_crewai import AsqavHooks

    assert Path(crewai.__file__).is_file(), "CrewAI must be an installed framework"
    clear_all_tool_call_hooks()
    state = {"tools": 0, "requests": [], "model_calls": 0}
    blocked = case == "refused_closed"

    class LocalLLM(BaseLLM):
        def __init__(self):
            super().__init__(model="test/local")

        def supports_function_calling(self):
            return native

        def call(self, messages, **kwargs):
            state["model_calls"] += 1
            assert state["model_calls"] <= 2, "Unexpected model retry"
            if state["model_calls"] == 1:
                if native:
                    return [
                        {
                            "id": "call_echo",
                            "type": "function",
                            "function": {
                                "name": "echo_tool",
                                "arguments": '{"text": "hello world"}',
                            },
                        }
                    ]
                return (
                    "Thought: I will call the echo tool.\nAction: echo_tool\n"
                    'Action Input: {"text": "hello world"}'
                )
            expected = "Tool execution blocked by hook" if blocked else "echoed hello world"
            assert expected in str(messages), messages
            return "Final Answer: checked"

    actual_tool = crewai.tools.tool

    def counted_tool(*args, **kwargs):
        def decorate(function):
            @functools.wraps(function)
            def counted(*call_args, **call_kwargs):
                state["tools"] += 1
                return function(*call_args, **call_kwargs)

            return actual_tool(*args, **kwargs)(counted)

        return decorate

    def send(_client, request, **kwargs):
        assert request.url.host == "api.asqav.com", request.url
        body = json.loads(request.content)
        if request.url.path.endswith("/agents/create"):
            data = {
                "agent_id": "agent_test",
                "name": body["name"],
                "public_key": "test_key",
                "key_id": "test_kid",
                "algorithm": "ml-dsa-65",
                "capabilities": [],
                "created_at": 0,
            }
        else:
            assert request.url.path.endswith("/agents/agent_test/sign"), request.url
            state["requests"].append(body)
            action = body["action_type"]
            if (action == "tool:start" and case.startswith("refused")) or (
                action == "tool:end" and case == "end_failed"
            ):
                return httpx.Response(403, json={"detail": "Test refusal"}, request=request)
            data = {
                "signature": "test_signature",
                "signature_id": "signature_test",
                "action_id": "action_test",
                "timestamp": 0,
                "verification_url": "https://example.invalid/test",
            }
        return httpx.Response(200, json=data, request=request)

    readme = Path(__file__).resolve().parents[1] / "README.md"
    code = re.findall(r"```python\n(.*?)```", readme.read_text(), re.S)[0]
    actual_init = AsqavHooks.__init__

    def configure(hooks, **kwargs):
        actual_init(hooks, **kwargs, fail_closed=blocked)

    with (
        patch("crewai.LLM", return_value=LocalLLM()),
        patch("crewai.tools.tool", counted_tool),
        patch.object(AsqavHooks, "__init__", configure),
        patch.object(httpx.Client, "send", send),
        patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")),
        patch.object(socket.socket, "connect_ex", side_effect=AssertionError("Network forbidden")),
    ):
        exec(compile(code, str(readme), "exec"), {})

    assert state["tools"] == (0 if blocked else 1), state
    assert state["model_calls"] == 2, state
    actions = [request["action_type"] for request in state["requests"]]
    assert actions[0] == "tool:start", actions
    if not blocked:
        assert actions == ["tool:start", "tool:end"], actions
    else:
        # CrewAI dispatchers differ in whether a blocked call reaches after hooks.
        assert actions in (["tool:start"], ["tool:start", "tool:end"]), actions
    context = {"tool": "echo_tool", "input": "{'text': 'hello world'}"}
    expected_bytes = canonicalize_action("tool:start", context)
    start = state["requests"][0]
    assert "context" not in start, start
    assert start["hash"] == "sha256:" + hashlib.sha256(expected_bytes).hexdigest(), start
    assert start["payload_size"] == len(expected_bytes), start
    print(
        f"PASS real CrewAI {version('crewai')} / Asqav {version('asqav')}: "
        f"native={native} case={case} tool_calls={state['tools']} actions={actions}"
    )


if __name__ == "__main__":
    run_probe(sys.argv[1] == "True", sys.argv[2])
