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

## Model Selection (Auto-Optimize)
Before each task, assess complexity and recommend the optimal model to the user.
Read `bootstrap/model-selection-reference.md` for the full model database and selection algorithm.

Quick decision guide (no need to read reference for these):
- **Simple tasks** (edits, typos, explanations, boilerplate): Stay on **SWE-1.5** (free).
- **Moderate tasks** (multi-file edits, unit tests, standard debug): Stay on **SWE-1.5**; suggest **GPT-5 Low** (0.5x) only if output quality is lacking.
- **Complex tasks** (architecture, refactoring across modules, security): Suggest **GPT-5 Med** (1x) or **Gemini 3.1 Pro** (1x).
- **Expert tasks** (architecture design, security audit, deep debug): Suggest **Claude Sonnet 4.6** (2x) or **GPT-5 High** (2x).
- **Frontier tasks** (novel design, threat modeling): Suggest **Claude Opus 4.6** (2x) or **Opus Thinking** (3x).

Always apply the **escalation pattern**: start free, escalate only if quality is insufficient.
Stick to one model per session to leverage context caching.
