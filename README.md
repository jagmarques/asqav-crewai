<p align="center">
  <a href="https://asqav.com">
    <img src="https://asqav.com/logo-text-white.png" alt="Asqav" width="200">
  </a>
</p>
<p align="center">
  Stop a rogue agent before it acts, and prove what it tried.
</p>
<p align="center">
  <a href="https://www.asqav.com/">Website</a> |
  <a href="https://www.asqav.com/docs">Docs</a> |
  <a href="https://github.com/jagmarques/asqav-sdk">SDK</a>
</p>

# Asqav for CrewAI

Stop a rogue agent before it acts, and prove what it tried.

Uses CrewAI's [tool call hooks](https://docs.crewai.com/en/learn/tool-hooks) to sign every tool invocation with [Asqav](https://asqav.com), producing a tamper-evident record of what your crew attempted. By default the integration observes and records (fail-open, never blocks). Turn on fail-closed mode to block a tool the moment Asqav refuses to sign its start event.

## Install

Not yet on PyPI. Install from GitHub:

```bash
pip install "git+https://github.com/jagmarques/asqav-crewai.git"
```

Once published, the install will be:

```bash
pip install asqav-crewai
```

This pulls in the `asqav` SDK. CrewAI itself is a peer dependency you install separately (or via the `crewai` extra):

```bash
pip install "asqav-crewai[crewai]"
```

Tool call hooks require CrewAI 1.9.1 or newer.

## Usage

```python
import asqav
from crewai import Agent, Crew, Task
from asqav_crewai import AsqavHooks

asqav.init(api_key="sk_...")

# Register Asqav signing for every tool call in this process
AsqavHooks(agent_name="my-crew").register()

crew = Crew(agents=[...], tasks=[...])
result = crew.kickoff()
```

Every tool call your crew makes produces signed `tool:start` and `tool:end` events through the Asqav API. Signing runs server-side with NIST FIPS 204 ML-DSA cryptography, so the audit trail is tamper-evident and holds up for EU AI Act, DORA, and SOC 2 evidence.

## Fail-open vs fail-closed

By default signing is fail-open. If the Asqav API is unreachable, a warning is logged but the tool call proceeds normally. Your crew never breaks because of governance:

```python
AsqavHooks(agent_name="my-crew").register()  # observe and record only
```

To stop a rogue agent before it acts, enable fail-closed mode. When Asqav refuses to sign a tool's start event, the `before_tool_call` hook returns `False` and CrewAI blocks that tool. The attempt is still recorded:

```python
AsqavHooks(agent_name="my-crew", fail_closed=True).register()  # block on refused sign
```

## How it works

`AsqavHooks` extends the Asqav adapter base class and registers two global CrewAI hooks:

- `before_tool_call` - signs `tool:start` with tool name and an input preview
- `after_tool_call` - signs `tool:end` with tool name and output metadata

The `before_tool_call` hook receives a `ToolCallHookContext` (`tool_name`, `tool_input`, `tool`, `agent`, `task`, `crew`). In fail-open mode it always returns `None` (allow). In fail-closed mode it returns `False` (block) when the start signature is refused. The `after_tool_call` hook returns `None` and never alters the tool result.

## Data handling

`asqav-crewai` is a thin wrapper around the `asqav` Python SDK and inherits its mode behavior:

- Asqav cloud (`*.asqav.com`): the SDK hashes your action context locally and sends only the hash plus a small metadata bag. Raw prompts and tool arguments never leave your infrastructure.
- Self-hosted: the SDK sends the full context so the server can run policy checks, PII redaction, and richer audit views.

You can override per call:

```python
import asqav

asqav.init(api_key="sk_...", base_url="https://api.asqav.com", mode="hash-only")
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

MIT
