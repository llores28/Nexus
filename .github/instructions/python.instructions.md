---
applyTo: '**/*.py'
---

<!-- nexus: profile=754255363160 generator=copilot.python nexus_version=0.2.0 -->

# Python conventions

- Never use `shell=True`, `eval()`, or `exec()`. Use `subprocess` argv lists.
- Public functions have type hints. Use `Optional`, `Literal`, and `TypedDict` for shapes that cross module boundaries. (warn)
