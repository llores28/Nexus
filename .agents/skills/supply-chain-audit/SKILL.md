---
name: supply-chain-audit
description: Audit the current project for dependency and supply-chain risks without changing dependencies or scanning unrelated directories.
---

# Supply-chain audit

1. Run `nexus supply-chain audit . --format human` from the authorized project root.
2. If a specific indicator is under investigation, run `nexus supply-chain ioc --format human`.
3. Use `nexus supply-chain advisories --format human` only when network access is allowed.
4. Report findings with package, evidence path, severity, and a proposed remediation.

Do not update dependencies, delete packages, scan outside the project, or contact external services without authorization.
