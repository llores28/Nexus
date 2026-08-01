# Nexus v0.3 Context Efficiency Report

Measured on the v0.3 implementation branch against its parent commit.

| Persistent instruction surface | Before | After |
|---|---:|---:|
| `AGENTS.md` | 9,008 bytes | 3,743 bytes |
| `CLAUDE.md` | 5,161 bytes | 299 bytes |
| `.github/copilot-instructions.md` | 3,979 bytes | 371 bytes |
| **Total** | **18,148 bytes** | **4,413 bytes** |

The persistent tracked instruction surface decreased by **75.7%**. These are
UTF-8 byte counts, not vendor-billed token claims. `nexus context audit`
estimates tokens at four characters per token and counts only Agent Skill
frontmatter as ambient discovery context; skill bodies remain just-in-time.

The final generated compatibility-fixture audit measured:

- zero duplicated instruction lines across generated provider surfaces;
- complete managed ignore coverage for Cursor, Aider, and Repomix; legacy
  Codeium ignore support remains opt-in migration compatibility;
- 12 canonical `.agents/skills` packages and 12 byte-equivalent Claude projections;
- estimated ambient context of 1,338 tokens for Codex/Devin/VS Code, 480 for
  Claude, 1,442 for Cursor, 1,430 for Copilot, and 1,112 for Devin Review;
- safe inventory fallback because Repomix was not installed;
- an initialized four-field journal summary below the 80-line limit.

For observation masking, a verbose successful pytest run measured 19,989 raw
characters. Its deterministic JSON digest was 1,176 characters, with 18,847
characters reported as omitted and the source identified by digest
`ebbabf0b73d11a88`. This is a measured size reduction for that observation,
not a claim about provider billing or universal token savings.

The audit remains `WARN` in a development checkout that retains ignored local
`.windsurf/*` migration fixtures or where the targeted secrets scan finds no
relevant config files (`coverage: none`). Legacy inputs are no longer tracked or
shipped, and neither condition is presented as a clean `PASS`.
