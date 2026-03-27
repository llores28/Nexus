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

## Model Selection — INTERACTIVE (Use ask_user_question)

**IMPORTANT**: When you detect a task that would benefit from a more capable model, you MUST use the `ask_user_question` tool to present model options to the user. Do NOT just mention it in text — present an interactive choice.

### When to Trigger Model Selection
Assess the user's request. If it matches these patterns AND current model is SWE-1.5 or a free tier:

| Task Type | Indicators | Recommended Model |
|-----------|------------|-------------------|
| **Complex** | Architecture, refactoring across modules, security hardening | GPT-5 Med (1x) or Gemini 3.1 Pro (1x) |
| **Expert** | Security audit, deep debugging, system design | Claude Sonnet 4.6 (2x) or GPT-5 High (2x) |
| **Frontier** | Novel architecture, threat modeling, research | Claude Opus 4.6 (2x) |

### How to Present Options
Use the `ask_user_question` tool with options like:

```
Question: "This looks like a [complex/expert/frontier] task. Would you like to switch models for better results?"

Options:
1. "[Recommended Model] (Xx cost) — Best for this task"
2. "Stay on current model — May have lower quality"
3. "Let me clarify the task first"
```

### When NOT to Trigger
- Simple tasks (edits, typos, explanations) — stay on SWE-1.5
- User explicitly said to use current model
- Already on a capable model for the task type
- Quick questions or clarifications

### Escalation Pattern
Start free (SWE-1.5), escalate only when task complexity warrants it.
Stick to one model per session to leverage context caching.

Reference: `nexus/model-selection-reference.md` for full model database.
