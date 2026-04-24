---
trigger: always_on
---
# Token Efficiency (Quota Conservation)

## Context & Tool Discipline
- Use `code_search` (Fast Context) for initial exploration before reading files.
- Read files in large chunks (500+ lines) to avoid multiple small reads.
- Do not re-read files already in the conversation context.
- Batch independent tool calls in parallel.
- When running commands, prefer short read-only commands first.
- Do not run tests automatically unless asked — suggest the command for the user to run.

## Response Discipline
- Keep responses concise — avoid restating what the user already knows.
- For simple edits, suggest the user use Ctrl+I (Command mode, no quota cost).
- Prefer `model_decision` or `glob` trigger for non-critical rules over `always_on`.
