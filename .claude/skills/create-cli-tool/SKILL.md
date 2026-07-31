---
name: create-cli-tool
description: Scaffold a new project-specific CLI tool that inherits the security framework
---
# Create CLI Tool

## Trigger
- Model identifies a repetitive task that would benefit from automation
- User requests a custom CLI tool for the project
- User runs `/create-tool`

## Command
```
nexus scaffold <name> --project-dir . --description "What this tool does"
```

## What gets created
- `tools/nexus/<name>.py` — tracked, project-local executable with Nexus security imports

## Guardrails (enforced by template)
- No `shell=True` in subprocess calls
- No `eval()` or `exec()`
- All path inputs validated via `security.validate_path()`
- All URL inputs validated via `security.validate_url()`
- Must emit structured output via `utils.emit()`

## After scaffolding
1. Edit the generated file to implement tool logic
2. Test with `python tools/nexus/<name>.py --project-dir . --format human`
3. Commit the generated tool with the project source
