# Third-party notices

The package under `src/tfagent/console/` is vendored from the Microsoft Agent
Framework Python harness console sample at commit
`68136ee081dbbee6983e6bb92a834f9ad30d20dc`.

Copyright (c) Microsoft Corporation. Licensed under the MIT License.

Source: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/harness/console

The vendored tool-call display observer includes a local compatibility patch
for OpenAI-compatible Chat Completions streams, whose argument deltas omit the
call id and function name after the initial header delta.
