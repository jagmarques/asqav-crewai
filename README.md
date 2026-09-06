<p align="center">
  <a href="https://asqav.com">
    <img src="https://asqav.com/logo-text-white.png" alt="Asqav" width="200">
  </a>
</p>
<p align="center">
  Record CrewAI tool-call events with Asqav.
</p>
<p align="center">
  <a href="https://www.asqav.com/">Website</a> |
  <a href="https://www.asqav.com/docs">Docs</a> |
  <a href="https://github.com/jagmarques/asqav-sdk">SDK</a>
</p>

# Asqav for CrewAI

Uses CrewAI's [tool call hooks](https://docs.crewai.com/en/learn/tool-hooks) to attempt signing `tool:start` and `tool:end` events with [Asqav](https://asqav.com). Successful signing requests produce receipts signed on the Asqav server. Signing failures do not block tool execution by default. With `fail_closed=True`, a missing start signature blocks the tool call through CrewAI's hook mechanism.

Asqav governs the agents you wire through it. An agent that never routes through the governed path produces no receipt and is not detected.

## Install

```bash
pip install "asqav-crewai[crewai] @ git+https://github.com/jagmarques/asqav-crewai.git"
```

This installs the integration from GitHub. To use a local checkout instead, run this from its root:

```bash
pip install ".[crewai]"
```

CrewAI is a peer dependency; the `[crewai]` extra installs it. The integration requires CrewAI 1.9.1 or newer.

## Usage: record tool-call events

Set `ASQAV_API_KEY` to your Asqav API key and `CREWAI_MODEL` to your CrewAI model identifier. Configure that model provider's credentials. The example calls both the model provider and the Asqav API.

```python
import os

import asqav
from crewai import LLM, Agent, Crew, Task
from crewai.tools import tool

from asqav_crewai import AsqavHooks

asqav.init(api_key=os.environ["ASQAV_API_KEY"], mode="hash-only")

# Register once before running crews in this process.
AsqavHooks(agent_name="my-crew").register()


@tool("echo_tool")
def echo_tool(text: str) -> str:
    """Echo the given text back."""
    return f"echoed {text}"


agent = Agent(
    role="Echoer",
    goal="Echo one message via the echo tool",
    backstory="A minimal test agent.",
    llm=LLM(model=os.environ["CREWAI_MODEL"]),
    tools=[echo_tool],
)
task = Task(
    description="Echo the message 'hello world' using echo_tool.",
    expected_output="The echoed message.",
    agent=agent,
)
result = Crew(agents=[agent], tasks=[task]).kickoff()
print(result)
```

The hooks cover tool calls that reach CrewAI's hook dispatch. Model calls, direct calls to tool functions, and calls skipped by a blocking hook that runs first are outside the start hook's coverage. A crew that never reaches a tool hook produces no signing requests from this integration.

## Fail-open vs fail-closed

By default, a signing error is logged and the tool may proceed. A failed signing request does not guarantee a receipt:

```python
AsqavHooks(agent_name="my-crew").register()  # allow despite signing failure
```

Choose fail-closed mode when tool execution must wait for a start signature. A refusal or signing error that leaves no signature makes the before hook return `False`, which asks CrewAI to block that call. This does not guarantee that a blocked attempt was recorded. Agent creation or lookup happens when `AsqavHooks` is constructed and can raise in either mode.

```python
AsqavHooks(agent_name="my-crew", fail_closed=True).register()
```

## How it works

`AsqavHooks` extends the Asqav adapter base class and registers two global CrewAI hooks:

- `before_tool_call` attempts to sign `tool:start` with the tool name and an input preview capped at 200 characters.
- `after_tool_call` attempts to sign `tool:end` with the tool name, result type, and stringified result length. It returns `None` to leave the result unchanged.

An end event describes the result seen by the after hook. It does not by itself establish that the tool executed or succeeded. Failure to sign an end event cannot undo an executed tool.

## Data handling

The SDK controls how the hook context is sent to Asqav:

- In `hash-only` mode, the SDK sends a digest of the action and hook context, its byte length, and SDK metadata. The input preview is included in the digest, rather than sent as context.
- In `full-payload` mode, the SDK sends the hook context, including that input preview.

Other agent, model, and tool calls have their own data handling. Configure the SDK mode before constructing the hooks:

```python
import os

import asqav

asqav.init(api_key=os.environ["ASQAV_API_KEY"], mode="hash-only")
```

See the [SDK fingerprint spec](https://github.com/jagmarques/asqav-sdk/blob/main/docs/fingerprint-spec.md) for the canonicalization and conformance vectors.

## Configuration

```python
# Use an existing Asqav agent by ID
AsqavHooks(agent_id="ag_abc123").register()

# Override the API key
AsqavHooks(api_key="sk_other", agent_name="audit-crew").register()
```

## License

[Elastic License 2.0](LICENSE)
