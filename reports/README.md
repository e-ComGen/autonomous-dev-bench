# Reports

Generated reports are views over canonical evidence and independent suite results. A report may aggregate infrastructure health and display multiple capability vectors, but must not calculate a universal autonomous-development score or allow one metric to compensate for a critical hard-gate failure.

`zoning-preview/` contains compact Markdown examples from advisory full-project scans. The command also produces deterministic summary JSON and separate raw JSON payloads locally; those large generated files are ignored by Git. Preview maps have `authority: NONE` and are observations, not suite verdicts.
