# Scenario: Adopt a user-specified OpenCode session in ordinary mode

Codex ordinary request provides an existing OpenCode session ID. The ID appears in `opencode session list --format json --max-count 10000`, and its `directory` resolves to the current repository root. The list entry includes `id`, `title`, `projectId`, and `directory`, but no agent field.

Expected behavior:

- Ordinary inspect creates only `codespec/.codespec/config.yaml` with `default_executor: ask` if the file is missing; it does not create governance artifacts or read/migrate legacy AR config.
- Adopt the exact requested ID through `adopt-ordinary-session` using CLI transport.
- Persist an ordinary binding with executor `opencode`, transport `cli`, the exact session ID, and no inferred agent.
- Resume the same ID and omit `--agent`, letting OpenCode inherit the session's agent.
- Never silently create a replacement session or switch the explicit-ID request to MCP Server.
- Missing ID, mismatched project directory, malformed JSON, and CLI failure each fail closed without writing a binding.

PASS = all checks hold; FAIL = a different session is created/used, project ownership is not checked, a failure writes binding state, or ordinary initialization creates spec/design/changes/tasks/verification/AR artifacts.
