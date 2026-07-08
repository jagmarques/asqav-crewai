# Changelog

Notable changes to asqav-crewai. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0]

First release.

### Added
- `AsqavHooks`: CrewAI tool-call hooks that sign `tool:start` and `tool:end`
  events through the Asqav SDK. Fail-open by default, with an optional
  fail-closed mode that blocks a tool when its `tool:start` signature is refused.
- `AsqavGuardrailProvider` and `enable_guardrail`: a pre-tool-call authorization
  layer over CrewAI's tool-call hook for gating a call before it runs.
- Tag-gated PyPI publish workflow using OIDC trusted publishing.
- Pull-request CI that runs the test suite and a `python -m build` plus
  `twine check` dry run.

### Changed
- Pinned the `asqav` SDK dependency to the 0.8 line (`asqav>=0.8.0,<0.9.0`).
